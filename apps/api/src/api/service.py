"""Операции над данными компании — общие для эндпоинтов и инструментов агента.

На вход — репозиторий (`CompanyRepo`) и id компании, на выход — модели контракта; нет компании — None.
"""

import datetime as dt

from api.chain import build_chain
from api.contract import CompanyProfile, ExposureMap, Feed, GroupImpact, InfluenceChain
from api.exposure import build_exposure
from api.group import group_context, group_impact
from api.news import NewsProvider
from api.personas import parse_persona_id
from api.profile import GROUP_MEMBERS_SHOWN, build_profile
from api.ranking import MSK, default_ranking, rank
from api.repo import CompanyRepo

# роли, которым в ленте показывается влияние на группу
GROUP_ROLES = {"owner", "ceo"}


def company_profile(repo: CompanyRepo, company_id: str) -> CompanyProfile | None:
    company = repo.get_company(company_id)
    if company is None:
        return None
    size, members, group_revenue = 1, [], None
    if company.group_id:
        size, members = repo.group(company.group_id, exclude=company.id, limit=GROUP_MEMBERS_SHOWN)
        stats = repo.group_stats([company.group_id]).get(company.group_id)
        group_revenue = stats.revenue if stats else None
    return build_profile(
        company,
        repo.flows(company.id),
        group_size=size,
        group_members=members,
        industry=repo.industry(company),
        group_revenue=group_revenue,
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


def persona_feed(
    repo: CompanyRepo,
    news: NewsProvider,
    persona: str,
    limit: int = 20,
    candidates: int = 500,
    days: int = 90,
    now: dt.datetime | None = None,
) -> Feed | None:
    """Лента пользователя: события, задевающие его компанию, по убыванию оценки с учётом роли.

    Пользователь — `p-u<номер компании>-<роль>`; компания должна быть действующим клиентом банка (сервис — для
    клиентов), иначе — None. Так ленту можно открыть для любого клиента, не только из `/api/personas`.
    """
    parsed = parse_persona_id(persona)
    if parsed is None:
        return None
    company_id, role = parsed
    company = repo.get_company(company_id)
    if company is None or company.client_type != "CLIENT":
        return None
    now = now or dt.datetime.now(MSK)
    flows = repo.flows(company.id)
    group = repo.group_records(company.group_id, exclude=company.id) if company.group_id else []
    exposure = build_exposure(company, flows, group)
    events = news.events(since=now - dt.timedelta(days=days), limit=candidates)
    items = rank(
        events,
        exposure,
        lambda okved, weights: build_chain(company, flows, group, okved, weights),
        role,
        now,
        bank_view=news.has_bank_view,
        regions={r for r in (company.region, company.city) if r},
    )
    items = items[:limit]
    # собственнику и гендиректору — блок «Ваша группа»: какие компании группы задевает событие
    if role in GROUP_ROLES and (ctx := group_context(company, group, flows)):
        by_id = {e.id: e for e in events}
        aliases = default_ranking().aliases
        for item in items:
            event = by_id[item.event_id]
            impact = group_impact(ctx, [(c, s) for c, s, _ in event.factors], event.sectors, aliases)
            if not impact.affected_count and item.channel == "group":
                # главный путь карточки — через группу: блок не может сказать «группу не касается»,
                # показываем участников и при слабой связи
                impact = group_impact(ctx, [(c, s) for c, s, _ in event.factors], event.sectors, aliases, 0.0)
            item.group_impact = impact if impact.affected_count else None
    return Feed(
        persona_id=persona,
        company_id=company.id,
        role=role,
        items=items,
        candidates=len(events),
        news_source=news.name,
    )


def company_group_impact(
    repo: CompanyRepo, company_id: str, okved: list[str], factors: list[str]
) -> tuple[bool, GroupImpact | None]:
    """Как событие с отраслями `okved` и факторами `factors` задевает группу компании.

    (найдена ли компания, влияние); у компании без группы влияние — None: блока «Ваша группа» нет.
    """
    company = repo.get_company(company_id)
    if company is None:
        return False, None
    if not company.group_id:
        return True, None
    group = repo.group_records(company.group_id, exclude=company.id)
    ctx = group_context(company, group, repo.flows(company.id))
    if ctx is None:
        return True, None
    impact = group_impact(
        ctx, [(f, 1.0) for f in factors], [(o, 1.0) for o in okved], default_ranking().aliases
    )
    return True, impact
