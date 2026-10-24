"""Влияние события на группу компаний: каких участников оно касается, через что и на какую выручку.

Для каждого участника группы — карта чувствительности по его собственным данным (отрасль, продукты банка, ВЭД;
платежей участников не берём — их нет в запросе и они не нужны, чтобы назвать канал). Без базового уровня,
общего для всех компаний (сигналы `always`), и без факторов, которые касаются всех (инфляция, регион).

Участник затронут, если событие в его отрасли (подотрасль-сосед того же класса — половина силы) или бьёт
по фактору, к которому он чувствителен хотя бы с силой MIN_FACTOR, и итоговая сила связи — событие ×
чувствительность — не ниже MIN_IMPACT. Затронут — не обязательно в минус: высокая ставка — выгода держателям
депозитов; знак влияния — дело агента.

Платежи компании пользователя с затронутыми участниками — отдельно: это внутригрупповой оборот.
"""

import time
from dataclasses import dataclass

from api.contract import AffectedMember, FactorExposure, FeedFactor, GroupImpact
from api.exposure import Catalog, build_exposure, default_catalog
from api.okved import SECTOR_BY_CODE, okved_prefix, sector_for
from api.profile import Flows, aggregate_flows, display_name, format_rub, format_share
from api.records import CompanyRecord, Flow

MEMBERS_SHOWN = 10
# чувствительность участника к фактору, с которой он может быть затронут (капиталоёмкая отрасль — 0,35)
MIN_FACTOR = 0.35
# итоговая сила связи, с которой участник затронут: слабые побочные теги новости группу не задевают
MIN_IMPACT = 0.25
# факторы, которые касаются любой компании: по ним группу не перечисляем
BROAD_FACTORS = {"inflation", "region"}
# соседняя подотрасль того же класса ОКВЭД — как в цепочке
PARTIAL_DIRECT = 0.5
# крупная компания группы — для подписи «из них крупных»
MAJOR_REVENUE = 1e9
CACHE_SECONDS = 600


@dataclass
class GroupContext:
    """Участники группы с их картами — считается один раз и годится для любого числа событий."""

    company: CompanyRecord
    members: list[tuple[CompanyRecord, dict[str, FactorExposure]]]
    flows: Flows

    @property
    def size(self) -> int:
        return len(self.members) + 1


def _member_catalog(catalog: Catalog) -> Catalog:
    """Каталог без базового уровня: сигнал `always` есть у всех и группу не отличает."""
    trimmed = catalog.model_copy(deep=True)
    for factor in trimmed.factor:
        factor.signal = [s for s in factor.signal if s.kind != "always"] or factor.signal[:0]
    trimmed.factor = [f for f in trimmed.factor if f.signal and f.code not in BROAD_FACTORS]
    return trimmed


_cache: dict[tuple, tuple[float, list]] = {}


def _member_maps(members: list[CompanyRecord], catalog: Catalog) -> list[tuple[CompanyRecord, dict]]:
    # карты участников зависят только от их записей: кэшируем по набору записей на CACHE_SECONDS
    key = (id(catalog), tuple(sorted((m.id, m.okved_code, m.revenue, m.credit, m.leasing) for m in members)))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    trimmed = _member_catalog(catalog)
    mapped = []
    for member in members:
        exposure = build_exposure(member, [], [], trimmed)
        mapped.append((member, {f.code: f for f in exposure.factors if f.strength}))
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = (time.monotonic(), mapped)
    return mapped


def group_context(
    company: CompanyRecord, group: list[CompanyRecord], flows: list[Flow], catalog: Catalog | None = None
) -> GroupContext | None:
    """Нет группы (или в ней только сама компания) — None: блока «Ваша группа» нет."""
    members = [m for m in group if m.id != company.id]
    if not company.group_id or not members:
        return None
    mapped = _member_maps(members, catalog or default_catalog())
    return GroupContext(company=company, members=mapped, flows=aggregate_flows(company, flows))


def _companies_genitive(n: int) -> str:
    """«касается 1 компании», «касается 3 компаний»."""
    return f"{n} компании" if n % 10 == 1 and n % 100 != 11 else f"{n} компаний"


def _industry_match(member_code: str | None, codes: dict[str, list[tuple[str, float]]]) -> float:
    """Совпадение отрасли участника с событием: свой код — полная сила, сосед по классу — половина."""
    prefix = okved_prefix(member_code)
    if not prefix or prefix not in codes:
        return 0.0
    code = member_code or ""
    best = 0.0
    for event_code, strength in codes[prefix]:
        exact = event_code == prefix or code.startswith(event_code) or event_code.startswith(code)
        best = max(best, strength * (1.0 if exact else PARTIAL_DIRECT))
    return best


def group_impact(
    ctx: GroupContext,
    factors: list[tuple[str, float]],
    okved: list[tuple[str, float]],
    aliases: dict[str, str] | None = None,
    min_impact: float = MIN_IMPACT,
) -> GroupImpact:
    """Каких участников группы касается событие с факторами `factors` и отраслями `okved` (код, сила 0–1)."""
    codes: dict[str, list[tuple[str, float]]] = {}
    for code, strength in okved:
        prefix = okved_prefix(code)
        if prefix and strength > 0:
            codes.setdefault(prefix, []).append((code.strip(), min(strength, 1.0)))
    event_factors: dict[str, float] = {}
    for code, strength in factors:
        code = (aliases or {}).get(code, code)
        if strength > 0 and code not in BROAD_FACTORS:
            event_factors[code] = max(event_factors.get(code, 0.0), min(strength, 1.0))

    affected: list[AffectedMember] = []
    total_revenue = 0.0
    for member, exposure in ctx.members:
        total_revenue += member.revenue or 0
        direct = _industry_match(member.okved_code, codes)
        direct = direct if direct >= min_impact else 0.0
        hits = sorted(
            (
                (strength * exposure[code].strength, exposure[code])
                for code, strength in event_factors.items()
                if code in exposure
                and exposure[code].strength >= MIN_FACTOR
                and strength * exposure[code].strength >= min_impact
            ),
            key=lambda h: -h[0],
        )
        if not direct and not hits:
            continue
        strength = max([direct, *(h[0] for h in hits)])
        if direct >= (hits[0][0] if hits else 0.0):
            activity = f"{member.okved_code} {member.okved_name or ''}".strip()
            channel = f"событие в её отрасли: {activity}"
        else:
            top = hits[0][1]
            channel = f"{top.label}: {top.channel.text}" if top.channel else top.label
        pair = ctx.flows.pairs.get(member.id)
        paid = pair.in_amount + pair.out_amount if pair else None
        affected.append(
            AffectedMember(
                id=member.id,
                display_name=display_name(member, member.id),
                okved=member.okved_code,
                sector=sector_for(member.okved_code),
                region=member.region,
                revenue=member.revenue,
                revenue_bn=round(member.revenue / 1e9, 3) if member.revenue else None,
                channel=channel,
                factors=[FeedFactor(code=f.code, label=f.label) for _, f in hits],
                direct=bool(direct),
                strength=round(strength, 4),
                intra_payments=round(paid, 2) if paid else None,
            )
        )

    # показываем крупнейших затронутых: для собственника важнее выручка, чем сила связи мелкой компании
    affected.sort(key=lambda m: (-(m.revenue or 0), -m.strength, m.id))
    revenue = sum(m.revenue or 0 for m in affected)
    major = [m for m in affected if (m.revenue or 0) >= MAJOR_REVENUE]
    intra = sum(m.intra_payments or 0 for m in affected)
    turnover = ctx.flows.turnover
    share = revenue / total_revenue if total_revenue else 0.0
    if affected:
        n = len(affected)
        text = f"событие касается {_companies_genitive(n)} группы из {ctx.size - 1}"
        if major:
            text += f", из них {len(major)} с выручкой от 1 млрд ₽"
        text += f"; их выручка — {format_rub(revenue)}, {format_share(share)} выручки группы без вас"
        # отрасли затронутых — по убыванию их выручки
        by_sector: dict[str, float] = {}
        for m in affected:
            sector = SECTOR_BY_CODE.get(okved_prefix(m.okved) or "")
            if sector:
                by_sector[sector] = by_sector.get(sector, 0.0) + (m.revenue or 0)
        sectors = sorted(by_sector, key=lambda s: -by_sector[s])
        if sectors:
            text += f"; отрасли: {', '.join(sectors[:4])}"
        if intra:
            text += f"; ваши платежи с ними — {format_rub(intra)}"
    else:
        text = "событие не касается других компаний группы"
    return GroupImpact(
        group_id=ctx.company.group_id,
        companies_total=ctx.size,
        affected_count=len(affected),
        major_count=len(major),
        affected_revenue=round(revenue, 2),
        affected_revenue_bn=round(revenue / 1e9, 3),
        affected_share=round(share, 4),
        affected=affected[:MEMBERS_SHOWN],
        intra_payments=round(intra, 2),
        intra_share=round(intra / turnover, 4) if turnover else 0.0,
        text=text,
        refs=["feat:GROUP_ID", "feat:group_revenue"] + (["feat:intra_group_share"] if intra else []),
    )
