import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from psycopg_pool import ConnectionPool

from api.agent.routes import router as agent_router
from api.agent.service import build_service
from api.config import get_settings
from api.contract import CompanyProfile, CompanySummary, Health, Persona
from api.db import connect, ensure_schema
from api.okved import sector_for
from api.personas import make_personas
from api.profile import GROUP_MEMBERS_SHOWN, build_profile, display_name
from api.repo import CompanyRepo, PgCompanyRepo

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    with connect(settings.database_url) as conn:
        ensure_schema(conn)
        conn.commit()
    # короткое ожидание соединения: /api/health должен быстро ответить 503, а не висеть
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, timeout=5, open=True)
    app.state.repo = PgCompanyRepo(pool)
    # модуль поиска, если подключён, кладёт свой SearchRepo в app.state.search — агент берёт его
    try:
        app.state.agent = build_service(settings, pool, app.state.repo, getattr(app.state, "search", None))
    except Exception:
        # агент не поднялся (опечатка в LLM_MODELS, битые файлы материалов) — остальное API работает
        logger.exception("агент не запустился")
        app.state.agent = None
    try:
        yield
    finally:
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
        return Health(status="degraded", db="unavailable")
    return Health(status="ok", db="ok", data=files)


@app.get("/api/companies", response_model=list[CompanySummary], tags=["компании"])
def list_companies(
    repo: Repo,
    large: Annotated[bool, Query(description="только крупные: выручка больше 15 млрд ₽")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CompanySummary]:
    return [
        CompanySummary(
            id=c.id,
            display_name=display_name(c, c.id),
            sector=sector_for(c.okved_code),
            okved=c.okved_code,
            revenue=c.revenue,
            region=c.region,
            client_type=c.client_type,
        )
        for c in repo.list_companies(large=large, limit=limit, offset=offset)
    ]


@app.get("/api/companies/{company_id}", response_model=CompanyProfile, tags=["компании"])
def get_company(company_id: str, repo: Repo) -> CompanyProfile:
    company = repo.get_company(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"компания {company_id} не найдена")
    size, members = 1, []
    if company.group_id:
        size, members = repo.group(company.group_id, exclude=company.id, limit=GROUP_MEMBERS_SHOWN)
    return build_profile(
        company,
        repo.flows(company.id),
        group_size=size,
        group_members=members,
        industry=repo.industry(company),
    )


@app.get("/api/personas", response_model=list[Persona], tags=["пользователи"])
def list_personas(repo: Repo) -> list[Persona]:
    return make_personas(repo.list_companies(large=True, limit=500, offset=0))
