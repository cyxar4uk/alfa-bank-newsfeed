import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from ingest.db.schema import ensure_schema as ensure_search_schema
from psycopg_pool import ConnectionPool

from api.agent.rerank import rerank
from api.agent.routes import router as agent_router
from api.agent.service import build_service
from api.config import get_settings
from api.contract import (
    ROLE_LABELS,
    CompanyProfile,
    CompanySummary,
    EventDetail,
    ExposureMap,
    Feed,
    GroupImpact,
    Health,
    InfluenceChain,
    Persona,
    SourceConnection,
    SourceEntry,
)
from api.db import connect, ensure_schema
from api.importer import DATA_FILES
from api.news import FallbackNews, NewsProvider, SearchNews, SnapshotNews
from api.okved import sector_for
from api.personas import parse_persona_id, personas_for
from api.profile import LARGE_REVENUE, display_name
from api.repo import CompanyRepo, PgCompanyRepo
from api.search.repo import SearchRepo
from api.search.routes import router as search_router
from api.service import company_chain, company_exposure, company_group_impact, company_profile, persona_feed
from api.sources import (
    Connections,
    MemoryConnections,
    PgConnections,
    catalog,
    catalog_entries,
    connect_message,
    entry_id,
)
from api.takeaway import takeaway

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    with connect(settings.database_url) as conn:
        ensure_schema(conn)
        ensure_search_schema(conn)  # таблицы новостей и аналитики банка (api.search); пересоздаёт загрузчик
        conn.commit()
    # короткое ожидание соединения: /api/health должен быстро ответить 503, а не висеть
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, timeout=5, open=True)
    app.state.repo = PgCompanyRepo(pool)
    app.state.search = SearchRepo(pool)
    app.state.connections = PgConnections(pool)
    # агент ищет новости и аналитику банка через app.state.search
    try:
        app.state.agent = build_service(settings, pool, app.state.repo, getattr(app.state, "search", None))
        # задачи, прерванные перезапуском, — failed, а не «идёт» вечно; только здесь: прогрев из того же
        # контейнера не должен ронять задачи работающего API
        app.state.agent.jobs.recover()
    except Exception:
        # агент не поднялся (опечатка в LLM_MODELS, битые файлы материалов) — остальное API работает
        logger.exception("агент не запустился")
        app.state.agent = None
    try:
        yield
    finally:
        if app.state.agent is not None:
            app.state.agent.jobs.shutdown()  # фоновые сборки не переживут остановку — после старта они failed
        pool.close()


app = FastAPI(
    title="Новостная аналитика для бизнес-решений",
    description=(
        "API сервиса: профиль компании по данным банка, тестовые пользователи, инсайты агента, трассы и "
        "отзывы."
    ),
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)


def get_repo(request: Request) -> CompanyRepo:
    return request.app.state.repo


Repo = Annotated[CompanyRepo, Depends(get_repo)]


# каталог источников — раньше роутера материалов: его /api/sources/{id} иначе поймал бы /api/sources/catalog
sources_router = APIRouter(prefix="/api/sources", tags=["источники"])


def get_connections(request: Request) -> Connections:
    return getattr(request.app.state, "connections", None) or _memory_connections


_memory_connections = MemoryConnections()  # без базы (тесты) — отметки в памяти процесса


def _persona_or_404(repo: CompanyRepo, persona: str) -> str:
    """Пользователь — действующий клиент банка, как у ленты: отметки не пишутся для несуществующих."""
    parsed = parse_persona_id(persona)
    company = repo.get_company(parsed[0]) if parsed else None
    if company is None or company.client_type != "CLIENT":
        raise HTTPException(status_code=404, detail=f"пользователь {persona} не найден")
    return persona


@sources_router.get("/catalog", response_model=list[SourceEntry])
def sources_catalog(
    repo: Repo,
    connections: Annotated[Connections, Depends(get_connections)],
    persona: Annotated[
        str, Query(description="id тестового пользователя: какие источники у него подключены")
    ],
) -> list[SourceEntry]:
    """Пул источников: российские и зарубежные, открытые и платные по API, подключён ли у пользователя и как
    подключить. Открытые ленты подключены всем — парсер их уже читает."""
    return catalog(connections, _persona_or_404(repo, persona))


@sources_router.post("/{source_id}/connect", response_model=SourceConnection)
def connect_source(
    repo: Repo,
    source_id: str,
    connections: Annotated[Connections, Depends(get_connections)],
    persona: Annotated[str, Query(description="id тестового пользователя")],
) -> SourceConnection:
    """Отметить источник подключённым. Ключи API в прототипе не принимаются: в ответе — куда ключ кладётся
    на сервере."""
    persona = _persona_or_404(repo, persona)
    source_id = entry_id(source_id)  # любая лента издателя — его запись в каталоге
    if not any(e["id"] == source_id for e in catalog_entries()):
        raise HTTPException(status_code=404, detail=f"источник {source_id} не найден")
    connections.connect(persona, source_id)
    entry = next(e for e in catalog(connections, persona) if e.id == source_id)
    raw = next(e for e in catalog_entries() if e["id"] == source_id)
    return SourceConnection(source=entry, message=connect_message(raw))


app.include_router(sources_router)
app.include_router(search_router)


app.include_router(agent_router)


@app.get("/api/health", response_model=Health, tags=["служебное"])
def health(repo: Repo, response: Response) -> Health:
    try:
        files = repo.imported_files()
    except Exception:
        response.status_code = 503
        return Health(status="degraded", db="unavailable", warnings=["база данных недоступна"])
    loaded = {f.file: f for f in files}
    warnings = []
    for name in DATA_FILES:
        if name not in loaded:
            warnings.append(
                f"файл {name} не загружен: положите CSV кейса в DATA_DIR/companies"
                " (по умолчанию data/raw/companies) и перезапустите импорт — `docker compose up import`"
            )
        elif not loaded[name].rows_loaded:
            warnings.append(f"файл {name} загружен, но в нём нет ни одной годной строки")
    # API живо — отвечаем 200, а нехватку данных показываем в статусе и предупреждениях
    return Health(status="degraded" if warnings else "ok", db="ok", data=files, warnings=warnings)


@app.get("/api/companies", response_model=list[CompanySummary], tags=["компании"])
def list_companies(
    repo: Repo,
    large: Annotated[
        bool, Query(description="только крупный бизнес: выручка группы (или своя вне группы) > 15 млрд ₽")
    ] = False,
    clients_only: Annotated[bool, Query(description="только действующие клиенты банка (CLIENT)")] = True,
    per_group: Annotated[bool, Query(description="от каждой группы одна компания — крупнейшая")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CompanySummary]:
    companies = repo.list_companies(
        large=large, limit=limit, offset=offset, clients_only=clients_only, per_group=per_group
    )
    groups = repo.group_stats([c.group_id for c in companies if c.group_id])
    result = []
    for c in companies:
        stats = groups.get(c.group_id) if c.group_id else None
        basis = stats.revenue if stats and stats.revenue else c.revenue
        result.append(
            CompanySummary(
                id=c.id,
                display_name=display_name(c, c.id),
                sector=sector_for(c.okved_code),
                okved=c.okved_code,
                revenue=c.revenue,
                group_id=c.group_id,
                group_revenue=stats.revenue if stats else None,
                group_size=stats.size if stats else None,
                large=bool(basis and basis > LARGE_REVENUE),
                region=c.region,
                client_type=c.client_type,
            )
        )
    return result


@app.get("/api/companies/{company_id}", response_model=CompanyProfile, tags=["компании"])
def get_company(company_id: str, repo: Repo) -> CompanyProfile:
    profile = company_profile(repo, company_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"компания {company_id} не найдена")
    return profile


@app.get("/api/companies/{company_id}/exposure", response_model=ExposureMap, tags=["компании"])
def get_exposure(company_id: str, repo: Repo) -> ExposureMap:
    """Карта чувствительности: к чему уязвима компания, сила, канал и доказательства каждого фактора."""
    exposure = company_exposure(repo, company_id)
    if exposure is None:
        raise HTTPException(status_code=404, detail=f"компания {company_id} не найдена")
    return exposure


@app.get("/api/companies/{company_id}/chain", response_model=InfluenceChain, tags=["компании"])
def get_chain(
    company_id: str,
    repo: Repo,
    okved: Annotated[list[str], Query(description="классы ОКВЭД события, например 56 или 46.71")],
) -> InfluenceChain:
    """Цепочка влияния: через кого событие в этих отраслях задевает компанию.

    Каналы — напрямую, через покупателей, поставщиков и группу.
    """
    # коды можно передать и повтором параметра, и через запятую: okved=56&okved=10 или okved=56,10
    codes = [code for value in okved for code in value.split(",") if code.strip()]
    chain = company_chain(repo, company_id, codes)
    if chain is None:
        raise HTTPException(status_code=404, detail=f"компания {company_id} не найдена")
    return chain


def optional_news(request: Request) -> NewsProvider | None:
    """Источник новостей, если он есть: без него эндпоинт работает по явно переданным отраслям и факторам."""
    try:
        return news_provider(request)
    except HTTPException:
        return None


@app.get("/api/companies/{company_id}/group-impact", response_model=GroupImpact | None, tags=["компании"])
def get_group_impact(
    company_id: str,
    repo: Repo,
    news: Annotated[NewsProvider | None, Depends(optional_news)],
    event_id: Annotated[
        str | None, Query(description="событие из ленты (src:news:…): отрасли и факторы — из его разметки")
    ] = None,
    okved: Annotated[list[str], Query(description="отрасли события, например 42 или 41,42")] = [],  # noqa: B006
    factor: Annotated[list[str], Query(description="факторы события, например rate или gov")] = [],  # noqa: B006
) -> GroupImpact | None:
    """Какие компании группы задевает событие, через какие факторы и на какую выручку; нет группы — null.

    Событие — по `event_id` (как в карточке ленты) или явно: отрасли `okved` и факторы `factor`.
    """
    codes = [c for value in okved for c in value.split(",") if c.strip()]
    factors = [f for value in factor for f in value.split(",") if f.strip()]
    event = None
    if event_id:
        if news is None:
            raise HTTPException(status_code=503, detail="нет новостей: ни базы поиска, ни снимка")
        event = news.event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail=f"событие {event_id} не найдено")
    elif not codes and not factors:
        # без события ответ «группу не касается» был бы ложным: спрашивать не о чем
        raise HTTPException(status_code=422, detail="укажите событие: event_id, okved или factor")
    found, impact = company_group_impact(repo, company_id, codes, factors, event)
    if not found:
        raise HTTPException(status_code=404, detail=f"компания {company_id} не найдена")
    return impact


def news_provider(request: Request) -> NewsProvider:
    """База новостей поиска, если она подключена (пустая — со снимком в запасе); иначе — снимок data/demo."""
    path = get_settings().news_snapshot
    snapshot = SnapshotNews(path) if path.is_file() else None
    search = getattr(request.app.state, "search", None)
    if search is not None:
        return FallbackNews(SearchNews(search), snapshot)
    if snapshot is None:
        raise HTTPException(status_code=503, detail=f"нет новостей: ни базы поиска, ни снимка {path}")
    return snapshot


@app.get("/api/feed", response_model=Feed, tags=["лента"])
@app.get("/api/briefing", response_model=Feed, tags=["лента"], summary="Брифинг — то же, что лента")
def get_feed(
    request: Request,
    repo: Repo,
    news: Annotated[NewsProvider, Depends(news_provider)],
    persona: Annotated[str, Query(description="id тестового пользователя, например p-u8318-cfo")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    llm: Annotated[bool, Query(description="дооценить верх ленты моделью (слагаемое llm)")] = True,
) -> Feed:
    """Лента пользователя: события, которые задевают его компанию, с оценкой и её разложением.

    Верх ленты дополнительно оценивает дешёвая модель — слагаемое `llm` в разложении; без моделей или бюджета
    лента остаётся формальной."""
    settings = get_settings()
    feed = persona_feed(
        repo, news, persona, limit=limit, candidates=settings.feed_candidates, days=settings.feed_days
    )
    if feed is None:
        raise HTTPException(
            status_code=404, detail=f"пользователь {persona} не найден или его компания не действующий клиент"
        )
    agent = getattr(request.app.state, "agent", None)
    _mark_ready(agent, feed)
    if llm and settings.feed_llm_top and agent is not None and agent.llm is not None:
        exposure = company_exposure(repo, feed.company_id)
        if exposure is not None:
            feed = rerank(
                feed, agent.llm, exposure, ROLE_LABELS.get(feed.role, ""), top_n=settings.feed_llm_top
            )
            # оценка модели меняет вывод: «не задевает» — только «к сведению»
            for item in feed.items:  # пересортировка могла сдвинуть оценённые моделью ниже верха
                item.takeaway = takeaway(item, feed.role)
    return feed


def _mark_ready(agent, feed: Feed) -> None:
    """Какие карточки уже собраны — экрану не нужно спрашивать статус по каждому событию."""
    if agent is None:
        return
    try:
        ready = agent.ready_events([i.event_id for i in feed.items], feed.persona_id)
        for item in feed.items:
            item.insight_ready = item.event_id in ready
    except Exception:
        logger.warning("не удалось проверить готовые карточки ленты", exc_info=True)


@app.get("/api/search", response_model=Feed, tags=["лента"])
def search_feed(
    request: Request,
    repo: Repo,
    news: Annotated[NewsProvider, Depends(news_provider)],
    q: Annotated[str, Query(min_length=2, max_length=200, description="что искать в новостях")],
    persona: Annotated[str, Query(description="id тестового пользователя")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Feed:
    """Поиск по новостям в формате ленты: задевающие компанию пользователя — первыми, с оценкой и выводом;
    остальные найденные — следом с оценкой 0 и выводом «к сведению»."""
    settings = get_settings()
    feed = persona_feed(
        repo, news, persona, limit=limit, candidates=min(settings.feed_candidates, 100), query=q
    )
    if feed is None:
        raise HTTPException(
            status_code=404, detail=f"пользователь {persona} не найден или его компания не действующий клиент"
        )
    _mark_ready(getattr(request.app.state, "agent", None), feed)
    return feed


@app.get("/api/events/{event_id:path}", response_model=EventDetail, tags=["лента"])
def get_event(event_id: str, news: Annotated[NewsProvider, Depends(news_provider)]) -> EventDetail:
    """Новость целиком: полный текст (если парсер получил его законно — полный RSS или открытая страница),
    картинка, ссылка на первоисточник; нет полного текста — `text: null`, лид в `source.fragment`."""
    event = news.event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"событие {event_id} не найдено")
    return EventDetail(
        id=event.id,
        source=event.source(),
        text=event.text,
        url=event.url,
        image_url=event.image_url,
        source_icon_url=event.source_icon_url,
    )


@app.get("/api/personas", response_model=list[Persona], tags=["пользователи"])
def list_personas(repo: Repo) -> list[Persona]:
    return personas_for(repo)
