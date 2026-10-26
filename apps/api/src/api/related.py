"""«По этой теме»: 3–6 событий рядом с открытой новостью — того же сюжета, фактора или близкие по заголовку.

Кандидаты — лента пользователя за две недели: то, что задевает его компанию, с выводом и уровнем ленты.
Близость: тот же сюжет (`api.week.story_key`) — 3, общий фактор с сильной меткой — 1, общие слова заголовка —
до 2 (доля общих основ). Берутся кандидаты с близостью от 1,5; среди них свежие — выше. Перепечатки одной
новости (почти тот же заголовок) не повторяются — ни открытой, ни друг друга.
"""

import datetime as dt
import re

from api.contract import FeedItem
from api.ranking import MSK
from api.takeaway import about
from api.week import TAG_MIN, story_key

RELATED_MIN, RELATED_MAX = 3, 6
CLOSE = 1.5  # ниже — «что-то про экономику», а не «по этой теме»
LOOSE = 1.0  # близких меньше трёх — добираем по общему фактору или паре общих слов
DUPLICATE = 0.6  # доля общих основ заголовков, при которой это та же новость в другом издании
_WORD = re.compile(r"[а-яёa-z0-9]+")
_STOP = {"после", "может", "могут", "будет", "станет", "время", "этого", "также", "более", "россии", "году"}


def stems(title: str) -> set[str]:
    """Основы значимых слов заголовка: первые 5 букв слов от 4 букв — «ставку»/«ставка» совпадут."""
    words = _WORD.findall(title.split(" // ")[0].casefold())
    return {w[:5] for w in words if len(w) >= 4 and w not in _STOP}


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _strong(item: FeedItem) -> set[str]:
    return {
        t.code
        for t in item.relevance.breakdown
        if t.kind == "factor"
        and (t.event_strength is None or t.event_strength >= TAG_MIN)
        and about(item, t.code)
    }


def closeness(target: FeedItem, other: FeedItem) -> float:
    score = 3.0 if story_key(target) == story_key(other) and story_key(target) != "other" else 0.0
    if _strong(target) & _strong(other):
        score += 1.0
    return score + 2.0 * overlap(stems(target.event.title), stems(other.event.title))


def _when(item: FeedItem) -> dt.datetime:
    return item.source.published_at or dt.datetime.min.replace(tzinfo=MSK)


def related(target: FeedItem, pool: list[FeedItem]) -> list[FeedItem]:
    """События по теме открытой новости: близкие, без перепечаток, свежие — выше, не больше шести."""
    own = stems(target.event.title)
    fresh = [
        i
        for i in pool
        if i.event_id != target.event_id
        and i.takeaway is not None
        and overlap(own, stems(i.event.title)) < DUPLICATE
    ]
    close = [i for i in fresh if closeness(target, i) >= CLOSE]
    if len(close) < RELATED_MIN:
        close = [i for i in fresh if closeness(target, i) >= LOOSE]
    picked: list[FeedItem] = []
    # среди перепечаток одной новости — самая близкая; потом — свежие выше
    for item in sorted(close, key=lambda i: -closeness(target, i)):
        if all(overlap(stems(item.event.title), stems(p.event.title)) < DUPLICATE for p in picked):
            picked.append(item)
    return sorted(picked[:RELATED_MAX], key=lambda i: _when(i), reverse=True)


def target_item(event_id: str, pool: list[FeedItem], fallback: FeedItem | None) -> FeedItem | None:
    """Открытая новость как элемент ленты: из ленты пользователя, иначе — собранная по самому событию."""
    return next((i for i in pool if i.event_id == event_id), fallback)
