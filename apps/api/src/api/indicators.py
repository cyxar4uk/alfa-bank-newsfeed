"""Показатели компании из её платежей — для карты рисков, расчётов и фактов агента.

Каждый показатель — число, фраза с ним, формула (её же — в README, «Как считается») и пометка «оценка»,
если число опирается на допущение, а не только на платежи. Основа — платежи, сведённые по контрагентам
(`api.profile.aggregate_flows`: без самоплатежей и выбросов); «внешние» — без компаний своей группы.
Показатель не считается, если для него нет данных: тогда его просто нет в списке.
"""

from collections import defaultdict

from api.contract import Indicator
from api.market import market_now
from api.okved import SECTOR_BY_CODE, okved_prefix
from api.profile import Flows, aggregate_flows, format_rub, format_share
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


def _fx(agg: Flows) -> Indicator | None:
    """Чувствительность к курсу: оборот с участниками ВЭД, пересчитанный на 1 ₽ курса доллара (оценка)."""
    fx_turnover = sum(
        p.out_amount + p.in_amount for p in agg.external() if p.counterparty and p.counterparty.fts_flag
    )
    now = market_now("fx:USD")
    if not fx_turnover or now is None or not now.value:
        return None
    per_rub = fx_turnover / now.value
    return Indicator(
        code="fx_sensitivity",
        label="Чувствительность к курсу",
        value=round(per_rub, 2),
        text=(
            f"Оборот с участниками ВЭД — {format_rub(fx_turnover)}; если он в долларах, каждый 1 ₽ курса"
            f" меняет его рублёвую сумму примерно на {format_rub(per_rub)} (оценка)"
        ),
        formula=(
            "внешний оборот с контрагентами-участниками ВЭД / курс доллара ЦБ на последнюю дату; допущение —"
            " расчёты с ними в долларах (валюты платежей в данных нет), поэтому это оценка, а не факт"
        ),
        is_estimate=True,
    )


def company_indicators(company: CompanyRecord, flows: list[Flow]) -> list[Indicator]:
    """Все показатели, для которых в платежах есть данные; порядок — как на карте рисков."""
    if not flows:
        return []
    agg = aggregate_flows(company, flows)
    found = [
        _concentration(agg, out=False),
        _concentration(agg, out=True),
        _side_sectors(agg, out=True),
        _side_sectors(agg, out=False),
        _intra(agg),
        _gov(agg),
        _fx(agg),
    ]
    return [i for i in found if i is not None]
