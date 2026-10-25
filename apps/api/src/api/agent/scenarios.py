"""Сценарии в рублях на условных числах — и на числах пользователя, если он их ввёл.

Сумм долга, валютных расчётов и закупок в данных банка нет, поэтому расчёт — «на единицу» (1 млрд ₽ долга,
100 млн ₽ валютных расчётов или закупок), а пользователь подставляет свои числа:
`POST /api/insights/{id}/scenarios`. Формулы простые и видны в тексте; модель их не пишет.

- ставка: проценты в год при 14 % и при прогнозе банка 12 % на конец 2027 г.;
- курс: от текущего курса (из новости) к прогнозу банка 87 руб./$ — для экспортёра рублёвая выручка, для
  импортёра закупки;
- нефть: $72 (прогноз ЦБ по Urals) → $85 → $100 — на сколько дорожает закупка, если её цена следует за нефтью;
  у перепродавца, который не успевает переложить рост в цены продажи, на столько же сжимается маржа.
"""

import re
from dataclasses import dataclass

from api.contract import Statement
from api.numbers import fmt_number, fmt_rub

RATE_NOW, RATE_2027 = 14.0, 12.0  # прогноз банка: 14,0 % до конца 2026 г., 12,0 % на конец 2027 г.
RATE_PAGE = "src:alfa:keyrate-2026-09#p1"
FX_FORECAST = 87.0  # прогноз банка по курсу на конец 2026 г., руб./$
FX_SOURCE = "src:alfa:macro-1h26#p1-9"
OIL_PRICES = (72.0, 85.0, 100.0)  # $ за баррель: прогноз ЦБ по Urals и два сценария роста

DEBT_UNIT, FX_UNIT, PURCHASE_UNIT = 1e9, 1e8, 1e8

_FX_IN_TEXT = re.compile(
    r"(?<![\d.,])(?<!\d\s)(\d{2,3})(?:[,.](\d{1,2}))?\s*(?:руб\w*|₽)(?!\s*(?:/|за)\s*л)", re.IGNORECASE
)
_DOLLAR = re.compile(r"доллар|\$|USD", re.IGNORECASE)
_NOT_DOLLAR = re.compile(r"евро|юан|литр|/л\b", re.IGNORECASE)
MIN_FX_CHANGE = 0.005  # меньше полупроцента — сценарий ни о чём


@dataclass
class Inputs:
    """Числа пользователя, ₽: долг, валютные расчёты за год, закупки за год. Нет — расчёт на единицу."""

    debt: float | None = None
    fx: float | None = None
    purchases: float | None = None


def _base(amount: float | None, unit: float) -> tuple[float, str]:
    if amount and amount > 0:
        return amount, f"на ваши {fmt_rub(amount)}"
    return unit, f"на каждый {fmt_rub(unit)}" if unit >= 1e9 else f"на каждые {fmt_rub(unit)}"


def rate(debt: float | None = None, refs: list[str] | None = None) -> Statement:
    base, label = _base(debt, DEBT_UNIT)
    now, later = base * RATE_NOW / 100, base * RATE_2027 / 100
    return Statement(
        text=(
            f"Проценты {label} долга, если ставка по кредиту идёт за ключевой:"
            f" при {fmt_number(RATE_NOW)} % — {fmt_rub(now)} в год,"
            f" при {fmt_number(RATE_2027)} % (прогноз Альфа-Банка на конец 2027 г.) — {fmt_rub(later)};"
            f" разница {fmt_rub(now - later)} в год."
        ),
        origin="estimate",
        refs=refs or [],
        confidence="medium",
    )


def fx_now(text: str) -> float | None:
    """Текущий курс доллара из новости: «доллар ниже 81 рубля». Рядом — доллар, не евро и не литр."""
    text = text or ""
    for m in _FX_IN_TEXT.finditer(text):
        window = text[max(0, m.start() - 40) : m.end() + 15]
        if not _DOLLAR.search(window) or _NOT_DOLLAR.search(window):
            continue
        value = float(f"{m[1]}.{m[2] or 0}")
        if 60 <= value <= 130:
            return value
    return None


def fx(
    now: float, direction: str | None, amount: float | None = None, refs: list[str] | None = None
) -> Statement:
    base, label = _base(amount, FX_UNIT)
    change = FX_FORECAST / now - 1
    percent = ("+" if change > 0 else "−") + fmt_number(abs(change) * 100)
    what = {
        "export": "рублёвая выручка от экспорта",
        "import": "рублёвая стоимость закупок за валюту",
    }.get(direction or "", "рублёвая сумма валютных расчётов")
    sign = "вырастет" if change > 0 else "снизится"
    return Statement(
        text=(
            f"Если курс дойдёт от {fmt_number(now)} до {fmt_number(FX_FORECAST)} руб./$"
            f" (прогноз Альфа-Банка на конец 2026 г.), это {percent} %: {label} валютных расчётов"
            f" {what} {sign} на {fmt_rub(abs(base * change))}."
        ),
        origin="estimate",
        refs=[FX_SOURCE, *(refs or [])],
        confidence="medium",
    )


def oil(purchases: float | None = None, reseller: bool = True, refs: list[str] | None = None) -> Statement:
    base, label = _base(purchases, PURCHASE_UNIT)
    first = OIL_PRICES[0]
    steps = ", ".join(
        f"при ${fmt_number(p, 0)} — на {fmt_rub(base * (p / first - 1))}" for p in OIL_PRICES[1:]
    )
    tail = (
        " Если цены продажи не успеют за закупкой, на столько же сожмётся ваша маржа."
        if reseller
        else " Это рост ваших затрат на топливо."
    )
    return Statement(
        text=(
            f"Допущение сервиса — цена закупки топлива идёт за нефтью. Тогда {label} закупок в год"
            f" от условного уровня ${fmt_number(first, 0)} за баррель она вырастет {steps}.{tail}"
        ),
        origin="estimate",
        refs=refs or [],
        confidence="low",
    )


_TRADE = re.compile(r"торговл", re.IGNORECASE)
_FUEL = re.compile(r"топлив|нефт|бензин|горюч", re.IGNORECASE)


def for_context(ctx, inputs: Inputs | None = None) -> list[tuple[str, Statement, str, str]]:
    """Сценарии для события и компании: (id, утверждение, блок карточки, фактор).

    Ставка — у кого кредит или лизинг и событие про ставку; курс — у кого ВЭД и есть прогноз банка по курсу
    в найденных материалах; нефть — у кого заметная зависимость от цен на нефть и топливо.
    """
    from api.agent.ports import LEVEL_RANK
    from api.agent.topics import event_topics, ved_direction

    inputs = inputs or Inputs()
    topics = event_topics(ctx.event)
    features = {f.id: f.value for f in ctx.profile.features}
    exposure = {f.code: f for f in ctx.exposure}
    out = []
    # прогноз ставки банка — только сверенный со страницей материала, иначе 12 % не из источника
    page = ctx.page_texts.get(RATE_PAGE, "").replace(" ", "")
    rate_verified = "14,0%" in page and "12,0%" in page
    if (
        rate_verified
        and topics & {"rate", "deposit"}
        and (
            features.get("feat:CL_PRODUCT_LOA_MARK")
            or features.get("feat:CL_PRODUCT_LEA_MARK")
            or inputs.debt
        )
    ):
        # прогноз сверен со страницей — на неё и на признаки кредита и лизинга ссылается расчёт
        refs = [
            RATE_PAGE,
            *(f for f in ("feat:CL_PRODUCT_LOA_MARK", "feat:CL_PRODUCT_LEA_MARK") if features.get(f)),
        ]
        out.append(("est:rate_scenario", rate(inputs.debt, refs), "risks", "rate"))
    fx_hit = next((h for h in ctx.analytics if h.source.id == FX_SOURCE), None)
    now = fx_now(ctx.event.text) or fx_now(ctx.event.source.title)
    fx_verified = fx_hit is not None and "87" in (fx_hit.source.fragment or "")
    if (
        "fx" in topics
        and (features.get("feat:FTS_FLAG") or inputs.fx)
        and fx_verified
        and now
        and abs(FX_FORECAST / now - 1) >= MIN_FX_CHANGE
    ):
        flags = [f for f in ("feat:FTS_FLAG",) if features.get(f)]
        out.append(
            ("est:fx_scenario", fx(now, ved_direction(ctx.exposure), inputs.fx, flags), "factors", "fx")
        )
    oil_level = max(
        (
            LEVEL_RANK.get(exposure[c].level, 0)
            for c in ("commodity_oil", "commodity_oil_gas")
            if c in exposure
        ),
        default=0,
    )
    if "oil" in topics and (oil_level >= 2 or inputs.purchases):
        # маржа — у того, кто перепродаёт само топливо, а не у любой торговли
        reseller = bool(_TRADE.search(ctx.profile.display_name) and _FUEL.search(ctx.profile.display_name))
        out.append(
            (
                "est:oil_scenario",
                oil(inputs.purchases, reseller),
                "risks",
                "commodity_oil",
            )
        )
    return out
