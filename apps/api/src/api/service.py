"""Операции над данными компании — общие для эндпоинтов и инструментов агента.

На вход — репозиторий (`CompanyRepo`) и id компании, на выход — модели контракта; нет компании — None.
"""

from api.chain import build_chain
from api.contract import CompanyProfile, ExposureMap, InfluenceChain
from api.exposure import build_exposure
from api.profile import GROUP_MEMBERS_SHOWN, build_profile
from api.repo import CompanyRepo


def company_profile(repo: CompanyRepo, company_id: str) -> CompanyProfile | None:
    company = repo.get_company(company_id)
    if company is None:
        return None
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


def company_exposure(repo: CompanyRepo, company_id: str) -> ExposureMap | None:
    company = repo.get_company(company_id)
    if company is None:
        return None
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    return build_exposure(company, repo.flows(company.id), group)


def company_chain(
    repo: CompanyRepo, company_id: str, okved: list[str], weights: dict[str, float] | None = None
) -> InfluenceChain | None:
    """Через кого событие с классами ОКВЭД `okved` задевает компанию.

    `weights` — сила связи события с классом ОКВЭД (0–1), по умолчанию 1.
    """
    company = repo.get_company(company_id)
    if company is None:
        return None
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    return build_chain(company, repo.flows(company.id), group, okved, weights)
