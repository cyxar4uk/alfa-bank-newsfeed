"""Тема события и тема текста, сегодняшняя дата и данные компании, которым вывод не должен противоречить.

- Позиция банка — только по теме события: в разборе нефти, курса и налога не место цитате про ключевую ставку.
  Тема события — по факторам разметки и заголовку; тема цитаты — по её тексту.
- Даты: «следите за заседанием 23 октября», когда оно прошло, — ошибка; агент знает, какое сегодня число.
- Профиль: экспортёру не приписывать импорт (и наоборот) — направление ВЭД берётся из данных банка.
"""

import datetime as dt
import re

MSK = dt.timezone(dt.timedelta(hours=3))

# тема → как её узнать в тексте; одна тема — один набор слов, без синонимов «на всякий случай»
TOPIC_WORDS: dict[str, re.Pattern] = {
    # «ставка НДПИ» и «ставка налога» — не ставка денег; «рублей» в сумме — не курс
    "rate": re.compile(
        r"ставк\w*(?!\s+(?:НДПИ|НДС|НДФЛ|налог|пошлин|акциз|утильсбор))\b|\bДКП\b"
        r"|денежно-кредитн|кредитн|заимств|займ|долгов",
        re.IGNORECASE,
    ),
    "deposit": re.compile(r"депозит|вклад|размещени|доходност", re.IGNORECASE),
    "fx": re.compile(
        r"курс\w* (?:рубл|доллар|юан|евро|валют)|курс\w* \d|доллар|юан|\bевро\b|валют|₽/\$|руб\./\$"
        r"|(?:укреплени|ослаблени)\w* рубл|рубл\w* (?:укреп|ослаб|подешев|подорож|к доллар|к юан)",
        re.IGNORECASE,
    ),
    "inflation": re.compile(r"инфляц|подорожа|дорожа|рост\w* цен|цен\w* раст", re.IGNORECASE),
    "oil": re.compile(r"нефт|urals|brent|топлив|бензин|дизел|АЗС|нефтепродукт|НПЗ", re.IGNORECASE),
    "tax": re.compile(
        r"налог|НДС|НДФЛ|НДПИ|пошлин|акциз|сверхдоход|фискальн|утильсбор|\bсбор\w* (?:в бюджет|за\b)",
        re.IGNORECASE,
    ),
    "budget": re.compile(r"бюджет|госрасход|Минфин|ОФЗ|дефицит", re.IGNORECASE),
    "agro": re.compile(r"зерн|пшениц|урожа|агро|сельхоз|продовольств|удобрени", re.IGNORECASE),
    "metals": re.compile(r"металл|\bсталь|алюмин|никел|\bмед[ьи]\b|золот", re.IGNORECASE),
    "demand": re.compile(r"спрос|потреблени|продаж|розниц|ипотек|жиль|доход\w* населени", re.IGNORECASE),
    "labor": re.compile(r"рынок труда|зарплат|занятост|мигрант|кадр", re.IGNORECASE),
}
TOPIC_LABELS = {
    "rate": "ставка и кредиты",
    "deposit": "депозиты",
    "fx": "курс рубля",
    "inflation": "инфляция и цены",
    "oil": "нефть и топливо",
    "tax": "налоги и пошлины",
    "budget": "бюджет",
    "agro": "зерно и продовольствие",
    "metals": "металлы",
    "demand": "спрос",
    "labor": "рынок труда",
}
# фактор разметки → тема
FACTOR_TOPICS = {
    "rate": "rate",
    "deposit_yield": "deposit",
    "fx": "fx",
    "inflation": "inflation",
    "commodity_oil": "oil",
    "commodity_oil_gas": "oil",
    "tax_regulation": "tax",
    "gov": "budget",
    "commodity_agro": "agro",
    "commodity_fertilizers": "agro",
    "commodity_metals": "metals",
    "commodity_gold": "metals",
    "consumer": "demand",
    "demand": "demand",
    "labor": "labor",
}
# чем искать позицию банка по теме события: слова из материалов банка, а не пересказ новости
TOPIC_QUERIES = {
    "fx": "курс рубля прогноз конец года руб./$",
    "inflation": "инфляция прогноз конец года",
    "oil": "нефть Urals цена прогноз",
    "tax": "налог налоговая нагрузка",
    "budget": "бюджет дефицит расходы",
    "agro": "зерно урожай экспорт пшеница",
    "metals": "металлы цены сталь",
    "demand": "потребительский спрос розничные продажи",
    "labor": "рынок труда зарплаты",
}
# ставка и депозиты — одна тема для банка: прогноз ставки отвечает и на вопрос о доходности размещения
RELATED = {"rate": {"deposit"}, "deposit": {"rate"}}
MIN_FACTOR = 0.4


def text_topics(text: str) -> set[str]:
    return {topic for topic, words in TOPIC_WORDS.items() if words.search(text or "")}


def event_topics(event) -> set[str]:
    """Темы события: о чём заголовок; если по нему не понять — факторы разметки (сила от MIN_FACTOR).

    Заголовок важнее разметки: у новости про курс в факторах часто есть и ставка, но позиция банка нужна про
    курс, а не прогноз ключевой ставки.
    """
    title = text_topics(event.source.title)
    if title:
        return title
    return {
        FACTOR_TOPICS[f.code] for f in event.factors if f.code in FACTOR_TOPICS and f.strength >= MIN_FACTOR
    }


def topic_hits(text: str, topics: set[str]) -> int:
    """Сколько раз в тексте встречаются слова тем события (с родственными): не случайное слово."""
    wanted = set(topics)
    for t in topics:
        wanted |= RELATED.get(t, set())
    return sum(len(TOPIC_WORDS[t].findall(text or "")) for t in wanted if t in TOPIC_WORDS)


def on_topic(text: str, topics: set[str]) -> bool:
    """Текст (цитата банка) — по теме события. Тем у события нет — проверять не с чем."""
    if not topics:
        return True
    wanted = set(topics)
    for t in topics:
        wanted |= RELATED.get(t, set())
    return bool(text_topics(text) & wanted)


# --- даты ---------------------------------------------------------------------------------------------

_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}
_MONTH = (
    r"(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яйе]\b|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*"
    r"|ноябр\w*|декабр\w*)"
)
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH}(?:\s+(20\d\d))?", re.IGNORECASE)
_PART_MONTH = re.compile(
    rf"\b(?:в\s+)?(конц\w*|начал\w*|середин\w*)\s+{_MONTH}(?:\s+(20\d\d))?", re.IGNORECASE
)
_NUMERIC = re.compile(r"\b(\d{2})\.(\d{2})\.(20\d\d)\b")
# что-то ещё предстоит: следить, ждать, пройдёт, представит
_FUTURE = re.compile(
    r"следит|следите|ждите|ждём|ожида\w*|предстоящ|ближайш|состоится|пройд[её]т|представит|объявит|рассмотрит"
    r"|будет|станет|начн[её]т|вступ\w* в силу|\bк\s+\d|перед\s+",
    re.IGNORECASE,
)


def today() -> dt.date:
    return dt.datetime.now(MSK).date()


def _month(word: str) -> int:
    word = word.lower()
    return next(n for stem, n in _MONTHS.items() if word.startswith(stem))


YEAR_AHEAD_DAYS = (
    60  # дата без года раньше сегодня больше чем на два месяца — это следующий год («к 15 января»)
)
NEAR = 60  # слово будущего — рядом с датой, в том же предложении
_MATERIAL_DATE = re.compile(r"(?:\bот|материал\w*)\s*$", re.IGNORECASE)


def _date(year: int | None, month: int, day: int, now: dt.date) -> dt.date | None:
    try:
        date = dt.date(year or now.year, month, day)
    except ValueError:
        return None
    if year is None and (now - date).days > YEAR_AHEAD_DAYS:
        date = date.replace(year=now.year + 1)
    return date


def _mentions(text: str, now: dt.date) -> list[tuple[dt.date, str, int, int]]:
    """Даты в тексте: (дата, как написано, начало, конец)."""
    out = []
    for m in _DAY_MONTH.finditer(text):
        if date := _date(int(m[3]) if m[3] else None, _month(m[2]), int(m[1]), now):
            out.append((date, m[0], m.start(), m.end()))
    for m in _PART_MONTH.finditer(text):
        part = m[1].lower()
        day = 1 if part.startswith("начал") else 15 if part.startswith("середин") else 28
        if date := _date(int(m[3]) if m[3] else None, _month(m[2]), day, now):
            out.append((date, m[0], m.start(), m.end()))
    for m in _NUMERIC.finditer(text):
        if date := _date(int(m[3]), int(m[2]), int(m[1]), now):
            out.append((date, m[0], m.start(), m.end()))
    return out


def _sentence(text: str, start: int, end: int) -> str:
    """Предложение вокруг даты, но не дальше NEAR знаков в каждую сторону."""
    left = max(text.rfind(".", 0, start - 1), text.rfind(";", 0, start), start - NEAR - 1)
    rights = [i for i in (text.find(". ", end), text.find(";", end)) if i >= 0]
    right = min([*rights, end + NEAR])
    return text[left + 1 : right]


def past_as_future(text: str, now: dt.date | None = None) -> list[str]:
    """Прошедшие даты, о которых текст говорит как о будущем: «следите за заседанием 23 октября» 26.10.

    Слово будущего ищется в том же предложении, что и дата; дата материала («от 31.07.2026») — не событие.
    """
    now = now or today()
    out = []
    for date, label, start, end in _mentions(text or "", now):
        if date >= now or _MATERIAL_DATE.search(text[max(0, start - 12) : start]):
            continue
        if _FUTURE.search(_sentence(text, start, end)):
            out.append(label)
    return out


# --- профиль компании -------------------------------------------------------------------------------------

_EXPORT = re.compile(r"направлени\w*\s*[—-]?\s*экспорт|экспорт сырья|экспортёр|экспортер", re.IGNORECASE)
_IMPORT = re.compile(
    r"направлени\w*\s*[—-]?\s*импорт|импорт\w* (?:товар|сырь|комплект)|импортёр|импортер", re.IGNORECASE
)
_SAYS_IMPORT = re.compile(r"импорт\w*|закупк\w* за рубеж|зарубежн\w* поставщик|ввоз", re.IGNORECASE)
_SAYS_EXPORT = re.compile(r"экспорт\w*|продаж\w* за рубеж|зарубежн\w* покупател|вывоз", re.IGNORECASE)


def ved_direction(exposure) -> str | None:
    """Направление ВЭД компании по данным банка: export, import или None (не известно)."""
    text = " ".join(f.channel_text for f in exposure if f.code in ("fx", "ved_logistics"))
    export, imp = bool(_EXPORT.search(text)), bool(_IMPORT.search(text))
    if export and not imp:
        return "export"
    if imp and not export:
        return "import"
    return None


def contradicts_ved(text: str, direction: str | None) -> str | None:
    """Вывод приписывает компании противоположное направление ВЭД — что именно; иначе None."""
    if direction == "export" and _SAYS_IMPORT.search(text) and not _SAYS_EXPORT.search(text):
        return "по данным банка компания экспортирует, а не импортирует"
    if direction == "import" and _SAYS_EXPORT.search(text) and not _SAYS_IMPORT.search(text):
        return "по данным банка компания импортирует, а не экспортирует"
    return None
