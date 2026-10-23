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

    # Кластер собирается вокруг главной записи: новая запись присоединяется, только если похожа на саму главную.
    # Так цепочка «бензин — рекорд» → «бензин Аи-95» → «дизель Аи-95» → «дизель после рекорда» не склеивает
    # четыре разных события в одно, как было бы при транзитивной склейке.
    unique.sort(key=lambda it: _rank(it, priority))
    heads: list[tuple[Source, set[str], set[str]]] = []
    clusters: list[list[Source]] = []
    index: dict[str, list[int]] = defaultdict(list)
    for item in unique:
        st, names = stems(item.title), proper_names(item.title)
        candidates = sorted({k for s in st for k in index[s]})
        for k in candidates:
            head, head_st, head_names = heads[k]
            if similar_titles(head_st, st, head_names, names) and _close_in_time(head, item):
                clusters[k].append(item)
                break
        else:
            for s in st:
                index[s].append(len(heads))
            heads.append((item, st, names))
            clusters.append([item])

    result = []
    for members in clusters:
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
