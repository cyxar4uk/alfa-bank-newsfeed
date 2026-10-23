"""Новости: ленты → нормализация → склейка дублей → разметка."""

from ingest.models import Source
from ingest.news.dedup import deduplicate
from ingest.news.fetch import Feed, FeedReport, RawItem, fetch_all
from ingest.news.normalize import normalize
from ingest.tagging.llm import LlmTagger, merge_tags
from ingest.tagging.rules import tag_text


def tag_source(source: Source, llm: LlmTagger | None = None) -> Source:
    tags = tag_text(f"{source.title}\n{source.fragment}")
    if llm is not None:
        tags = merge_tags(tags, llm.tag(source))
    return source.model_copy(update={"tags": tags})


def build_news(raw: list[RawItem], llm: LlmTagger | None = None) -> list[Source]:
    priority: dict[str, int] = {}
    items = []
    for r in raw:
        src = normalize(r)
        if src is None:
            continue
        priority[src.id] = min(priority.get(src.id, r.priority), r.priority)
        items.append(src)
    return [tag_source(s, llm) for s in deduplicate(items, priority)]


def collect_news(feeds: list[Feed], llm: LlmTagger | None = None) -> tuple[list[Source], list[FeedReport]]:
    raw, reports = fetch_all([f for f in feeds if f.enabled])
    return build_news(raw, llm), reports
