"""Место для разметки языковой моделью поверх словарей.

Ключа к моделям пока нет, поэтому есть только интерфейс и заглушка. Настоящая реализация будет звать дешёвую
модель из разрешённого списка (Gemma 4 26B A4B) один раз при загрузке материала и кэшировать ответ.
"""

from typing import Protocol

from ingest.models import Source, Tags


class LlmTagger(Protocol):
    name: str

    def tag(self, source: Source) -> Tags: ...


class MockLlmTagger:
    """Детерминированная заглушка: ничего не добавляет, только отмечает, что шаг пройден."""

    name = "llm-mock"

    def tag(self, source: Source) -> Tags:
        return Tags(tagged_by=[self.name])


def make_llm_tagger(mode: str) -> LlmTagger | None:
    if mode == "off":
        return None
    if mode == "mock":
        return MockLlmTagger()
    raise ValueError(f"неизвестный режим разметки моделью: {mode}")


def _union(a: list[str], b: list[str]) -> list[str]:
    return a + [x for x in b if x not in a]


def merge_tags(base: Tags, extra: Tags) -> Tags:
    """Словари — основа; модель дополняет списки и заполняет тип события, если словари его не нашли."""
    return Tags(
        topics=_union(base.topics, extra.topics),
        sectors=_union(base.sectors, extra.sectors),
        okved=sorted(set(base.okved) | set(extra.okved)),
        event_type=base.event_type or extra.event_type,
        regions=_union(base.regions, extra.regions),
        countries=_union(base.countries, extra.countries),
        tagged_by=_union(base.tagged_by, extra.tagged_by),
    )
