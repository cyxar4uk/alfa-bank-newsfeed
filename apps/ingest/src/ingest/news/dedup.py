"""Склейка дублей: одна и та же ссылка и один сюжет у разных издателей.

Сюжет определяем по совпадению основ слов в заголовках в пределах окна по времени. Главной остаётся запись
самого приоритетного источника (регулятор раньше СМИ), остальные уходят в `also_reported_by`.
"""

from collections import defaultdict
from datetime import timedelta

from ingest.models import Mention, Source
from ingest.text import proper_names, share_name, stems

TIME_WINDOW = timedelta(hours=48)
JACCARD_MIN = 0.5
OVERLAP_MIN = 0.75
OVERLAP_MIN_SHARED = 4


def similar_titles(a: set[str], b: set[str], names_a: set[str] = frozenset(), names_b: set[str] = frozenset()) -> bool:
    if not a or not b:
        return False
    # шаблонные заголовки про разные места или компании — разные события:
    # «В аэропорту Сочи ввели ограничения» и «В аэропорту Казани ввели ограничения»
    if names_a and names_b and not share_name(names_a, names_b):
        return False
    # «повысил ставку до 16%» и «повысил ставку до 14%» — тоже разные события
    nums_a = {s for s in a if s[0].isdigit()}
    nums_b = {s for s in b if s[0].isdigit()}
    if nums_a and nums_b and not nums_a & nums_b:
        return False
    shared = len(a & b)
    if shared / len(a | b) >= JACCARD_MIN:
        return True
    # короткий заголовок целиком внутри длинного: «ЦБ сохранил ставку 14%» ⊂ «Банк России сохранил ставку 14%…»
    return shared >= OVERLAP_MIN_SHARED and shared / min(len(a), len(b)) >= OVERLAP_MIN


def _close_in_time(a: Source, b: Source) -> bool:
    if a.published_at is None or b.published_at is None:
        return True
    return abs(a.published_at - b.published_at) <= TIME_WINDOW


def _rank(item: Source, priority: dict[str, int]) -> tuple:
    has_lead = item.fragment != item.title
    ts = item.published_at.timestamp() if item.published_at else float("inf")
    return (priority.get(item.id, 99), not has_lead, ts)


def deduplicate(items: list[Source], priority: dict[str, int] | None = None) -> list[Source]:
    """priority: id записи → приоритет её ленты (меньше — главнее)."""
    priority = priority or {}

    by_url: dict[str, Source] = {}
    for item in items:
        prev = by_url.get(item.url)
        if prev is None or _rank(item, priority) < _rank(prev, priority):
            by_url[item.url] = item
    unique = list(by_url.values())

    parent = list(range(len(unique)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    title_stems = [stems(it.title) for it in unique]
    title_names = [proper_names(it.title) for it in unique]
    index: dict[str, list[int]] = defaultdict(list)
    for i, st in enumerate(title_stems):
        for s in st:
            index[s].append(i)

    for i, st in enumerate(title_stems):
        candidates = {j for s in st for j in index[s] if j > i}
        for j in candidates:
            if similar_titles(st, title_stems[j], title_names[i], title_names[j]) and _close_in_time(
                unique[i], unique[j]
            ):
                parent[find(j)] = find(i)

    clusters: dict[int, list[Source]] = defaultdict(list)
    for i, item in enumerate(unique):
        clusters[find(i)].append(item)

    result = []
    for members in clusters.values():
        members.sort(key=lambda it: _rank(it, priority))
        head, rest = members[0], members[1:]
        head = head.model_copy(
            update={
                "also_reported_by": [
                    Mention(publisher=m.publisher, title=m.title, url=m.url, published_at=m.published_at) for m in rest
                ]
            }
        )
        result.append(head)
    result.sort(key=lambda it: it.published_at.timestamp() if it.published_at else 0, reverse=True)
    return result
