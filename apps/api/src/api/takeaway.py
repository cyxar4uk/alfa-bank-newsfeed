"""Вывод по событию ленты: важно ли для компании и роли → почему (с числом из данных) → что делать.

Строится правилами по готовому элементу ленты: оценка, главная причина и строка «для вас». Если верх ленты
оценила модель (слагаемое `llm`), её оценка ограничивает уровень: «не задевает» — только «к сведению».
Текст — без технических слов: ни «фактор», ни «канал», ни «оценка».
"""

import re

from api.consequence import consequence, is_seller
from api.contract import ExposureMap, FeedItem, Takeaway
from api.profile import companies, format_rub
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
    "commodity_oil:seller": {"default": "пересмотрите цены продажи и запасы топлива"},
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
# короткие формы действий — когда полная не помещается в 160 знаков вместе с числом
SHORT_ACTIONS = {
    "rate": "сверьте сроки пересмотра ставок",
    "deposit_yield": "решите, фиксировать ли доходность",
    "fx": "оцените валютную позицию",
    "ved_logistics": "сверьте сроки расчётов с партнёрами",
    "commodity_oil": "пересчитайте затраты на топливо",
    "commodity_oil:seller": "пересмотрите цены продажи",
    "gov": "проверьте планы по госконтрактам",
    "consumer": "сверьте прогноз продаж",
    "inflation": "проверьте цены и издержки",
    "tax_regulation": "проверьте сроки изменений",
}
NOTHING = "Действий не нужно."
GIST_MAX = 55

# оценка модели из слагаемого llm: «оценка модели: не задевает — …» (api.agent.rerank.IMPACT_LABEL)
_LLM = re.compile(r"^оценка модели: (не задевает|слабо|заметно|сильно)(?: — (.*))?$")
_OKVED_LIST = re.compile(r"\s*с ОКВЭД[\d.,\s]+")
_DIGIT = re.compile(r"\d")
_NUMBERS = re.compile(r"\d+(?:[.,]\d+)?")
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


# от чего зависят компании группы, которых задевает событие, — по главной причине
DEPENDS = {
    "rate": "от кредитов",
    "deposit_yield": "от доходности свободных денег",
    "commodity_oil": "от цен на топливо",
    "fx": "от курса",
    "ved_logistics": "от внешней торговли",
    "gov": "от госзаказа",
    "consumer": "от спроса",
    "inflation": "от издержек",
    "tax_regulation": "от налогов и пошлин",
}
_GROUP_LINE = re.compile(r"^(\d+) компани\w*, ([\d,]+ (?:тыс\.|млн|млрд|трлн) ₽)")
_SHARE_OF = re.compile(r"^(\d+) из (\d+)$")


def _depend(n: int, key: str) -> str:
    verb = "зависит" if n % 10 == 1 and n % 100 != 11 else "зависят"
    return f" {verb} {DEPENDS[key]}" if key in DEPENDS else ""


def facts(item: FeedItem, key: str, exposure: ExposureMap | None) -> list[str]:
    """Числа из данных компании человеческими фразами: группа, строка «для вас», признаки компании."""
    found = []
    gi = item.group_impact
    if gi and gi.affected_count:
        n = gi.affected_count
        found.append(f"{companies(n)} группы с выручкой {format_rub(gi.affected_revenue)}{_depend(n, key)}")
    if item.short and _DIGIT.search(item.short):
        found.append(_why(item))
    factor = next((f for f in exposure.factors if f.code == key), None) if exposure else None
    for e in factor.evidence if factor else []:
        value = e.value.split(";")[0].replace(" без самой компании", "").strip()
        if not _DIGIT.search(value) or _CODE_VALUE.match(value):
            continue
        label = _OKVED_LIST.sub("", e.label).strip().lower()
        if m := _GROUP_LINE.match(value):  # «48 компаний, 116,8 млрд ₽ — 59 % выручки группы»
            n = int(m.group(1))
            found.append(f"{companies(n)} группы с выручкой {m.group(2)}{_depend(n, key)}")
        elif (m := _SHARE_OF.match(value)) and "кредит" in label:  # «11 из 28»
            found.append(f"кредиты у {m.group(1)} из {m.group(2)} компаний группы")
        elif not label.startswith("компании группы"):
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


def _action_key(item: FeedItem, exposure: ExposureMap | None) -> str:
    key, _ = main_reason(item)
    if key == "commodity_oil" and is_seller(exposure, key):
        return "commodity_oil:seller"  # торгует топливом: цена — его выручка, а не затраты
    return key


def action_for(item: FeedItem, role: str, exposure: ExposureMap | None = None) -> str:
    actions = ACTIONS.get(_action_key(item, exposure), {})
    return actions.get(role) or actions.get("default") or DEFAULT_ACTION


def short_action(item: FeedItem, role: str, exposure: ExposureMap | None = None) -> str:
    key = _action_key(item, exposure)
    return SHORT_ACTIONS.get(key) or action_for(item, role, exposure).split(" и ")[0]


def takeaway(
    item: FeedItem,
    role: str,
    exposure: ExposureMap | None = None,
    avoid: set[str] | None = None,
    used_facts: set[str] | None = None,
) -> Takeaway:
    """Вывод по правилам: что меняется для компании — число из её данных — что делать.

    `avoid` — уже выданные тексты ленты: тот же текст второй раз не повторяется; `used_facts` — уже названные
    числа: следующее событие с той же причиной берёт другое число, если оно есть.
    """
    if not item.relevance.breakdown:  # найдено поиском, но компанию не задевает
        return Takeaway(level="info", text=f"Напрямую вас не касается. {NOTHING}")
    key, strength = main_reason(item)
    level = level_of(item, strength)
    action = action_for(item, role, exposure)
    quick = short_action(item, role, exposure)
    what = gist(item)
    numbers = facts(item, key, exposure)
    fresh = [n for n in numbers if n not in (used_facts or set())]
    # сначала ещё не названные числа, потом остальные: берём первое, с которым фраза помещается целиком
    candidates = fresh + [n for n in numbers if n not in fresh] or [_why(item)]
    view, reason = model_view(item)
    # что меняется для компании → число из её данных; направление не определить — так и говорим
    known = consequence(item, key, exposure)
    tail = known.split(" — ", 1)[-1] if known else "направление пока неясно"  # «долг группы дороже»

    def lead(fact: str, short: bool = False) -> str:
        if known:
            return f"{known}: {fact}"
        return f"{_short(what) if short else what} — направление пока неясно. {_cap(fact)}"

    def variants_for(why: str) -> list[str]:
        brief = _brief(why)
        bare = re.sub(r" (?:зависят|зависит) от .+$", "", brief)  # без «зависят от кредитов»
        if level == "act":
            return [
                f"{lead(why)}. Что делать: {action}.",
                f"{lead(brief)}. Что делать: {action}.",
                f"{lead(brief)}. Что делать: {quick}.",
                f"{lead(bare)}. Что делать: {quick}.",
                f"{lead(bare, True)}. Что делать: {quick}.",
                # та же история другой заметкой: своё событие, то же последствие и число — не повтор
                f"{_short(what)} — {tail}: {bare}. Что делать: {quick}.",
            ]
        if level == "watch":
            return [
                f"{lead(why)}. Следите; если подтвердится — {action}.",
                f"{lead(brief)}. Следите; если подтвердится — {quick}.",
                f"{lead(bare)}. Следите; если подтвердится — {quick}.",
                f"{lead(bare)}. Следите за продолжением.",
                f"{lead(bare, True)}. Следите за продолжением.",
                f"{_short(what)} — {tail}: {bare}. Следите за продолжением.",
            ]
        if view == "не задевает" and reason:
            return [
                f"Скорее не касается вас: {reason.rstrip('.')}.",
                f"{what} — скорее не касается вас. {NOTHING}",
            ]
        if known:
            return [
                f"{known}, но вас касается слабо: {brief}. {NOTHING}",
                f"{what} — слабо касается вас. {NOTHING}",
            ]
        return [f"{what} — слабо касается вас: {brief}. {NOTHING}", f"{what} — слабо касается вас. {NOTHING}"]

    variants: list[str] = []
    fitting: list[str] = []
    for why in candidates:
        variants = variants_for(why)
        fitting = [v for v in variants if len(v) <= TEXT_MAX and v not in (avoid or set())]
        if fitting:
            break
    variants += [f"{what}. {_cap(action)}."]
    fitting = fitting or [v for v in variants if len(v) <= TEXT_MAX and v not in (avoid or set())]
    return Takeaway(level=level, text=fitting[0] if fitting else _fits(*variants))


def _brief(why: str) -> str:
    """Короткая форма причины с числом: «178 компаний группы с выручкой 149,0 млрд ₽ зависят от кредитов»."""
    if len(why) <= 70:
        return why
    for sep in (" — ", ": ", ", "):
        numbered = [part for part in why.split(sep) if _DIGIT.search(part)]
        if numbered and len(min(numbered, key=len)) < len(why):
            return min(numbered, key=len)
    return why


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
        # число названо, если все его цифры есть в тексте — и в сокращённой форме причины
        shown = set(_NUMBERS.findall(item.takeaway.text))
        for fact in facts(item, main_reason(item)[0], exposure):
            if set(_NUMBERS.findall(fact)) <= shown:
                named.add(fact)
