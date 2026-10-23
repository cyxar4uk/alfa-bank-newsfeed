"""Токены для сравнения заголовков: нижний регистр, без стоп-слов, грубая основа слова."""

import re

_WORD = re.compile(r"[a-zа-яё0-9]+(?:[.,][0-9]+)?", re.I)
STEM_LEN = 5

STOPWORDS = frozenset(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от
    меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж
    вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
    будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один
    почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после
    над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед
    иногда лучше чуть том нельзя такой им более всегда конечно всю между это также года году году
    the a an of to in on for and or is are was be by with as at from
    """.split()
)


def tokens(text: str) -> list[str]:
    return [t.casefold().replace("ё", "е") for t in _WORD.findall(text)]


_CAPITALIZED = re.compile(r"(?<![\w-])[A-ZА-ЯЁ][\w-]*")
# одно и то же разными словами: «Банк России», «ЦБ», «ЦБ РФ» — не признак разных событий
_GENERIC_NAMES = frozenset({"банк", "росси", "рф", "цб", "центр", "минфи", "прави", "госду", "кремл", "мосби"})


def proper_names(title: str) -> set[str]:
    """Слова с заглавной буквы, кроме первого слова заголовка: «В аэропорту Сочи…» → {«сочи»}."""
    words = _CAPITALIZED.findall(title)
    if words and title.lstrip(' «"').startswith(words[0]):
        words = words[1:]
    names = {w.casefold().replace("ё", "е") for w in words}
    return {n for n in names if n[:STEM_LEN] not in _GENERIC_NAMES}


def same_name(a: str, b: str) -> bool:
    """Одно название в разных падежах: «Китай» и «Китае», но не «Нижнекамск» и «Нижнего»."""
    common = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        common += 1
    return common >= 3 and common >= min(len(a), len(b)) - 1


def share_name(a: set[str], b: set[str]) -> bool:
    return any(same_name(x, y) for x in a for y in b)


def stems(text: str) -> set[str]:
    """Основы значимых слов. Числа сохраняются целиком — «14%» и «16%» не должны совпасть."""
    out = set()
    for tok in tokens(text):
        if tok in STOPWORDS:
            continue
        if tok[0].isdigit():
            out.add(tok.replace(",", "."))
        elif len(tok) >= 3:
            out.add(tok[:STEM_LEN])
    return out
