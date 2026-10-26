"""Показатели компании из её платежей — для карты рисков, расчётов и фактов агента.

Каждый показатель — число, фраза с ним, формула (её же — в README, «Как считается») и пометка «оценка»,
если число опирается на допущение, а не только на платежи. Основа — платежи, сведённые по контрагентам
(`api.profile.aggregate_flows`: без самоплатежей и выбросов); «внешние» — без компаний своей группы.
Показатель не считается, если для него нет данных: тогда его просто нет в списке.
"""

from collections import defaultdict

from api.contract import Indicator
from api.okved import SECTOR_BY_CODE, okved_prefix
from api.profile import Flows, aggregate_flows, countries, format_rub, format_share
from api.records import CompanyRecord, Flow

GOV_OKVED = "84"  # государственное управление и обеспечение военной безопасности; социальное обеспечение
CONCENTRATION_HIGH = 0.3  # доля одного контрагента, начиная с которой это заметная зависимость
SECTORS_SHOWN = 3


def _sectors(pairs: list[tuple[float, CompanyRecord | None]]) -> list[tuple[str, float]]:
    total = sum(a for a, _ in pairs)
    by: dict[str, float] = defaultdict(float)
    for amount, cp in pairs:
        prefix = okved_prefix(cp.okved_code) if cp else None
        if prefix:
            by[SECTOR_BY_CODE.get(prefix) or f"ОКВЭД {prefix}"] += amount
    return sorted(((s, a / total) for s, a in by.items()), key=lambda x: -x[1]) if total else []


def _side_sectors(agg: Flows, out: bool) -> Indicator | None:
    pairs = [(p.out_amount if out else p.in_amount, p.counterparty) for p in agg.external()]
    pairs = [(a, cp) for a, cp in pairs if a]
    top = _sectors(pairs)[:SECTORS_SHOWN]
    if not top:
        return None
    who = "поставщикам" if out else "от покупателей"
    listed = ", ".join(f"{s} — {format_share(v)}" for s, v in top)
    return Indicator(
        code="supplier_sectors" if out else "customer_sectors",
        label="Платежи поставщикам по отраслям" if out else "Поступления от покупателей по отраслям",
        value=round(top[0][1], 4),
        text=f"Внешние платежи {who}: {listed}",
        formula=(
            "сумма внешних платежей по контрагентам одной отрасли (класс ОКВЭД) / все внешние платежи этой"
            " стороны; контрагенты вне данных банка — в знаменателе, но без отрасли"
        ),
    )


def _concentration(agg: Flows, out: bool) -> Indicator | None:
    amounts = [p.out_amount if out else p.in_amount for p in agg.external()]
    total = sum(amounts)
    if not total:
        return None
    share = max(amounts) / total
    who = "поставщик" if out else "покупатель"
    of = "внешних платежей поставщикам" if out else "внешних поступлений"
    note = " — заметная зависимость от одного контрагента" if share >= CONCENTRATION_HIGH else ""
    return Indicator(
        code="top_supplier_share" if out else "top_customer_share",
        label="Крупнейший поставщик" if out else "Крупнейший покупатель",
        value=round(share, 4),
        text=f"Ваш крупнейший {who} — {format_share(share)} {of}{note}",
        formula=f"платежи с крупнейшим внешним контрагентом-{who}ом / все {of}",
    )


def _intra(agg: Flows) -> Indicator | None:
    turnover = agg.turnover
    intra = sum(p.out_amount + p.in_amount for p in agg.pairs.values() if agg.in_group(p.counterparty))
    if not turnover or not intra:
        return None
    share = intra / turnover
    return Indicator(
        code="intra_group_share",
        label="Оборот с компаниями группы",
        value=round(share, 4),
        text=f"С компаниями своей группы — {format_share(share)} платёжного оборота ({format_rub(intra)})",
        formula="платежи в обе стороны с компаниями той же группы / весь платёжный оборот",
    )


def _gov(agg: Flows) -> Indicator | None:
    pairs = [(p.in_amount, p.counterparty) for p in agg.external() if p.in_amount]
    total = sum(a for a, _ in pairs)
    gov = sum(a for a, cp in pairs if cp and okved_prefix(cp.okved_code) == GOV_OKVED)
    if not total or not gov:
        return None
    share = gov / total
    return Indicator(
        code="gov_customers_share",
        label="Госзаказчики",
        value=round(share, 4),
        text=f"От госзаказчиков — {format_share(share)} внешних поступлений ({format_rub(gov)})",
        formula=(
            "поступления от контрагентов с ОКВЭД 84 (госуправление) / все внешние поступления; заказчики-"
            "госкомпании с другим ОКВЭД сюда не попадают — показатель скорее занижен"
        ),
    )


def _side_concentrations(agg: Flows, out: bool) -> list[Indicator]:
    pairs = [p for p in agg.external() if (p.out_amount if out else p.in_amount) > 0]
    amounts = sorted((p.out_amount if out else p.in_amount for p in pairs), reverse=True)
    total = sum(amounts)
    if not total:
        return []
    side = "платежей поставщикам" if out else "поступлений от покупателей"
    prefix = "supplier" if out else "customer"
    result = []
    for n in (3, 5):
        share = sum(amounts[:n]) / total
        label = f"Доля крупнейших {n} {'поставщиков' if out else 'покупателей'}"
        result.append(
            Indicator(
                code=f"top{n}_{prefix}_share",
                label=label,
                value=round(share, 4),
                text=(f"На {n} крупнейших контрагентов приходится {format_share(share)} внешних {side}"),
                formula=f"сумма {n} крупнейших сумм по внешним контрагентам / все внешние {side}",
            )
        )
    shares = [a / total for a in amounts]
    hhi = sum(share * share for share in shares)
    hhi_text = f"{hhi:.4f}".replace(".", ",")
    result.append(
        Indicator(
            code=f"hhi_{prefix}",
            label=f"Индекс концентрации {'поставщиков' if out else 'покупателей'}",
            value=round(hhi, 4),
            text=f"Индекс Херфиндаля — Хиршмана для внешних {side}: {hhi_text}",
            formula=(
                f"сумма квадратов долей каждого внешнего контрагента в сумме внешних {side};"
                " диапазон 0–1"
            ),
        )
    )
    return result


def _unknown_coverage(agg: Flows, out: bool) -> list[Indicator]:
    pairs = [p for p in agg.external() if (p.out_amount if out else p.in_amount) > 0]
    total = sum(p.out_amount if out else p.in_amount for p in pairs)
    if not total:
        return []
    side = "платежей поставщикам" if out else "поступлений от покупателей"
    direction = "out" if out else "in"
    unknown = {
        "industry": sum(
            (p.out_amount if out else p.in_amount)
            for p in pairs
            if not p.counterparty or not okved_prefix(p.counterparty.okved_code)
        ),
        "counterparty": sum((p.out_amount if out else p.in_amount) for p in pairs if not p.counterparty),
        "region": sum(
            (p.out_amount if out else p.in_amount)
            for p in pairs
            if not p.counterparty or not (p.counterparty.region or p.counterparty.city)
        ),
    }
    labels = {"industry": "отрасль", "counterparty": "контрагент", "region": "регион"}
    return [
        Indicator(
            code=f"unknown_{key}_{direction}_share",
            label=f"Неизвестна: {labels[key]}",
            value=round(amount / total, 4),
            text=(
                f"Неизвестна {labels[key]} для {format_share(amount / total)} внешних {side} "
                f"({format_rub(amount)} из {format_rub(total)})"
            ),
            formula=(
                f"сумма внешних {side}, для которых {labels[key]} не указана / "
                f"все внешние {side} ({format_rub(total)})"
            ),
        )
        for key, amount in unknown.items()
    ]


def _region_concentration(agg: Flows, out: bool) -> Indicator | None:
    pairs = [p for p in agg.external() if (p.out_amount if out else p.in_amount) > 0]
    total = sum(p.out_amount if out else p.in_amount for p in pairs)
    if not total:
        return None
    by_region: dict[str, float] = defaultdict(float)
    for pair in pairs:
        region = (pair.counterparty.region or "").strip() if pair.counterparty else ""
        if region:
            by_region[region] += pair.out_amount if out else pair.in_amount
    if not by_region:
        return None
    region, amount = max(by_region.items(), key=lambda item: (item[1], item[0]))
    side = "внешних платежей поставщикам" if out else "внешних поступлений"
    direction = "out" if out else "in"
    share = amount / total  # unknown regions remain in the denominator
    return Indicator(
        code=f"top_region_share_{direction}",
        label=f"Крупнейший регион {'поставщиков' if out else 'покупателей'}",
        value=round(share, 4),
        text=(
            f"Регион {region} — {format_share(share)} {side} "
            f"({format_rub(amount)}); неизвестный регион включён в знаменатель"
        ),
        formula=f"внешние {side} контрагентов из крупнейшего известного региона / все внешние {side}",
    )


def _ved_country_membership(agg: Flows, out: bool) -> list[Indicator]:
    pairs = [pair for pair in agg.external() if (pair.out_amount if out else pair.in_amount) > 0]
    total = sum(pair.out_amount if out else pair.in_amount for pair in pairs)
    if not total:
        return []
    by_country: dict[str, float] = defaultdict(float)
    for pair in pairs:
        cp = pair.counterparty
        if not cp or cp.fts_flag is not True or not cp.fts_countries:
            continue
        amount = pair.out_amount if out else pair.in_amount
        for country in set(countries(cp.fts_countries)):
            by_country[country] += amount
    side = "внешних платежей поставщикам" if out else "внешних поступлений"
    direction = "out" if out else "in"
    warning = (
        "Страна ВЭД не указывает валюту или направление расчётов; одна сумма может относиться к нескольким "
        "странам, поэтому доли пересекаются и не складываются в долю оборота."
    )
    return [
        Indicator(
            code=f"ved_country_{direction}_share_{index}",
            label=f"Участники ВЭД: {country}",
            value=round(amount / total, 4),
            text=(
                f"Контрагенты-участники ВЭД с указанной страной {country} связаны с "
                f"{format_share(amount / total)} {side}. {warning}"
            ),
            formula=(
                f"внешние {side} контрагентов с флагом ВЭД и страной {country} / все внешние {side}; "
                "страны множественные, доли пересекаются"
            ),
        )
        for index, (country, amount) in enumerate(
            sorted(by_country.items(), key=lambda item: (-item[1], item[0]))[:5], start=1
        )
    ]


def company_indicators(company: CompanyRecord, flows: list[Flow]) -> list[Indicator]:
    """Все показатели, для которых в платежах есть данные; порядок — как на карте рисков."""
    if not flows:
        return []
    agg = aggregate_flows(company, flows)
    found = [
        _concentration(agg, out=False),
        _concentration(agg, out=True),
        *_side_concentrations(agg, out=False),
        *_side_concentrations(agg, out=True),
        *_unknown_coverage(agg, out=False),
        *_unknown_coverage(agg, out=True),
        _region_concentration(agg, out=False),
        _region_concentration(agg, out=True),
        *_ved_country_membership(agg, out=False),
        *_ved_country_membership(agg, out=True),
        _side_sectors(agg, out=True),
        _side_sectors(agg, out=False),
        _intra(agg),
        _gov(agg),
    ]
    return [i for i in found if i is not None]
