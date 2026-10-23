from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from psycopg_pool import ConnectionPool

from api.config import get_settings
from api.contract import CompanyProfile, CompanySummary, ExposureMap, Health, InfluenceChain, Persona
from api.db import connect, ensure_schema
from api.okved import sector_for
from api.personas import DEMO_COMPANIES, make_personas
from api.profile import LARGE_REVENUE, display_name
from api.repo import CompanyRepo, PgCompanyRepo
from api.service import company_chain, company_exposure, company_profile


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    with connect(settings.database_url) as conn:
        ensure_schema(conn)
        conn.commit()
    # короткое ожидание соединения: /api/health должен быстро ответить 503, а не висеть
    pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, timeout=5, open=True)
    app.state.repo = PgCompanyRepo(pool)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(
    title="Новостная аналитика для бизнес-решений",
    description="API сервиса: профиль компании по данным банка, тестовые пользователи, контракт инсайта.",
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)


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
    # персоны — у действующих клиентов крупного бизнеса: демо-клиенты и крупнейшие компании групп
    leaders = repo.list_companies(large=True, limit=1000, offset=0, clients_only=True, per_group=True)
    known = {c.id for c in leaders}
    demo = [repo.get_company(cid) for cid in DEMO_COMPANIES if cid not in known]
    return make_personas([*leaders, *(c for c in demo if c)])
