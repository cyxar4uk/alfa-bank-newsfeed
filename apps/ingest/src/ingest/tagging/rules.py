"""Разметка по словарям: факторы и отрасли с силой связи, тип события, регионы, страны.

Сила считается по месту и характеру совпадения (правила — в шапке dictionaries.toml), доказательства — найденные
слова с пометкой, где они стоят. Так ранжирование может разложить вклад события на слагаемые.
"""

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from ingest.models import FactorLink, SectorLink, Tags

# шаблон срабатывает только с начала слова: «газ» не найдётся внутри «Вагазин»
_WORD_START = r"(?<![\w-])"
STRENGTH = {("title", "strong"): 1.0, ("title", "weak"): 0.6, ("lead", "strong"): 0.6, ("lead", "weak"): 0.3}
EXTRA_PER_HIT = 0.1
REGION_FACTOR = ("region", "события региона")
HOME_COUNTRY = "Россия"
FOREIGN_NOTE = "событие в других странах — связь косвенная"
_PLACE = {"title": "в заголовке", "lead": "в тексте"}


@dataclass(frozen=True)
class Entry:
    name: str
    strong: re.Pattern[str] | None
    weak: re.Pattern[str] | None = None
    code: str = ""
    okved: tuple[str, ...] = ()
    implies: tuple[tuple[str, float], ...] = ()
    exclude: re.Pattern[str] | None = None


@dataclass(frozen=True)
class Dictionaries:
    factors: tuple[Entry, ...]
    sectors: tuple[Entry, ...]
    event_types: tuple[Entry, ...]
    regions: tuple[Entry, ...]
    countries: tuple[Entry, ...]
    noise: re.Pattern[str] | None = None
    # новость только о других странах: эти факторы не ставятся, отрасли из текста не сильнее foreign_cap
    domestic: re.Pattern[str] | None = None
    domestic_exclude: re.Pattern[str] | None = None
    foreign_factors: tuple[str, ...] = ()
    foreign_cap: float = 1.0
    foreign_trade: re.Pattern[str] | None = None
    # регион — фактор, только если рядом слова об экономике региона
    region_economy: re.Pattern[str] | None = None
    # не деловые категории (спорт, происшествия…) и те из них, что сильнее делового признака
    offtopic: tuple[Entry, ...] = ()
    offtopic_strict: dict[str, str] = field(default_factory=dict)  # категория → "True" | "always"
    business_words: re.Pattern[str] | None = None

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
            exclude=_pattern(item.get("exclude")),
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
        noise=_pattern(data.get("noise", {}).get("patterns")),
        domestic=_pattern(data.get("foreign", {}).get("domestic")),
        domestic_exclude=_pattern(data.get("foreign", {}).get("domestic_exclude")),
        foreign_factors=tuple(data.get("foreign", {}).get("factors", ())),
        foreign_cap=float(data.get("foreign", {}).get("sector_cap", 1.0)),
        foreign_trade=_pattern(data.get("foreign", {}).get("trade")),
        region_economy=_pattern(data.get("region_economy", {}).get("patterns")),
        offtopic=_entries(data.get("offtopic", [])),
        offtopic_strict={e["name"]: str(e["strict"]) for e in data.get("offtopic", []) if e.get("strict")},
        business_words=_pattern(data.get("business_words", {}).get("patterns")),
    )


def prepare(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _whole_words(text: str, start: int, end: int) -> str:
    """Совпадение по основе «нефт» → слово целиком «нефти»: доказательство должно читаться."""
    while end < len(text) and (text[end].isalnum() or text[end] == "-"):
        end += 1
    return text[start:end]


def blank(pattern: re.Pattern[str] | None, text: str) -> str:
    """Стереть фразы-исключения пробелами той же длины: остальной текст разбирается как прежде.

    Фраза стирается до конца последнего слова: хвост «…рубля» не должен остаться словом «я».
    """
    if pattern is None:
        return text
    out, pos = [], 0
    for m in pattern.finditer(text):
        start = max(m.start(), pos)
        end = m.start() + len(_whole_words(text, m.start(), m.end()))
        if end <= start:
            continue
        out += [text[pos:start], " " * (end - start)]
        pos = end
    return "".join(out) + text[pos:]


def _hits(entry: Entry, parts: dict[str, str]) -> list[tuple[str, str, str]]:
    """Совпадения (место, сила шаблона, найденные слова), сильные раньше слабых, без повторов слов."""
    if entry.exclude:
        parts = {place: blank(entry.exclude, text) for place, text in parts.items()}
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


def _foreign(title: str, countries: list[str], regions: list, text: str, dicts: Dictionaries) -> bool:
    """Новость только о других странах: России, её регионов и российских признаков нет, и при этом в заголовке названы
    две чужие страны (торговля между ними) или одна — без торговых слов («в Киеве отключили электроэнергию»).

    Чужая страна только в тексте — сравнение («…банки США поступили так же»), новость наша. Одна страна и торговля или
    выход на рынок — наша торговля с ней, просто Россия не названа: «импорт автомобилей из Китая упал».
    """
    if not dicts.foreign_factors and dicts.foreign_cap >= 1.0:
        return False
    if HOME_COUNTRY in countries or regions:
        return False
    if dicts.domestic and dicts.domestic.search(blank(dicts.domestic_exclude, text)):
        return False
    abroad = [e.name for e in dicts.countries if e.name != HOME_COUNTRY and e.strong.search(title)]
    trade = bool(dicts.foreign_trade and dicts.foreign_trade.search(text))
    return len(abroad) >= 2 or (len(abroad) == 1 and not trade)


def _capped(link: SectorLink, cap: float) -> SectorLink:
    """Отрасль, названная в новости о других странах, — не сильнее cap; выведенная из сырьевого фактора — как есть."""
    if link.via != "text" or link.strength <= cap:
        return link
    return link.model_copy(update={"strength": cap, "evidence": [*link.evidence, FOREIGN_NOTE]})


def _region_economy(parts: dict[str, str], dicts: Dictionaries) -> list[tuple[str, str, str]]:
    """Слова об экономике региона (налоги, бюджет, аренда, ограничения для транспорта, поддержка бизнеса)."""
    if dicts.region_economy is None:
        return []
    return _hits(Entry(name="region_economy", strong=dicts.region_economy), parts)


def business_verdict(
    raw: dict[str, str], signals: dict[str, list[tuple[str, str, str]]], dicts: Dictionaries
) -> tuple[bool | None, str]:
    """Деловая ли новость для руководителя компании: True, False или None — сомнительная, решает модель.

    Сильный деловой признак в заголовке (фактор или отрасль из словаря) — деловая; не деловая категория (спорт,
    происшествие, культура…) без делового следа — нет, а со следом (слабый признак, слово о бизнесе) — сомнительная.
    Строгие категории сильнее признака: поздравление таможенников — не новость о таможне. Сильный признак только в
    тексте — деловая, если нигде нет не деловой категории.
    """
    if not dicts.offtopic:
        return True, "отсев не настроен"

    def offtopic(text: str) -> Entry | None:
        return next((e for e in dicts.offtopic if e.strong and e.strong.search(text)), None)

    def strong(place: str) -> list[str]:
        return [word for hits in signals.values() for p, kind, word in hits if p == place and kind == "strong"]

    off_title, off_lead = offtopic(raw["title"]), offtopic(raw["lead"])
    title_strong, lead_strong = strong("title"), strong("lead")
    # хоть какой-то деловой след: слабый признак фактора или слово о бизнесе — такое отсеивать без модели не будем
    trace = any(signals.values()) or bool(
        dicts.business_words and dicts.business_words.search(f"{raw['title']}\n{raw['lead']}")
    )
    if off_title and off_title.name in dicts.offtopic_strict:
        # строгая категория сильнее отрасли («Локомотив» проиграл), "always" — и фактора («поздравил таможенников»);
        # слова о бизнесе в заголовке сильнее любой: «футболист купил завод» решит модель
        if dicts.business_words and dicts.business_words.search(raw["title"]):
            return None, f"{off_title.name}, но в заголовке слова о бизнесе"
        factor_strong = [w for k, hits in signals.items() if not k.startswith("sector:") for p, kind, w in hits
                         if p == "title" and kind == "strong"]  # fmt: skip
        if factor_strong and dicts.offtopic_strict[off_title.name] != "always":
            return None, f"{off_title.name}, но в заголовке «{factor_strong[0]}»"
        return False, off_title.name
    if title_strong:
        return True, f"деловые слова в заголовке: «{title_strong[0]}»"
    if off_title and not trace:
        return False, off_title.name
    if lead_strong and not (off_title or off_lead):
        return True, f"деловые слова в тексте: «{lead_strong[0]}»"
    if off_lead and not trace:
        return False, off_lead.name
    if off_title or off_lead:
        return None, f"{(off_title or off_lead).name}, но есть деловые слова"
    return None, "только слабые деловые признаки" if trace else "нет деловых признаков"


def tag(title: str, lead: str = "", dicts: Dictionaries | None = None) -> Tags:
    dicts = dicts or load_dictionaries()
    raw = {"title": prepare(title), "lead": prepare(lead)}
    # факторы, отрасли и регионы — без фраз-шума («Золотой мяч», «взрыв газа»); тип события и страны — по всему тексту
    parts = {place: blank(dicts.noise, text) for place, text in raw.items()}

    factors: list[FactorLink] = []
    implied: list[SectorLink] = []
    signals: dict[str, list[tuple[str, str, str]]] = {}  # код фактора или «sector:<название>» → совпадения
    for entry in dicts.factors:
        hits = _hits(entry, parts)
        if not hits:
            continue
        signals[entry.code] = hits
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
    economy = _region_economy(parts, dicts)
    if regions and economy:
        signals["region"] = economy  # аренда, налоги, бюджет региона — деловой признак
        all_hits = [hit for _, h in regions for hit in h] + economy
        code, name = REGION_FACTOR
        factors.append(FactorLink(code=code, name=name, strength=strength_of(all_hits), evidence=_evidence(all_hits)))

    sector_names, direct = [], []
    for entry in dicts.sectors:
        hits = _hits(entry, parts)
        if not hits:
            continue
        signals[f"sector:{entry.name}"] = hits
        sector_names.append(entry.name)
        for okved in entry.okved:
            direct.append(
                SectorLink(
                    okved=okved, name=entry.name, strength=strength_of(hits), via="text", evidence=_evidence(hits)
                )
            )

    text = f"{raw['title']}\n{raw['lead']}"
    countries = [e.name for e in dicts.countries if e.strong.search(text)]
    if _foreign(raw["title"], countries, regions, text, dicts):
        # до выбора сильнейшей связи: у отрасли, названной в тексте и выведенной из сырьевого фактора, останется вторая
        dropped = {f.code for f in factors if f.code in dicts.foreign_factors}
        factors = [f for f in factors if f.code not in dropped]
        signals = {k: v for k, v in signals.items() if k not in dropped}
        implied = [s for s in implied if s.via.removeprefix("factor:") not in dropped]
        direct = [_capped(s, dicts.foreign_cap) for s in direct]

    best: dict[str, SectorLink] = {}
    for link in direct + implied:  # при равной силе названная в тексте отрасль важнее выведенной из фактора
        if link.strength > 0 and (link.okved not in best or link.strength > best[link.okved].strength):
            best[link.okved] = link
    sector_links = sorted(best.values(), key=lambda s: (-s.strength, s.okved))
    factors.sort(key=lambda f: -f.strength)
    business, reason = business_verdict(raw, signals, dicts)
    return Tags(
        business=business,
        business_reason=reason,
        topics=[f.name for f in factors],
        factors=factors,
        sectors=sector_names,
        sector_links=sector_links,
        okved=sorted(best),
        event_type=next((e.name for e in dicts.event_types if e.strong.search(text)), None),
        regions=[e.name for e, _ in regions],
        countries=countries,
        tagged_by=["rules"],
    )
