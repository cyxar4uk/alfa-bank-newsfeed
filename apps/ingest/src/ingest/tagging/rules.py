"""Разметка по словарям: факторы и отрасли с силой связи, тип события, регионы, страны.

Сила считается по месту и характеру совпадения (правила — в шапке dictionaries.toml), доказательства — найденные
слова с пометкой, где они стоят. Так ранжирование может разложить вклад события на слагаемые.
"""

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from ingest.models import FactorLink, SectorLink, Tags

# шаблон срабатывает только с начала слова: «газ» не найдётся внутри «Вагазин»
_WORD_START = r"(?<![\w-])"
STRENGTH = {("title", "strong"): 1.0, ("title", "weak"): 0.6, ("lead", "strong"): 0.6, ("lead", "weak"): 0.3}
EXTRA_PER_HIT = 0.1
REGION_FACTOR = ("region", "события региона")
_PLACE = {"title": "в заголовке", "lead": "в тексте"}


@dataclass(frozen=True)
class Entry:
    name: str
    strong: re.Pattern[str] | None
    weak: re.Pattern[str] | None = None
    code: str = ""
    okved: tuple[str, ...] = ()
    implies: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class Dictionaries:
    factors: tuple[Entry, ...]
    sectors: tuple[Entry, ...]
    event_types: tuple[Entry, ...]
    regions: tuple[Entry, ...]
    countries: tuple[Entry, ...]

    def sector_name(self, okved: str) -> str:
        return next((e.name for e in self.sectors if okved in e.okved), okved)


def _pattern(patterns: list[str] | None) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(f"{_WORD_START}(?:{p})" for p in patterns))


def _entries(items: list[dict]) -> tuple[Entry, ...]:
    return tuple(
        Entry(
            name=item["name"],
            strong=_pattern(item.get("strong") or item.get("patterns")),
            weak=_pattern(item.get("weak")),
            code=item.get("code", ""),
            okved=tuple(item.get("okved", ())),
            implies=tuple(item.get("implies", {}).items()),
        )
        for item in items
    )


@lru_cache(maxsize=4)
def load_dictionaries(path: str | None = None) -> Dictionaries:
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        raw = resources.files("ingest.tagging").joinpath("dictionaries.toml").read_text("utf-8")
        data = tomllib.loads(raw)
    return Dictionaries(
        factors=_entries(data["factor"]),
        sectors=_entries(data["sector"]),
        event_types=_entries(data["event_type"]),
        regions=_entries(data["region"]),
        countries=_entries(data["country"]),
    )


def prepare(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _whole_words(text: str, start: int, end: int) -> str:
    """Совпадение по основе «нефт» → слово целиком «нефти»: доказательство должно читаться."""
    while end < len(text) and (text[end].isalnum() or text[end] == "-"):
        end += 1
    return text[start:end]


def _hits(entry: Entry, parts: dict[str, str]) -> list[tuple[str, str, str]]:
    """Совпадения (место, сила шаблона, найденные слова), сильные раньше слабых, без повторов слов."""
    out, seen = [], set()
    for kind, pattern in (("strong", entry.strong), ("weak", entry.weak)):
        if pattern is None:
            continue
        for place, text in parts.items():
            for m in pattern.finditer(text):
                word = _whole_words(text, m.start(), m.end())
                if word not in seen:
                    seen.add(word)
                    out.append((place, kind, word))
    return out


def strength_of(hits: list[tuple[str, str, str]]) -> float:
    if not hits:
        return 0.0
    base = max(STRENGTH[(place, kind)] for place, kind, _ in hits)
    return round(min(1.0, base + EXTRA_PER_HIT * (len(hits) - 1)), 1)


def _evidence(hits: list[tuple[str, str, str]], limit: int = 4) -> list[str]:
    return [f"«{word}» {_PLACE[place]}" for place, _, word in hits[:limit]]


def tag(title: str, lead: str = "", dicts: Dictionaries | None = None) -> Tags:
    dicts = dicts or load_dictionaries()
    parts = {"title": prepare(title), "lead": prepare(lead)}

    factors: list[FactorLink] = []
    implied: list[SectorLink] = []
    for entry in dicts.factors:
        hits = _hits(entry, parts)
        if not hits:
            continue
        link = FactorLink(code=entry.code, name=entry.name, strength=strength_of(hits), evidence=_evidence(hits))
        factors.append(link)
        for okved, weight in entry.implies:
            implied.append(
                SectorLink(
                    okved=okved,
                    name=dicts.sector_name(okved),
                    strength=round(link.strength * weight, 1),
                    via=f"factor:{entry.code}",
                    evidence=link.evidence[:2],
                )
            )

    regions = [(e, _hits(e, parts)) for e in dicts.regions]
    regions = [(e, h) for e, h in regions if h]
    if regions:
        all_hits = [hit for _, h in regions for hit in h]
        code, name = REGION_FACTOR
        factors.append(FactorLink(code=code, name=name, strength=strength_of(all_hits), evidence=_evidence(all_hits)))

    sector_names, direct = [], []
    for entry in dicts.sectors:
        hits = _hits(entry, parts)
        if not hits:
            continue
        sector_names.append(entry.name)
        for okved in entry.okved:
            direct.append(
                SectorLink(
                    okved=okved, name=entry.name, strength=strength_of(hits), via="text", evidence=_evidence(hits)
                )
            )

    best: dict[str, SectorLink] = {}
    for link in direct + implied:  # при равной силе названная в тексте отрасль важнее выведенной из фактора
        if link.strength > 0 and (link.okved not in best or link.strength > best[link.okved].strength):
            best[link.okved] = link
    sector_links = sorted(best.values(), key=lambda s: (-s.strength, s.okved))
    factors.sort(key=lambda f: -f.strength)

    text = f"{parts['title']}\n{parts['lead']}"
    return Tags(
        topics=[f.name for f in factors],
        factors=factors,
        sectors=sector_names,
        sector_links=sector_links,
        okved=sorted(best),
        event_type=next((e.name for e in dicts.event_types if e.strong.search(text)), None),
        regions=[e.name for e, _ in regions],
        countries=[e.name for e in dicts.countries if e.strong.search(text)],
        tagged_by=["rules"],
    )
