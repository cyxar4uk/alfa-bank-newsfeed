"""Вывод по событию ленты: важно ли для компании и роли → почему (с числом из данных) → что делать.

Строится правилами по готовому элементу ленты: оценка, главная причина и строка «для вас». Если верх ленты
оценила модель (слагаемое `llm`), её оценка ограничивает уровень: «не задевает» — только «к сведению».
Текст — без технических слов: ни «фактор», ни «канал», ни «оценка».
"""

import re

from api.contract import FeedItem, Takeaway
from api.short import clean_channel

TEXT_MAX = 160
ACT = 0.5  # оценка, с которой событие важно: стоит действовать
WATCH = 0.35  # с которой — может задеть, стоит следить
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

# оценка модели из слагаемого llm: «оценка модели: не задевает — …» (api.agent.rerank.IMPACT_LABEL)
_LLM = re.compile(r"^оценка модели: (не задевает|слабо|заметно|сильно)(?: — (.*))?$")


def _main_reason(item: FeedItem) -> tuple[str, float | None]:
    """Ключ действия по главной причине (код фактора или канал цепочки) и зависимость компании."""
    for term in item.relevance.breakdown:
        if term.kind == "factor":
            return term.code, term.exposure
        if term.kind == "chain":
            return ":".join(term.code.split(":")[:2]), None  # «chain:buyers:56» → «chain:buyers»
    return "", None


def _model_view(item: FeedItem) -> tuple[str | None, str]:
    term = next((t for t in item.relevance.breakdown if t.kind == "llm"), None)
    m = _LLM.match(term.label) if term else None
    return (m.group(1), m.group(2) or "") if m else (None, "")


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


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def takeaway(item: FeedItem, role: str) -> Takeaway:
    key, exposure = _main_reason(item)
    actions = ACTIONS.get(key, {})
    action = actions.get(role) or actions.get("default") or DEFAULT_ACTION
    why = _why(item)
    score = item.relevance.score
    level = "act" if score >= ACT else "watch" if score >= WATCH else "info"
    if (exposure is not None and exposure < WEAK_EXPOSURE) or "событие за рубежом" in item.relevance.reason:
        level = "watch" if level == "act" else level
    if not item.relevance.breakdown:  # найдено поиском, но компанию не задевает
        return Takeaway(level="info", text=f"Напрямую вас не касается. {NOTHING}")
    view, reason = _model_view(item)
    if view == "не задевает":
        level = "info"
    elif view == "слабо" and level == "act":
        level = "watch"
    elif view == "сильно" and level == "info":
        level = "watch"

    if level == "act":
        text = _fits(f"Касается вас: {why}. {_cap(action)}.", f"Касается вас. {_cap(action)}.")
    elif level == "watch":
        text = _fits(
            f"Может задеть: {why}. Следите; если подтвердится — {action}.",
            f"Может задеть: {why}. Следите за продолжением.",
            f"Может задеть. {_cap(action)}, если подтвердится.",
        )
    elif view == "не задевает" and reason:
        text = _fits(f"Скорее не касается вас: {reason.rstrip('.')}.", f"Скорее не касается вас. {NOTHING}")
    else:
        text = _fits(f"Слабо касается вас: {why}. {NOTHING}", f"Слабо касается вас. {NOTHING}")
    return Takeaway(level=level, text=text)
