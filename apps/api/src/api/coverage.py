"""Охват события в группе: сколько компаний группы задевает событие и на какую выручку — одно число на пару
«событие × компания».

Отсюда берут число лента (блок «Ваша группа» и вывод), эндпоинт `/group-impact` и агент (вердикт, ключевые
цифры) — поэтому оно не расходится между экранами. Событие — факторы и отрасли с силами из разметки парсера.
Строгий порог (`api.group.MIN_IMPACT`) никого не задевает, а событие доходит до компании через группу (канал
цепочки «группа») — берём и слабые связи: блок не может сказать «группу не касается» о событии, которое
касается компании именно через группу.
"""

from api.chain import build_chain
from api.contract import GroupImpact
from api.group import GroupContext, group_context, group_impact
from api.numbers import fmt_rub
from api.ranking import default_ranking
from api.records import CompanyRecord, Flow
from api.repo import CompanyRepo

Pairs = list[tuple[str, float]]


def coverage_phrase(impact: GroupImpact) -> str:
    """«127 из 368 других компаний группы с выручкой 127,1 млрд ₽» — одно определение на все экраны: N задетых
    из K компаний группы без вашей; так число стоит и в выводе ленты, и у агента."""
    others = impact.others_total or impact.companies_total - 1
    revenue = fmt_rub(impact.affected_revenue)
    return f"{impact.affected_count} из {others} других компаний группы с выручкой {revenue}"


def credit_phrase(impact: GroupImpact) -> str:
    """«из них с кредитом в банке — 3» — вторая часть того же определения, для ставки и долга."""
    return f"из них с кредитом в банке — {impact.affected_with_credit}"


def _through_group(
    company: CompanyRecord, flows: list[Flow], group: list[CompanyRecord], sectors: Pairs
) -> bool:
    weights: dict[str, float] = {}
    for okved, strength in sectors:
        weights[okved] = max(weights.get(okved, 0.0), strength)
    if not weights:
        return False
    chain = build_chain(company, flows, group, list(weights), weights)
    return any(c.kind == "group" for c in chain.channels)


def coverage_in(
    ctx: GroupContext,
    company: CompanyRecord,
    flows: list[Flow],
    group: list[CompanyRecord],
    factors: Pairs,
    sectors: Pairs,
    keep_empty: bool = False,
) -> GroupImpact | None:
    """Охват по уже собранным данным группы (лента считает их один раз на все события).

    `keep_empty` — вернуть и пустой охват («событие не касается других компаний группы»), а не None.
    """
    aliases = default_ranking().aliases
    impact = group_impact(ctx, factors, sectors, aliases)
    if not impact.affected_count and _through_group(company, flows, group, sectors):
        impact = group_impact(ctx, factors, sectors, aliases, 0.0)
    return impact if impact.affected_count or keep_empty else None


def event_coverage(
    repo: CompanyRepo, company_id: str, factors: Pairs, sectors: Pairs, keep_empty: bool = False
) -> GroupImpact | None:
    """Охват события с факторами `factors` и отраслями `sectors` (код, сила 0–1) в группе компании.

    Нет компании, группы или задетых компаний — None.
    """
    company = repo.get_company(company_id)
    if company is None or not company.group_id:
        return None
    group = repo.group_records(company.group_id, exclude=company.id)
    flows = repo.flows(company.id)
    ctx = group_context(company, group, flows)
    if ctx is None:
        return None
    return coverage_in(ctx, company, flows, group, factors, sectors, keep_empty)
