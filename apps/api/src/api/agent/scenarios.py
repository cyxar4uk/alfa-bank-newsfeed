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

from api.agent.inputs import fx_flow, interest_change
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
    """Числа пользователя: долг ₽, валютные расчёты за год ₽, закупки за год ₽, топливо т/мес, тип ставки.

    Нет числа — расчёт на единицу. «Мои числа» сохраняет пользователь (`api.inputs`), их же можно передать в
    пересчёт явно.
    """

    debt: float | None = None
    fx: float | None = None
    purchases: float | None = None
    fuel_t: float | None = None  # закупка топлива в месяц, т
    rate_type: str | None = None  # floating | fixed

    receipts_month: float | None = None
    purchases_month: float | None = None
    fx_currency: str | None = None
    fx_base_rate: float | None = None
    fx_scenario_rate: float | None = None
    current_rate_pct: float | None = None
    scenario_rate_pct: float | None = None

    @classmethod
    def from_user(cls, saved) -> "Inputs":
        """Из сохранённых «моих чисел» (`api.contract.UserInputs`): закупки в месяц → в год."""
        if saved is None:
            return cls()
        monthly = getattr(saved, "fx_purchases_month_rub", None)
        return cls(
            debt=getattr(saved, "debt_rub", None),
            fx=monthly * 12 if monthly is not None else None,
            receipts_month=getattr(saved, "fx_revenue_month_rub", None),
            purchases_month=monthly,
            fx_currency=getattr(saved, "fx_currency", None),
            fx_base_rate=getattr(saved, "fx_base_rate", None),
            fx_scenario_rate=getattr(saved, "fx_scenario_rate", None),
            current_rate_pct=getattr(saved, "current_rate_pct", None),
            scenario_rate_pct=getattr(saved, "scenario_rate_pct", None),
            fuel_t=getattr(saved, "fuel_purchase_month_t", None),
            rate_type=getattr(saved, "rate_type", None),
        )

    def any(self) -> bool:
        return any(
            v is not None
            for v in (
                self.debt,
                self.fx,
                self.purchases,
                self.fuel_t,
                self.receipts_month,
                self.purchases_month,
                self.fx_currency,
                self.fx_base_rate,
                self.fx_scenario_rate,
                self.current_rate_pct,
                self.scenario_rate_pct,
                self.rate_type,
            )
        )


def saved_inputs(persona_id: str):
    """«Мои числа» пользователя (`api.inputs.user_inputs`); модуля нет или числа не вводили — None."""
    import importlib

    try:
        fn = getattr(importlib.import_module("api.inputs"), "user_inputs", None)
    except ImportError:
        return None
    if fn is None:
        return None
    try:
        return fn(persona_id)
    except Exception:
        return None


def inputs_stamp(persona_id: str) -> str | None:
    """Когда сохранены «мои числа» — часть версии карточки: после сохранения рубли пересчитаются."""
    saved = saved_inputs(persona_id)
    stamp = getattr(saved, "updated_at", None)
    return stamp.isoformat() if stamp else None


def _base(amount: float | None, unit: float) -> tuple[float, str]:
    if amount and amount > 0:
        return amount, f"на ваши {fmt_rub(amount)}"
    return unit, f"на каждый {fmt_rub(unit)}" if unit >= 1e9 else f"на каждые {fmt_rub(unit)}"


def rate(debt: float | None = None, refs: list[str] | None = None, rate_type: str | None = None) -> Statement:
    base, label = _base(debt, DEBT_UNIT)
    now, later = base * RATE_NOW / 100, base * RATE_2027 / 100
    if rate_type == "fixed":
        return Statement(
            text=(
                f"Ставка по долгу фиксированная: проценты {label} не изменятся "
                "до пересмотра условий договора."
            ),
            origin="estimate",
            refs=refs or [],
            confidence="medium",
        )
    cheaper = fmt_number((RATE_NOW - RATE_2027) / RATE_NOW * 100, 0)
    return Statement(
        text=(
            f"Проценты {label} долга, если ставка по кредиту идёт за ключевой:"
            f" при {fmt_number(RATE_NOW)} % — {fmt_rub(now)} в год,"
            f" при {fmt_number(RATE_2027)} % (прогноз Альфа-Банка на конец 2027 г.) — {fmt_rub(later)};"
            f" разница {fmt_rub(now - later)} в год — примерно на {cheaper} % меньше текущих выплат."
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


def oil(
    purchases: float | None = None,
    reseller: bool = True,
    refs: list[str] | None = None,
    fuel_t: float | None = None,
) -> Statement:
    base, label = _base(purchases, PURCHASE_UNIT)
    first = OIL_PRICES[0]
    if fuel_t and not purchases:
        # тонны без цены — рост в процентах: цену тонны в данных банка не знаем
        steps = ", ".join(
            f"при ${fmt_number(p, 0)} — на {fmt_number((p / first - 1) * 100)} %" for p in OIL_PRICES[1:]
        )
        tail = " На столько же сожмётся ваша маржа, если цены продажи не успеют." if reseller else ""
        return Statement(
            text=(
                "Допущение сервиса — цена закупки топлива идёт за нефтью. Тогда ваши"
                f" {fmt_number(fuel_t, 0)} т топлива в месяц от условного уровня ${fmt_number(first, 0)}"
                f" за баррель подорожают {steps}.{tail}"
            ),
            origin="estimate",
            refs=refs or [],
            confidence="low",
        )
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


# расчёты карточки, которые заменяются на числах пользователя (старые тексты «на каждый 1 млрд» — тоже)
SCENARIO_PREFIXES = (
    "Валютная часть за месяц:",
    "Процентная часть за месяц:",
    "Итого за сопоставимый месяц:",
    "Общий итог не рассчитан:",
    "При валюте ",
    "По фиксированной ставке проценты не меняются",
    "Если плавающая ставка изменится",
    "Проценты на",
    "Ставка по долгу фиксированная",
    "Если курс дойдёт",
    "Допущение сервиса",
    "На каждый 1 млрд",
    "На каждые 100 млн ₽ валютных",
)
ASK_RATES = (12.0, 14.0, 16.0)  # ставки, на которых заранее считаем проценты по долгу пользователя в чате


def joint_scenario(inputs: Inputs) -> Statement | None:
    """Месячные FX и процентные компоненты; общий итог — только когда известны обе стороны."""
    fx_known = (
        inputs.receipts_month is not None
        and inputs.purchases_month is not None
        and inputs.fx_currency
        and inputs.fx_base_rate
        and inputs.fx_scenario_rate
    )
    fx_delta_month = None
    parts: list[str] = []
    if fx_known:
        flow = fx_flow(
            inputs.receipts_month,
            inputs.purchases_month,
            inputs.fx_base_rate,
            inputs.fx_scenario_rate,
        )
        fx_delta_month = flow.change_month_rub
        direction = "плюс" if fx_delta_month > 0 else "минус" if fx_delta_month < 0 else "без изменения"
        parts.append(
            f"Валютная часть за месяц: {direction} {fmt_rub(abs(fx_delta_month))}, "
            f"поступления минус закупки при {inputs.fx_currency}, курс {fmt_number(inputs.fx_base_rate)} → "
            f"{fmt_number(inputs.fx_scenario_rate)} ₽."
        )

    interest_known = inputs.debt is not None and (
        inputs.debt == 0
        or inputs.rate_type == "fixed"
        or (
            inputs.rate_type == "floating"
            and inputs.current_rate_pct is not None
            and inputs.scenario_rate_pct is not None
        )
    )
    interest_delta_month = None
    if interest_known and (inputs.debt == 0 or inputs.rate_type == "fixed"):
        interest_delta_month = 0.0
        label = (
            "явно указано отсутствие долга"
            if inputs.debt == 0
            else "фиксированная ставка до пересмотра договора"
        )
        parts.append(f"Процентная часть за месяц: без изменения (0 ₽; {label}).")
    elif interest_known:
        change = interest_change(inputs.debt, inputs.current_rate_pct, inputs.scenario_rate_pct)
        interest_delta_month = -change / 12
        direction = (
            "плюс" if interest_delta_month > 0 else "минус" if interest_delta_month < 0 else "без изменения"
        )
        parts.append(
            f"Процентная часть за месяц: {direction} {fmt_rub(abs(interest_delta_month))}; "
            "при долге "
            f"{fmt_rub(inputs.debt)} и плавающей ставке {fmt_number(inputs.current_rate_pct)}% → "
            f"{fmt_number(inputs.scenario_rate_pct)}% годовых."
        )

    if fx_delta_month is not None and interest_delta_month is not None:
        total = fx_delta_month + interest_delta_month
        direction = "плюс" if total > 0 else "минус" if total < 0 else "без изменения"
        parts.append(
            f"Итого за сопоставимый месяц: {direction} {fmt_rub(abs(total))}. "
            "Допущения: объёмы валютных поступлений и закупок постоянны; текущая и сценарная ставки "
            "действуют полный период; проценты выплачиваются равномерно по месяцам. "
            "Это условное изменение денежного потока, не прибыль и не прогноз."
        )
    elif parts:
        parts.append("Общий итог не рассчитан: для второй компоненты не хватает данных.")
    return Statement(text=" ".join(parts), origin="estimate", refs=[], confidence="medium") if parts else None


def user_lines(saved, ctx=None) -> list[str]:
    """Что пользователь сообщил о себе («мои числа») — модели в контекст; рубли по ставкам уже посчитаны."""
    inputs = Inputs.from_user(saved)
    if saved is None:
        from api.agent.clarifications import clarification_questions

        return [f"Уточнение для сценария: {q}" for q in clarification_questions(ctx, saved)]
    if not (inputs.any() or inputs.rate_type):
        return []
    kind = {"floating": "плавающая (идёт за ключевой)", "fixed": "фиксированная"}.get(
        inputs.rate_type or "", ""
    )
    lines = []
    if inputs.debt is not None and inputs.rate_type == "fixed":
        lines.append(
            f"Ваш долг по вашим данным — {fmt_rub(inputs.debt)}; ставка фиксированная, "
            "проценты не меняются до пересмотра условий договора."
        )
    elif inputs.debt:
        table = "; ".join(
            f"при {fmt_number(r)} % — {fmt_rub(inputs.debt * r / 100)} в год" for r in ASK_RATES
        )
        lines.append(
            f"Ваш долг по вашим данным — {fmt_rub(inputs.debt)}"
            + (f", ставка {kind}" if kind else "")
            + f". Проценты на него: {table}. Называй это «по вашим данным {fmt_rub(inputs.debt)}»."
        )
    elif kind:
        lines.append(f"Тип ставки по вашим данным: {kind}.")
    if inputs.fx:
        lines.append(f"Валютные закупки по вашим данным — {fmt_rub(inputs.fx)} в год.")
    if inputs.fuel_t:
        lines.append(f"Закупка топлива по вашим данным — {fmt_number(inputs.fuel_t, 0)} т в месяц.")
    combined = joint_scenario(inputs)
    if combined:
        lines.append(combined.text)
    from api.agent.clarifications import clarification_questions

    lines.extend(f"Уточнение для сценария: {q}" for q in clarification_questions(ctx, saved))
    return lines


def reprice(insight, ctx):
    """Копия карточки с рублями на «моих числах» (без модели): сценарии вместо старых текстов."""
    fresh = for_context(ctx)
    out = insight.model_copy(deep=True)
    c = out.consequences
    for place in ("risks", "opportunities", "factors"):
        items = getattr(c, place)
        setattr(
            c,
            place,
            [s for s in items if not (s.origin == "estimate" and s.text.startswith(SCENARIO_PREFIXES))],
        )
    for _, statement, place, _ in fresh:
        getattr(c, place).append(statement)
    return out


_TRADE = re.compile(r"торговл", re.IGNORECASE)
_FUEL = re.compile(r"топлив|нефт|бензин|горюч", re.IGNORECASE)


def for_context(ctx, inputs: Inputs | None = None) -> list[tuple[str, Statement, str, str]]:
    """Сценарии для события и компании: (id, утверждение, блок карточки, фактор).

    Ставка — у кого кредит или лизинг и событие про ставку; курс — у кого ВЭД и есть прогноз банка по курсу
    в найденных материалах; нефть — у кого заметная зависимость от цен на нефть и топливо.
    """
    from api.agent.ports import LEVEL_RANK
    from api.agent.topics import event_topics, ved_direction

    inputs = inputs if inputs is not None and inputs.any() else Inputs.from_user(ctx.user_inputs)
    topics = event_topics(ctx.event)
    features = {f.id: f.value for f in ctx.profile.features}
    exposure = {f.code: f for f in ctx.exposure}
    out = []
    combined = joint_scenario(inputs)
    if combined and ("fx" in topics or "rate" in topics):
        factor = "fx" if "fx" in topics else "rate"
        out.append(("est:user_joint_scenario", combined, "factors" if factor == "fx" else "risks", factor))
    # прогноз ставки банка — только сверенный со страницей материала, иначе 12 % не из источника
    page = ctx.page_texts.get(RATE_PAGE, "").replace(" ", "")
    rate_verified = "14,0%" in page and "12,0%" in page
    if (
        rate_verified
        and "rate" in topics
        and (
            features.get("feat:CL_PRODUCT_LOA_MARK")
            or features.get("feat:CL_PRODUCT_LEA_MARK")
            or inputs.debt
        )
    ):
        # Прогноз ставки из источника показываем только при отсутствии заполненного сценария.
        refs = [
            RATE_PAGE,
            *(f for f in ("feat:CL_PRODUCT_LOA_MARK", "feat:CL_PRODUCT_LEA_MARK") if features.get(f)),
        ]
        if combined is None:
            out.append(("est:rate_scenario", rate(inputs.debt, refs, inputs.rate_type), "risks", "rate"))
    fx_hit = next((h for h in ctx.analytics if h.source.id == FX_SOURCE), None)
    now = fx_now(ctx.event.text) or fx_now(ctx.event.source.title)
    fx_verified = fx_hit is not None and "87" in (fx_hit.source.fragment or "")
    if (
        "fx" in topics
        and (features.get("feat:FTS_FLAG") or inputs.fx)
        and fx_verified
        and now
        and combined is None
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
    if "oil" in topics and (oil_level >= 2 or inputs.purchases or inputs.fuel_t):
        # маржа — у того, кто перепродаёт само топливо, а не у любой торговли
        reseller = bool(_TRADE.search(ctx.profile.display_name) and _FUEL.search(ctx.profile.display_name))
        out.append(
            (
                "est:oil_scenario",
                oil(inputs.purchases, reseller, fuel_t=inputs.fuel_t),
                "risks",
                "commodity_oil",
            )
        )
    return out
