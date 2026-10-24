"""Цепочка влияния: через кого событие в отрасли задевает компанию.

Событие размечено двузначными классами ОКВЭД (`Source.tags.okved`). Каналы:
- прямой — класс компании среди классов события;
- через покупателей — доля внешних поступлений от контрагентов этого класса;
- через поставщиков — доля внешних платежей контрагентам этого класса;
- через группу — доля выручки группы (без самой компании) у компаний этого класса; платежи внутри группы
  показываются только здесь и в спрос и поставки не входят.

Сила канала = доля × сила связи события с отраслью (`weights`, по умолчанию 1); для ленты — максимум
и сумма каналов. Канал с долей меньше MIN_SHARE — шум, в цепочку не попадает.
Доли считаются так же, как в профиле и карте (`api.profile.payment_structure`).
"""

import math

from api.contract import ChainChannel, ChainNode, InfluenceChain
from api.exposure import Catalog, Context, default_catalog
from api.okved import SECTOR_BY_CODE, okved_prefix, sector_for
from api.profile import Pair, aggregate_flows, companies, display_name, format_rub, format_share
from api.records import CompanyRecord, Flow

NODES_SHOWN = 5
MIN_SHARE = 0.01


def event_classes(okved: list[str]) -> list[str]:
    """Двузначные классы из кодов события: «56», «56.10», «46.71» → 56, 46; мусор отбрасывается."""
    result: list[str] = []
    for code in okved:
        prefix = okved_prefix(code)
        if prefix and prefix not in result:
            result.append(prefix)
    return result


def _sector(okved: str) -> str:
    return SECTOR_BY_CODE.get(okved) or f"ОКВЭД {okved}"


def _node(
    cp_id: str, cp: CompanyRecord | None, amount: float | None, share: float | None, intra: bool
) -> ChainNode:
    return ChainNode(
        id=cp_id,
        display_name=display_name(cp, cp_id),
        in_dataset=cp is not None,
        okved=cp.okved_code if cp else None,
        sector=sector_for(cp.okved_code) if cp else None,
        region=cp.region if cp else None,
        amount=round(amount, 2) if amount is not None else None,
        share=round(share, 4) if share is not None else None,
        revenue=cp.revenue if cp else None,
        intra_group=intra,
    )


PARTIAL_DIRECT = 0.5  # событие в соседней подотрасли того же класса ОКВЭД


def _direct(company: CompanyRecord, okved: str, codes: list[str], weight: float) -> ChainChannel | None:
    """Своя отрасль.

    `codes` — исходные коды события этого класса: «46» — весь класс, «46.71» — только топливо.
    """
    if okved_prefix(company.okved_code) != okved:
        return None
    activity = f"{company.okved_code} {company.okved_name or ''}".strip()
    code = company.okved_code or ""
    exact = any(c == okved or code.startswith(c) or c.startswith(code) for c in codes)
    if not exact:
        share = PARTIAL_DIRECT
        text = (
            f"событие в соседней отрасли того же класса ОКВЭД {okved} ({', '.join(codes)}), ваша — {activity}"
        )
    else:
        share = 1.0
        text = f"событие в вашей отрасли: {activity}"
    return ChainChannel(
        kind="direct",
        okved=okved,
        sector=SECTOR_BY_CODE.get(okved),
        share=share,
        weight=weight,
        strength=round(share * weight, 4),
        text=text,
        counterparties=0,
        refs=["feat:MAINOKVED_CODE", "feat:sector"],
    )


def _side_channel(ctx: Context, name: str, okved: str, weight: float) -> ChainChannel | None:
    side = ctx.side(name)
    sector = next((s for s in side.sectors if s.okved == okved), None)
    if sector is None or sector.share < MIN_SHARE:
        return None
    attr = "in_amount" if name == "customers" else "out_amount"
    pairs: list[tuple[str, Pair]] = [
        (cp_id, p)
        for cp_id, p in ctx.flows.pairs.items()
        if getattr(p, attr)
        and not ctx.flows.in_group(p.counterparty)
        and p.counterparty is not None
        and okved_prefix(p.counterparty.okved_code) == okved
    ]
    pairs.sort(key=lambda item: (-getattr(item[1], attr), item[0]))
    nodes = [
        _node(cp_id, p.counterparty, getattr(p, attr), getattr(p, attr) / side.amount, False)
        for cp_id, p in pairs[:NODES_SHOWN]
    ]
    if name == "customers":
        kind, who, what, prefix = "buyers", "ваши покупатели", "внешних поступлений", "demand"
        ref = "feat:customer_sectors"
    else:
        kind, who, what, prefix = "suppliers", "ваши поставщики", "внешних платежей", "supply"
        ref = "feat:supplier_sectors"
    text = (
        f"событие → {_sector(okved)} ({okved}) → {who}: {companies(sector.counterparties)}, "
        f"{format_share(sector.share)} {what} ({format_rub(sector.amount)}) → вы"
    )
    notes = []
    if side.coverage < ctx.catalog.payments.low_coverage:
        notes.append(
            f"отрасль известна лишь у {format_share(side.coverage)} {what}: реальная доля может быть выше"
        )
    refs = [ref]
    if sector.share >= next((d.min_share for d in ctx.catalog.dynamic if d.prefix == prefix), 1.0):
        refs.append(f"exp:{prefix}_{okved}")
    return ChainChannel(
        kind=kind,
        okved=okved,
        sector=SECTOR_BY_CODE.get(okved),
        share=sector.share,
        weight=weight,
        strength=round(sector.share * weight, 4),
        coverage=side.coverage,
        text=text,
        counterparties=sector.counterparties,
        nodes=nodes,
        refs=refs,
        notes=notes,
    )


def _group_channel(ctx: Context, okved: str, weight: float) -> ChainChannel | None:
    """Компании группы этого класса: доля — большая из доли выручки группы и доли вашего оборота с ними."""
    matched = [m for m in ctx.group if okved_prefix(m.okved_code) == okved]
    if not matched:
        return None
    total = sum(m.revenue or 0 for m in ctx.group)
    amount = sum(m.revenue or 0 for m in matched)
    turnover = ctx.flows.turnover
    intra = sum(
        p.in_amount + p.out_amount
        for p in ctx.flows.pairs.values()
        if ctx.flows.in_group(p.counterparty) and okved_prefix(p.counterparty.okved_code) == okved
    )
    revenue_share = amount / total if total else 0.0
    intra_share = intra / turnover if turnover else 0.0
    share = max(revenue_share, intra_share)
    if share < MIN_SHARE:
        return None
    matched.sort(key=lambda m: (-(m.revenue or 0), m.id))
    nodes = []
    for m in matched[:NODES_SHOWN]:
        pair = ctx.flows.pairs.get(m.id)
        paid = (pair.in_amount + pair.out_amount) if pair else None
        nodes.append(_node(m.id, m, paid, (m.revenue / total) if (m.revenue and total) else None, True))
    text = (
        f"событие → {_sector(okved)} ({okved}) → компании вашей группы: {companies(len(matched))}, "
        f"{format_rub(amount)} — {format_share(revenue_share)} выручки группы без вас → вы"
    )
    notes = []
    if intra_share >= 0.001:
        notes.append(f"платежи с ними — {format_share(intra_share)} вашего оборота (внутригрупповые)")
    if intra_share > revenue_share:
        notes.append("сила — по доле вашего оборота с ними: она больше их доли в выручке группы")
    refs = ["feat:GROUP_ID"] + (["feat:intra_group_share"] if intra else [])
    return ChainChannel(
        kind="group",
        okved=okved,
        sector=SECTOR_BY_CODE.get(okved),
        share=round(share, 4),
        weight=weight,
        strength=round(share * weight, 4),
        text=text,
        counterparties=len(matched),
        nodes=nodes,
        refs=refs,
        notes=notes,
    )


def build_chain(
    company: CompanyRecord,
    flows: list[Flow],
    group: list[CompanyRecord] | None,
    okved: list[str],
    weights: dict[str, float] | None = None,
    catalog: Catalog | None = None,
) -> InfluenceChain:
    """Каналы, по которым событие с классами ОКВЭД `okved` задевает компанию.

    `group` — другие компании группы.
    """
    catalog = catalog or default_catalog()
    classes = event_classes(okved)
    ctx = Context(
        company, aggregate_flows(company, flows), [m for m in group or [] if m.id != company.id], catalog
    )

    # веса — по двузначным классам; ключи вида 46.71 приводятся к классу, при нескольких — берётся больший
    class_weights: dict[str, float] = {}
    for key, value in (weights or {}).items():
        prefix = okved_prefix(key)
        if prefix and isinstance(value, int | float) and math.isfinite(value):
            class_weights[prefix] = max(class_weights.get(prefix, 0.0), min(max(float(value), 0.0), 1.0))
    codes_by_class: dict[str, list[str]] = {}
    for code in okved:
        prefix = okved_prefix(code)
        if prefix:
            codes_by_class.setdefault(prefix, []).append(code.strip())

    channels: list[ChainChannel] = []
    gaps: list[str] = []
    sides_ok = {}
    reasons = {}
    for name in ("customers", "suppliers"):
        sides_ok[name], reasons[name] = ctx.side_has_data(name)
    if (
        not sides_ok["customers"]
        and not sides_ok["suppliers"]
        and reasons["customers"] == reasons["suppliers"]
    ):
        gaps.append(reasons["customers"])  # одна причина на обе стороны (нет платежей, мало платежей)
    else:
        for name, who in (("customers", "покупатели"), ("suppliers", "поставщики")):
            if not sides_ok[name] and reasons[name]:
                gaps.append(f"{who}: {reasons[name]}")
    weak = False
    for code in classes:
        w = class_weights.get(code, 1.0)
        candidates = [_direct(company, code, codes_by_class[code], w)]
        for name in ("customers", "suppliers"):
            if not sides_ok[name]:
                continue
            candidates.append(_side_channel(ctx, name, code, w))
            if candidates[-1] is None and any(x.okved == code for x in ctx.side(name).sectors):
                weak = True  # контрагенты этого класса есть, но меньше MIN_SHARE стороны
        candidates.append(_group_channel(ctx, code, w))
        # нулевая связь события с отраслью — канала нет
        channels.extend(c for c in candidates if c is not None and c.strength > 0)
    for name, what in (("customers", "поступлений"), ("suppliers", "платежей")):
        side = ctx.side(name)
        if sides_ok[name] and side.coverage < catalog.payments.low_coverage:
            gaps.append(f"отрасль известна лишь у {format_share(side.coverage)} внешних {what}")

    channels.sort(key=lambda c: (-c.strength, c.kind, c.okved))
    strengths = [c.strength for c in channels]
    reason = None
    if not classes:
        reason = "у события нет классов ОКВЭД"
    elif not channels:
        if class_weights and all(class_weights.get(c, 1.0) == 0 for c in classes):
            reason = "связь события с этими отраслями нулевая"
        elif weak:
            reason = (
                "контрагенты из отраслей события есть, но дают меньше"
                f" {format_share(MIN_SHARE)} оборота стороны"
            )
        elif not (sides_ok["customers"] and sides_ok["suppliers"]):
            reason = (
                "сама компания и её группа к отраслям события не относятся;"
                " по контрагентам данных недостаточно (см. gaps) — связь через них не проверить"
            )
        else:
            reason = "ни компания, ни её контрагенты и группа не относятся к отраслям события"
    return InfluenceChain(
        company_id=company.id,
        event_okved=classes,
        channels=channels,
        strength_max=max(strengths, default=0.0),
        strength_sum=round(min(sum(strengths), 1.0), 4),
        gaps=gaps,
        reason=reason,
    )
