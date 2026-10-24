"""Вывод по событию ленты: важно ли для компании и роли → почему (с числом из данных) → что делать.

Строится правилами по готовому элементу ленты: оценка, главная причина и строка «для вас». Если верх ленты
оценила модель (слагаемое `llm`), её оценка ограничивает уровень: «не задевает» — только «к сведению».
Текст — без технических слов: ни «фактор», ни «канал», ни «оценка».
"""

import re

from api.contract import ExposureMap, FeedItem, Takeaway
from api.group import companies_genitive
from api.profile import format_rub
from api.short import clean_channel

TEXT_MAX = 160
# оценка события насыщается: сильная прямая связь с одной причиной даёт 0,4–0,5, максимум в ленте — около 0,6;
# порог 0,5 оставлял «важными» одно-два события на компанию (проверено на стенде 25.10)
ACT = 0.42  # оценка, с которой событие важно: стоит действовать
WATCH = 0.3  # с которой — может задеть, стоит следить; ниже веб сворачивает событие
WEAK_EXPOSURE = 0.3  # слабая зависимость компании — не выше «следить»

# что делать по главной причине; роль уточняет, где это естественно
ACTIONS: dict[str, dict[str, str]] = {
    "rate": {
        "default": "проверьте, когда пересматриваются ставки по кредитам и лизингу",
        "owner": "учтите стоимость долга в планах инвестиций группы",
        "treasury": "сверьте график платежей по плавающим ставкам",
        "chief_accountant": "проверьте расчёт процентов и резервов в отчётности",
    },
    "deposit_yield": {
        "default": "решите, фиксировать ли доходность свободных денег на депозите",
        "chief_accountant": "учтите доход по депозитам в налоговом учёте",
    },
    "fx": {
        "default": "оцените валютную позицию и нужна ли защита от колебаний курса",
        "chief_accountant": "проверьте переоценку валютных статей и курсовые разницы",
    },
    "ved_logistics": {
        "default": "проверьте сроки расчётов и поставок с зарубежными партнёрами",
        "chief_accountant": "проверьте документы валютного контроля и таможенные платежи",
    },
    "consumer": {"default": "сверьте прогноз продаж и запасы с изменением спроса"},
    "labor": {
        "default": "оцените, как это скажется на фонде оплаты труда",
        "chief_accountant": "проверьте начисления по зарплате и взносам",
    },
    "gov": {"default": "проверьте сроки оплаты и планы по госконтрактам"},
    "commodity_oil": {"default": "пересчитайте затраты на топливо и цены договоров"},
    "commodity_metals": {"default": "пересчитайте закупочные цены на металл"},
    "commodity_gold": {"default": "проверьте цены сделок с драгметаллами"},
    "commodity_fertilizers": {"default": "пересчитайте затраты на удобрения"},
    "commodity_agro": {"default": "пересчитайте закупочные цены на сырьё и продукты"},
    "inflation": {"default": "проверьте, успевают ли цены за ростом издержек"},
    "region": {"default": "проверьте, затронуты ли ваши площадки в регионе"},
    "tax_regulation": {
        "default": "проверьте, что меняется в налогах и отчётности и с какого срока",
        "chief_accountant": "сверьте с учётной политикой и сроками отчётности",
    },
    "chain:buyers": {"default": "проверьте спрос и сроки оплаты у крупных покупателей"},
    "chain:suppliers": {"default": "проверьте цены и сроки поставок у ключевых поставщиков"},
    "chain:group": {"default": "обсудите с компаниями группы, как это скажется на их выручке"},
    "chain:direct": {"default": "оцените, как событие меняет условия в вашей отрасли"},
}
DEFAULT_ACTION = "оцените, касается ли это ваших договоров и планов"
NOTHING = "Действий не нужно."
GIST_MAX = 55

# оценка модели из слагаемого llm: «оценка модели: не задевает — …» (api.agent.rerank.IMPACT_LABEL)
_LLM = re.compile(r"^оценка модели: (не задевает|слабо|заметно|сильно)(?: — (.*))?$")
_OKVED_LIST = re.compile(r"\s*с ОКВЭД[\d.,\s]+")
_DIGIT = re.compile(r"\d")
# вид деятельности с кодом ОКВЭД, номер компании, перечень классов ОКВЭД («41, 42, 35»)
_CODE_VALUE = re.compile(r"^(?:\d{2}\.\d|U_|\d{2}(?:\.\d+)*(?:,\s*\d{2}(?:\.\d+)*)*$)")


def main_reason(item: FeedItem) -> tuple[str, float | None]:
    """Ключ действия по главной причине и зависимость компании; фактор, выбранный моделью, — главнее."""
    llm = next((t for t in item.relevance.breakdown if t.kind == "llm"), None)
    factors = {t.code: t for t in item.relevance.breakdown if t.kind == "factor"}
    if llm is not None and (code := llm.code.removeprefix("llm:")) in factors:
        return code, factors[code].exposure
    for term in item.relevance.breakdown:
        if term.kind == "factor":
            return term.code, term.exposure
        if term.kind == "chain":
            return ":".join(term.code.split(":")[:2]), None  # «chain:buyers:56» → «chain:buyers»
    return "", None


def model_view(item: FeedItem) -> tuple[str | None, str]:
    """Оценка модели верха ленты: «не задевает» | «слабо» | «заметно» | «сильно» и её объяснение."""
    term = next((t for t in item.relevance.breakdown if t.kind == "llm"), None)
    m = _LLM.match(term.label) if term else None
    return (m.group(1), m.group(2) or "") if m else (None, "")


def gist(item: FeedItem) -> str:
    """Суть события из заголовка: до « // », без точки — «ЦБ повысил прогноз цены на нефть Urals до $72»."""
    title = item.event.title.split(" // ")[0].strip().rstrip(".")
    return title if len(title) <= GIST_MAX else title[: GIST_MAX - 1].rsplit(" ", 1)[0] + "…"


def facts(item: FeedItem, key: str, exposure: ExposureMap | None) -> list[str]:
    """Числа из данных компании, почему событие её касается: группа, строка «для вас», признаки карты."""
    found = []
    gi = item.group_impact
    if gi and gi.affected_count:
        revenue = format_rub(gi.affected_revenue)
        found.append(f"касается {companies_genitive(gi.affected_count)} группы с выручкой {revenue}")
    if item.short and _DIGIT.search(item.short):
        found.append(_why(item))
    factor = next((f for f in exposure.factors if f.code == key), None) if exposure else None
    for e in factor.evidence if factor else []:
        if _DIGIT.search(e.value) and not _CODE_VALUE.match(e.value):
            value = e.value.split(";")[0].replace(" без самой компании", "").strip()
            label = _OKVED_LIST.sub("", e.label).strip().lower()
            found.append(f"{label}: {value}")
    return list(dict.fromkeys(found))


def _why(item: FeedItem) -> str:
    """Почему: строка «для вас» без названия причины («кредит у вас и у 11 компаний группы»)."""
    if item.short and item.short.startswith("Через "):
        return (item.short[:1].lower() + item.short[1:]).rstrip(".")  # «через покупателей: общепит — 53 %…»
    if item.short and ": " in item.short:
        return item.short.split(": ", 1)[1].strip().rstrip(".")
    return clean_channel(item.channel_text).strip().rstrip(".")


def _fits(*variants: str) -> str:
    for text in variants:
        if len(text) <= TEXT_MAX:
            return text
    cut = variants[-1][: TEXT_MAX - 1]
    return cut[: cut.rfind(" ")].rstrip(",;:— ") + "…"


def level_of(item: FeedItem, exposure_strength: float | None) -> str:
    score = item.relevance.score
    level = "act" if score >= ACT else "watch" if score >= WATCH else "info"
    if (exposure_strength is not None and exposure_strength < WEAK_EXPOSURE) or "событие за рубежом" in (
        item.relevance.reason
    ):
        level = "watch" if level == "act" else level
    view, _ = model_view(item)
    if view == "не задевает":
        return "info"
    if view == "слабо" and level == "act":
        return "watch"
    if view == "сильно" and level == "info":
        return "watch"
    return level


def action_for(item: FeedItem, role: str) -> str:
    key, _ = main_reason(item)
    actions = ACTIONS.get(key, {})
    return actions.get(role) or actions.get("default") or DEFAULT_ACTION


def takeaway(
    item: FeedItem,
    role: str,
    exposure: ExposureMap | None = None,
    avoid: set[str] | None = None,
    used_facts: set[str] | None = None,
) -> Takeaway:
    """Вывод по правилам: суть события — почему касается (число из данных) — что делать.

    `avoid` — уже выданные тексты ленты: тот же текст второй раз не повторяется; `used_facts` — уже названные
    числа: следующее событие с той же причиной берёт другое число, если оно есть.
    """
    if not item.relevance.breakdown:  # найдено поиском, но компанию не задевает
        return Takeaway(level="info", text=f"Напрямую вас не касается. {NOTHING}")
    key, strength = main_reason(item)
    level = level_of(item, strength)
    action = action_for(item, role)
    what = gist(item)
    numbers = facts(item, key, exposure)
    fresh = [n for n in numbers if n not in (used_facts or set())]
    why = (fresh or numbers or [_why(item)])[0]
    view, reason = model_view(item)

    brief = _brief(why)
    if level == "act":
        variants = [
            f"{what} — {why}. Что делать: {action}.",
            f"{what} — {brief}. Что делать: {action}.",
            f"{_cap(why)}. Что делать: {action}.",
            f"{_cap(brief)}. Что делать: {action}.",
            f"{_short(what)} — {brief}. Что делать: {action}.",  # то же число, но своё событие — не повтор
        ]
    elif level == "watch":
        variants = [
            f"{what} — может задеть: {why}. Следите; если подтвердится — {action}.",
            f"{what} — может задеть: {why}. Следите за продолжением.",
            f"Может задеть: {why}. Следите за продолжением.",
        ]
    elif view == "не задевает" and reason:
        variants = [
            f"Скорее не касается вас: {reason.rstrip('.')}.",
            f"{what} — скорее не касается вас. {NOTHING}",
        ]
    else:
        variants = [f"{what} — слабо касается вас: {why}. {NOTHING}", f"Слабо касается вас: {why}. {NOTHING}"]
    variants += [f"{what}. {_cap(action)}."]
    fitting = [v for v in variants if len(v) <= TEXT_MAX and v not in (avoid or set())]
    return Takeaway(level=level, text=fitting[0] if fitting else _fits(*variants))


def _brief(why: str) -> str:
    """Короткая форма причины с числом: «48 компаний, 116,8 млрд ₽», «кредиты у 11 компаний группы»."""
    if len(why) <= 50:
        return why
    if " — " in why:
        return why.split(" — ")[0]
    numbered = [part for part in why.split(", ") if _DIGIT.search(part)]
    return min(numbered, key=len) if numbered else why


def _short(what: str, limit: int = 35) -> str:
    return what if len(what) <= limit else what[: limit - 1].rsplit(" ", 1)[0] + "…"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def takeaways(items: list[FeedItem], role: str, exposure: ExposureMap | None = None) -> None:
    """Выводы всей ленты: одинаковых текстов нет — следующее событие получает свой вариант."""
    used: set[str] = set()
    named: set[str] = set()
    for item in items:
        item.takeaway = takeaway(item, role, exposure, used, named)
        used.add(item.takeaway.text)
        text = item.takeaway.text.casefold()
        named.update(n for n in facts(item, main_reason(item)[0], exposure) if n.casefold() in text)
