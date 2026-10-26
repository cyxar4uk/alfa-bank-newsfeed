import datetime as dt
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from ingest.db.schema import ensure_schema as ensure_search_schema
from psycopg_pool import ConnectionPool

from api import inputs, market
from api.agent.loop import insight_id
from api.agent.rerank import rerank
from api.agent.routes import router as agent_router
from api.agent.service import build_service
from api.cache import FEEDS
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
    Related,
    RiskMap,
    SourceConnection,
    SourceEntry,
    UserInputs,
    UserInputsIn,
)
from api.db import connect, ensure_schema
from api.images import ImageError, proxied
from api.images import fetch as fetch_image
from api.importer import DATA_FILES
from api.inputs import PgInputs
from api.levels import LEVELS
from api.market import PgMarket
from api.news import FallbackNews, NewsProvider, SearchNews, SnapshotNews
from api.okved import sector_for
from api.personas import DEMO_PERSONAS, parse_persona_id, persona_id, personas_for
from api.precompute import Precompute, PrecomputeStatus
from api.products import attach_products
from api.profile import LARGE_REVENUE, display_name
from api.ranking import MSK
from api.repo import CompanyRepo, PgCompanyRepo
from api.search.repo import SearchRepo
from api.search.routes import router as search_router
from api.service import (
    WEEK_EVENTS,
    company_chain,
    company_exposure,
    company_group_impact,
    company_profile,
    company_related,
    company_risk_map,
    finish_week,
    persona_feed,
    week_events,
)
from api.sources import (
    Connections,
    MemoryConnections,
    PgConnections,
    WithoutPublishers,
    catalog,
    catalog_entries,
    company_industries,
    connect_message,
    disconnect_message,
    entry_id,
    publishers_of,
)
from api.takeaway import takeaways
from api.takeaway_llm import demote_unrelated, write_top

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
    inputs.STORE = PgInputs(pool)
    market.MARKET = PgMarket(pool)
    # агент ищет новости и аналитику банка через app.state.search
    app.state.agent_error = None
    try:
        app.state.agent = build_service(settings, pool, app.state.repo, getattr(app.state, "search", None))
        # задачи, прерванные перезапуском, — failed, а не «идёт» вечно; только здесь: прогрев из того же
        # контейнера не должен ронять задачи работающего API
        app.state.agent.jobs.recover()
    except Exception as exc:
        # агент не поднялся (опечатка в LLM_MODELS, битые файлы материалов) — остальное API работает
        logger.exception("агент не запустился")
        app.state.agent = None
        app.state.agent_error = f"{type(exc).__name__}: {exc}"[:300]
    if settings.feed_warmup:
        threading.Thread(target=warm_feeds, args=(app.state,), name="warm-feeds", daemon=True).start()
    app.state.precompute = make_precompute(app.state, settings)
    if settings.precompute_enabled and app.state.agent is not None:
        # первый цикл сразу после старта — это и есть прогрев демо после выкатки
        app.state.precompute.start(settings.precompute_every_s)
    try:
        yield
    finally:
        app.state.precompute.shutdown()
        if app.state.agent is not None:
            app.state.agent.jobs.shutdown()  # фоновые сборки не переживут остановку — после старта они failed
        pool.close()


WARM_EVERY = 12 * 60  # чаще, чем истекает кэш лент (15 мин): демо-пользователь не попадает на холодную ленту


def warm_feeds(state, rounds: int | None = None) -> None:
    """Прогреть ленту за день, неделю и карту рисков демо-пользователей и держать их тёплыми.

    Первый запрос недели с оценкой модели идёт до минуты; жюри открывает именно демо-пользователей."""
    done = 0
    while rounds is None or done < rounds:
        for company_id, role, _ in DEMO_PERSONAS:
            try:
                warm_one(state, company_id, role)
            except Exception:  # прогрев — не работа API: сбой одного пользователя не мешает остальным
                logger.warning("не прогрета лента %s %s", company_id, role, exc_info=True)
        done += 1
        if rounds is None or done < rounds:
            time.sleep(WARM_EVERY)


def warm_one(state, company_id: str, role: str) -> None:
    persona = persona_id(company_id, role)
    news = news_for(state)
    agent = getattr(state, "agent", None)
    for period in ("day", "week"):
        FEEDS.get_or_compute(
            (persona, period, 20, True, news.name),
            lambda period=period: build_feed(state.repo, news, agent, persona, 20, True, period),
            refresh=True,
        )
    FEEDS.get_or_compute(
        ("risk", company_id, persona, news.name),
        lambda: company_risk_map(state.repo, news, company_id, persona),
        refresh=True,
    )


def make_precompute(state, settings) -> Precompute:
    """Планировщик разборов заранее для демо-пользователей; лента — та же, что на экране (кэш лент)."""

    def feed_for(persona: str) -> Feed | None:
        news = news_for(state)
        agent = getattr(state, "agent", None)
        return FEEDS.get_or_compute(
            (persona, "day", 20, True, news.name),
            lambda: build_feed(state.repo, news, agent, persona, 20, True, "day"),
        )

    return Precompute(
        getattr(state, "agent", None),
        [persona_id(company_id, role) for company_id, role, _ in DEMO_PERSONAS],
        feed_for,
        budget_rub=settings.precompute_budget_rub,
        per_hour=settings.precompute_per_hour,
        in_flight=settings.precompute_in_flight,
        watch=settings.precompute_watch,
        enabled=settings.precompute_enabled,
    )


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


def _okveds(repo: CompanyRepo, persona: str) -> set[str]:
    """Отрасли пользователя для пометки «для вашей отрасли»: его компания и её ключевые контрагенты."""
    parsed = parse_persona_id(persona)
    company = repo.get_company(parsed[0]) if parsed else None
    return company_industries(company, repo.flows(company.id)) if company is not None else set()


def _source_or_404(source_id: str) -> dict:
    source_id = entry_id(source_id)  # любая лента издателя — его запись в каталоге
    raw = next((e for e in catalog_entries() if e["id"] == source_id), None)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"источник {source_id} не найден")
    return raw


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
    persona = _persona_or_404(repo, persona)
    return catalog(connections, persona, _okveds(repo, persona))


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
    raw = _source_or_404(source_id)
    connections.connect(persona, raw["id"])
    entry = next(e for e in catalog(connections, persona, _okveds(repo, persona)) if e.id == raw["id"])
    return SourceConnection(source=entry, message=connect_message(raw))


@app.get("/api/personas/{persona}/inputs", response_model=UserInputs | None, tags=["пользователи"])
def get_inputs(repo: Repo, persona: str) -> UserInputs | None:
    """«Мои числа» пользователя — долг, тип ставки, валютные закупки, закупка топлива; не вводил — null."""
    return inputs.STORE.get(_persona_or_404(repo, persona))


@app.put("/api/personas/{persona}/inputs", response_model=UserInputs, tags=["пользователи"])
def put_inputs(repo: Repo, persona: str, body: UserInputsIn) -> UserInputs:
    """Сохранить «мои числа»: разбор события посчитает последствия в рублях компании. Незаполненное — null."""
    return inputs.STORE.put(_persona_or_404(repo, persona), body)


@sources_router.post("/{source_id}/disconnect", response_model=SourceConnection)
def disconnect_source(
    repo: Repo,
    source_id: str,
    connections: Annotated[Connections, Depends(get_connections)],
    persona: Annotated[str, Query(description="id тестового пользователя")],
) -> SourceConnection:
    """Отключить источник у пользователя: новости открытой ленты уходят из его ленты, брифинга и поиска
    (у остальных пользователей остаются); отметка «подключён» у платного снимается. Вернуть — `connect`."""
    persona = _persona_or_404(repo, persona)
    raw = _source_or_404(source_id)
    connections.disconnect(persona, raw["id"])
    entry = next(e for e in catalog(connections, persona, _okveds(repo, persona)) if e.id == raw["id"])
    return SourceConnection(source=entry, message=disconnect_message(raw))


app.include_router(sources_router)
app.include_router(search_router)


app.include_router(agent_router)


@app.get("/api/precompute/status", response_model=PrecomputeStatus, tags=["служебное"])
def precompute_status(request: Request) -> PrecomputeStatus:
    """Разборы заранее: сколько собрано до открытия, хиты кэша, потрачено за сутки, почему стоит."""
    pre = getattr(request.app.state, "precompute", None)
    if pre is None:  # без lifespan (тесты) — планировщик не создан
        pre = make_precompute(request.app.state, get_settings())
    return pre.status()


@app.get("/api/health", response_model=Health, tags=["служебное"])
def health(request: Request, repo: Repo, response: Response) -> Health:
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
    status = "degraded" if warnings else "ok"
    # агент — не данные: причина, почему он не отвечает, — в предупреждениях, статус от неё не меняется
    agent = getattr(request.app.state, "agent", None)
    if agent is None and getattr(request.app.state, "agent_error", None):
        warnings.append(f"агент не запустился: {request.app.state.agent_error}")
    elif agent is not None and agent.llm is None:
        warnings.append("агент выключен: не заданы LLM_API_KEY и LLM_BASE_URL (в .env или в окружении)")
    return Health(status=status, db="ok", data=files, warnings=warnings)


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
    """База новостей поиска, если она подключена (пустая — со снимком в запасе); иначе — снимок data/demo.

    Источники, которые пользователь (`persona` в запросе) отключил в каталоге, из его новостей убраны."""
    provider = news_for(request.app.state)
    persona = request.query_params.get("persona")
    try:
        off = get_connections(request).disconnected(persona) if persona else set()
    except Exception:  # лента важнее фильтра: без базы отметок показываем все источники
        logger.warning("не удалось прочитать отключённые источники", exc_info=True)
        off = set()
    return WithoutPublishers(provider, publishers_of(off)) if off else provider


def news_for(state) -> NewsProvider:
    path = get_settings().news_snapshot
    snapshot = SnapshotNews(path) if path.is_file() else None
    search = getattr(state, "search", None)
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
    period: Annotated[
        Literal["day", "week"],
        Query(
            description="day — лента; week — «Главное за неделю»: 3–5 сюжетов недели, позиция банка, действие"
        ),
    ] = "day",
) -> Feed:
    """Лента пользователя: события, которые задевают его компанию, с оценкой и её разложением.

    Верх ленты дополнительно оценивает дешёвая модель — слагаемое `llm` в разложении; без моделей или бюджета
    лента остаётся формальной. `period=week` — события за 7 дней и сюжеты недели (`stories`): события
    одной темы, динамика и пик по числу новостей по дням, вывод с охватом группы.

    Готовая лента живёт 15 минут (api.cache): второй запрос с главной или вкладки отвечает сразу."""
    agent = getattr(request.app.state, "agent", None)
    key = (persona, period, limit, llm, news.name)
    feed = FEEDS.get_or_compute(key, lambda: build_feed(repo, news, agent, persona, limit, llm, period))
    if feed is None:
        raise HTTPException(
            status_code=404, detail=f"пользователь {persona} не найден или его компания не действующий клиент"
        )
    feed = feed.model_copy(deep=True)  # готовность карточек — своя у каждого запроса
    _mark_ready(agent, feed)
    return feed


def build_feed(
    repo: CompanyRepo, news: NewsProvider, agent, persona: str, limit: int, llm: bool, period: str
) -> Feed | None:
    """Лента или неделя пользователя целиком — с оценкой модели и закреплённым уровнем; не клиент — None."""
    settings = get_settings()
    now = dt.datetime.now(MSK)
    if period == "week" and not _client_persona(repo, persona):
        return None
    events = week_events(news, now) if period == "week" else None  # неделю грузим только для своих
    feed = persona_feed(
        repo,
        news,
        persona,
        limit=WEEK_EVENTS if events is not None else limit,
        candidates=settings.feed_candidates,
        days=settings.feed_days,
        now=now,
        events=events,
    )
    if feed is None:
        return None
    exposure = company_exposure(repo, feed.company_id)
    if llm and settings.feed_llm_top and agent is not None and agent.llm is not None:
        if exposure is not None:
            feed = rerank(
                feed, agent.llm, exposure, ROLE_LABELS.get(feed.role, ""), top_n=settings.feed_llm_top
            )
            # оценка модели меняет вывод: «не задевает» — к сведению и в свёрнутую часть; верх пишет модель
            feed = demote_unrelated(feed)
            takeaways(feed.items, feed.role, exposure)
            feed = write_top(feed, agent.llm, exposure, ROLE_LABELS.get(feed.role, ""))
    # уровень, однажды показанный, — тот же в дне, неделе и карточке (api.levels); сюжеты недели берут его же
    feed = LEVELS.pin(feed, exposure)
    attach_products(feed.items, feed.role, repo.get_company(feed.company_id), exposure)
    if events is not None:
        feed = finish_week(feed, events, news, now, limit, exposure)
    return feed


@app.get("/api/companies/{company_id}/risk-map", response_model=RiskMap, tags=["компании"])
def get_risk_map(
    company_id: str,
    repo: Repo,
    news: Annotated[NewsProvider, Depends(news_provider)],
    persona: Annotated[str, Query(description="пользователь этой компании: порядок факторов — для его роли")],
) -> RiskMap:
    """К чему уязвима компания: 5–7 факторов по силе и роли — почему (число из данных банка), что с фактором
    на этой неделе, позиция банка и новости по дням; `limits` — чего не оцениваем."""
    risk = FEEDS.get_or_compute(
        ("risk", company_id, persona, news.name), lambda: company_risk_map(repo, news, company_id, persona)
    )
    if risk is None:
        raise HTTPException(
            status_code=404, detail=f"компания {company_id} или пользователь {persona} не найдены"
        )
    return risk


def _client_persona(repo: CompanyRepo, persona: str) -> bool:
    parsed = parse_persona_id(persona)
    company = repo.get_company(parsed[0]) if parsed else None
    return company is not None and company.client_type == "CLIENT"


def _mark_ready(agent, feed: Feed) -> None:
    """Какие карточки уже собраны — экрану не нужно спрашивать статус по каждому событию."""
    _mark_items(agent, feed.items, feed.persona_id)


def _mark_items(agent, items: list, persona_id: str) -> None:
    if agent is None:
        return
    try:
        ready = agent.ready_events([i.event_id for i in items], persona_id)
        jobs = getattr(agent, "jobs", None)
        for item in items:
            item.insight_ready = item.event_id in ready
            key = insight_id(item.event_id, persona_id)
            job = jobs.get(key) if jobs and not item.insight_ready else None
            busy = job is not None and job.status in ("queued", "running")
            # ready — откроется мгновенно; queued — собирается (разбор заранее или по запросу)
            item.insight_state = "ready" if item.insight_ready else "queued" if busy else "none"
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
    exposure = company_exposure(repo, feed.company_id)
    feed = LEVELS.pin(feed, exposure, remember=False)
    attach_products(feed.items, feed.role, repo.get_company(feed.company_id), exposure)
    if feed.items and not any(i.relevance.score > 0 for i in feed.items):
        feed.note = f"По запросу «{q}» нашлись новости, но ни одна не касается вашей компании — для справки."
    elif not feed.items:
        feed.note = f"По запросу «{q}» новостей не найдено."
    return feed


# раньше /api/events/{event_id:path}: путь id с двоеточиями и слэшами иначе поглотил бы «/related»
@app.get("/api/events/{event_id:path}/related", response_model=Related, tags=["лента"])
def get_related(
    request: Request,
    event_id: str,
    repo: Repo,
    news: Annotated[NewsProvider, Depends(news_provider)],
    persona: Annotated[str, Query(description="id тестового пользователя: выводы и уровни — для него")],
) -> Related:
    """«По этой теме»: 3–6 событий ленты пользователя за две недели — того же сюжета, фактора или близкие по
    заголовку, без перепечаток, свежие выше. С выводом и уровнем, как в ленте."""
    items = FEEDS.get_or_compute(
        ("related", event_id, persona, news.name), lambda: company_related(repo, news, persona, event_id)
    )
    if items is None:
        if news.event(event_id) is None:
            raise HTTPException(status_code=404, detail=f"событие {event_id} не найдено")
        raise HTTPException(status_code=404, detail=f"пользователь {persona} не найден")
    items = [i.model_copy(deep=True) for i in items]  # готовность карточек — своя у каждого запроса
    _mark_items(getattr(request.app.state, "agent", None), items, persona)
    return Related(event_id=event_id, items=items)  # картинки уже через прокси (api.ranking)


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
        image_url=proxied(event.image_url),
        source_icon_url=proxied(event.source_icon_url),
    )


@app.get(
    "/api/img",
    tags=["лента"],
    response_class=Response,
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "картинка"},
        403: {},
        413: {},
        415: {},
        502: {},
    },
)
def get_image(u: Annotated[str, Query(max_length=2000, description="адрес картинки у издателя")]) -> Response:
    """Картинка новости через наш адрес: хосты изданий из каталога, публичные адреса, картинка до 2 МБ."""
    try:
        data, kind = fetch_image(u, get_settings().img_cache_dir)
    except ImageError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    headers = {
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'",
    }
    return Response(content=data, media_type=kind, headers=headers)


@app.get("/api/personas", response_model=list[Persona], tags=["пользователи"])
def list_personas(repo: Repo) -> list[Persona]:
    return personas_for(repo)
