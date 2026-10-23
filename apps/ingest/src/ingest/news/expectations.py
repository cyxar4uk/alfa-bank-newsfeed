"""Ожидания рынка и аналитиков из текста новости — для сравнения с позицией банка (фича F).

Берём только предложения из заголовка и лида, где есть слово ожидания («ожидают», «прогноз», «консенсус»…).
Кто ожидает — по словарю ниже; показатель — фактор из каталога, найденный в этом же предложении; числа — как в тексте.
Цитата — предложение дословно, без пересказа: потребитель сверяет её с источником.
"""

import re

from ingest.models import Expectation
from ingest.tagging.rules import Dictionaries, load_dictionaries, prepare

_MARKER = re.compile(
    r"(?<![\w-])(ожида|прогноз|консенсус|рассчитыва|предполага|допуска|не исключа|закладыва|предсказ|"
    r"по оценк|оценива|полага|считают|сценари)",
    re.I,
)
# порядок важен: первым ищем самого конкретного «кто»
_WHO: list[tuple[str, re.Pattern[str]]] = [
    ("bank", re.compile(r"(?<![\w-])альфа-банк\w*", re.I)),
    (
        "international",
        re.compile(
            r"(?<![\w-])(мвф|международн\w* валютн\w* фонд\w*|всемирн\w* банк\w*|оэср|"
            r"рейтингов\w* агентств\w*)",
            re.I,
        ),
    ),
    (
        "analysts",
        re.compile(
            r"(?<![\w-])(консенсус[\w-]*|аналитик\w*|экономист\w*|эксперт\w*|опрошенн\w*|стратег\w*|"
            r"участник\w* опроса|брокер\w*)",
            re.I,
        ),
    ),
    ("market", re.compile(r"(?<![\w-])(участник\w* рынка|рын(ок|ки|ка)|инвестор\w*|трейдер\w*|фьючерс\w*)", re.I)),
    (
        "regulator",
        re.compile(
            r"(?<![\w-])(банк\w* россии|цб(?: рф)?|центробанк\w*|регулятор\w*|набиуллин\w*|"
            r"фрс|ецб)\b",
            re.I,
        ),
    ),
    (
        "government",
        re.compile(
            r"(?<![\w-])(минэкономразвития|минфин\w*|минэнерго|минпромторг\w*|правительств\w*|"
            r"министерств\w*|кабмин\w*)\b",
            re.I,
        ),
    ),
    # сначала название в кавычках («Северсталь»), и только потом безымянная «компания»
    ("company", re.compile(r"«[^»]{2,40}»")),
    ("company", re.compile(r"(?<![\w-])компани[яи]\w*", re.I)),
]
_VALUE = re.compile(
    r"[$€]\s?\d+(?:[.,]\d+)?|"
    r"[-−+]?\d+(?:[.,]\d+)?(?:\s?[-–]\s?\d+(?:[.,]\d+)?)?\s?"
    r"(?:%|п\.\s?п\.|б\.\s?п\.|руб\w*|₽|\$|долл\w*|юан\w*|евро|трлн|млрд|млн|миллион\w*|миллиард\w*|тыс\w*)"
)
# «инфляционные ожидания» — показатель, а не чьё-то ожидание
_METRIC = re.compile(r"инфляционн\w* ожидани\w*", re.I)
# показатели вне каталога факторов: ожидание по ним не приписываем фактору из соседнего предложения
_OUTSIDE_CATALOG = re.compile(r"ввп|валов\w* внутренн|рост\w* экономик|экономическ\w* рост|рецесси", re.I)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[«\"(А-ЯЁA-Z0-9])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def _who(sentence: str) -> tuple[str, str]:
    for kind, pattern in _WHO:
        m = pattern.search(sentence)
        if m:
            return m.group(0).strip("«»"), kind
    return "источник не назван", "other"


def _indicator(sentence: str, dicts: Dictionaries, use_weak: bool) -> str | None:
    """Первый по тексту фактор; слабые шаблоны — только когда известно, кто ожидает."""
    text = prepare(sentence)
    best, best_pos = None, len(text) + 1
    for entry in dicts.factors:
        for pattern in (entry.strong, entry.weak if use_weak else None):
            m = pattern.search(text) if pattern else None
            if m and m.start() < best_pos:
                best, best_pos = entry.code, m.start()
    return best


def extract(title: str, lead: str, dicts: Dictionaries | None = None) -> list[Expectation]:
    dicts = dicts or load_dictionaries()
    found: list[Expectation] = []
    texts = [title] + (sentences(lead) if lead and lead != title else [])
    context = None  # показатель из предыдущего предложения: «Brent превысила $112. Аналитики ожидают роста до $120.»
    for sentence in texts:
        # обрезанный лид кончается многоточием, которого нет в источнике — в цитату его не берём
        sentence = sentence.rstrip("…").rstrip()
        own = _indicator(sentence, dicts, use_weak=False)
        if not _MARKER.search(_METRIC.sub("", sentence)) or any(
            e.quote.rstrip(".!?") == sentence.rstrip(".!?") for e in found
        ):
            context = own or context
            continue
        who, kind = _who(sentence)
        indicator = _indicator(sentence, dicts, use_weak=kind != "other")
        # показатель берём из соседнего предложения, только если известно, кто ожидает
        if indicator is None and kind != "other" and not _OUTSIDE_CATALOG.search(sentence):
            indicator = context
        context = own or context
        # ожидание без показателя — общие слова, сравнивать с банком нечего
        if indicator is None:
            continue
        values = [v.strip() for v in _VALUE.findall(sentence)]
        # лид не длиннее 500 знаков, поэтому предложение берём целиком — цитата остаётся дословной
        found.append(Expectation(who=who, who_kind=kind, indicator=indicator, values=values, quote=sentence))
    return found
