import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from ingest.db.schema import ensure_schema as ensure_search_schema
from psycopg_pool import ConnectionPool

from api.agent.routes import router as agent_router
from api.agent.service import build_service
from api.config import get_settings
from api.contract import CompanyProfile, CompanySummary, ExposureMap, Health, InfluenceChain, Persona
from api.db import connect, ensure_schema
from api.importer import DATA_FILES
from api.okved import sector_for
from api.personas import personas_for
from api.profile import LARGE_REVENUE, display_name
from api.repo import CompanyRepo, PgCompanyRepo
from api.search.repo import SearchRepo
from api.search.routes import router as search_router
from api.service import company_chain, company_exposure, company_profile

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
app.include_router(search_router)


app.include_router(agent_router)


def get_repo(request: Request) -> CompanyRepo:
    return request.app.state.repo


Repo = Annotated[CompanyRepo, Depends(get_repo)]


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


@app.get("/api/personas", response_model=list[Persona], tags=["пользователи"])
def list_personas(repo: Repo) -> list[Persona]:
    return personas_for(repo)
