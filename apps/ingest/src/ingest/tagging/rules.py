"""Разметка по словарям: темы, отрасли с кодами ОКВЭД, тип события, регионы, страны."""

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from ingest.models import Tags

# шаблон срабатывает только с начала слова: «газ» не найдётся внутри «Вагазин»
_WORD_START = r"(?<![\w-])"


@dataclass(frozen=True)
class Entry:
    name: str
    pattern: re.Pattern[str]
    okved: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dictionaries:
    topics: tuple[Entry, ...]
    sectors: tuple[Entry, ...]
    event_types: tuple[Entry, ...]
    regions: tuple[Entry, ...]
    countries: tuple[Entry, ...]


def _compile(items: list[dict]) -> tuple[Entry, ...]:
    out = []
    for item in items:
        pattern = re.compile("|".join(f"{_WORD_START}(?:{p})" for p in item["patterns"]))
        out.append(Entry(name=item["name"], pattern=pattern, okved=tuple(item.get("okved", ()))))
    return tuple(out)


@lru_cache(maxsize=4)
def load_dictionaries(path: str | None = None) -> Dictionaries:
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        raw = resources.files("ingest.tagging").joinpath("dictionaries.toml").read_text("utf-8")
        data = tomllib.loads(raw)
    return Dictionaries(
        topics=_compile(data["topic"]),
        sectors=_compile(data["sector"]),
        event_types=_compile(data["event_type"]),
        regions=_compile(data["region"]),
        countries=_compile(data["country"]),
    )


def prepare(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _matches(entries: tuple[Entry, ...], text: str) -> list[Entry]:
    return [e for e in entries if e.pattern.search(text)]


def tag_text(text: str, dicts: Dictionaries | None = None) -> Tags:
    dicts = dicts or load_dictionaries()
    text = prepare(text)
    sectors = _matches(dicts.sectors, text)
    event = next((e.name for e in dicts.event_types if e.pattern.search(text)), None)
    return Tags(
        topics=[e.name for e in _matches(dicts.topics, text)],
        sectors=[e.name for e in sectors],
        okved=sorted({code for e in sectors for code in e.okved}),
        event_type=event,
        regions=[e.name for e in _matches(dicts.regions, text)],
        countries=[e.name for e in _matches(dicts.countries, text)],
        tagged_by=["rules"],
    )
