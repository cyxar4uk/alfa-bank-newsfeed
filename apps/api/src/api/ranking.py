"""Отбор и ранжирование событий под компанию и роль пользователя — без LLM.

Событие размечено факторами (`tags.factors`: код и сила связи 0–1) и отраслями (`tags.sector_links`:
двузначный ОКВЭД и сила). Компания описана картой чувствительности (`api.exposure`) и цепочкой влияния
(`api.chain`). Оценка — в `roles.toml`, там же веса ролей. У каждой оценки — разложение на слагаемые,
которые в сумме дают её.
"""

import datetime as dt
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.contract import (
    ChannelKind,
    ExposureMap,
    FactorExposure,
    FeedFactor,
    FeedItem,
    FeedRelevance,
    InfluenceChain,
    InsightEvent,
    Role,
    ScoreTerm,
    Source,
    SourceTags,
)

ROLES_PATH = Path(__file__).with_name("roles.toml")
MSK = dt.timezone(dt.timedelta(hours=3))


# --- Конфиг --------------------------------------------------------------------------------------


class Scoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_weight: float = Field(default=1.0, ge=0)
    half_life_days: float = Field(default=14, gt=0)
    min_freshness: float = Field(default=0.3, ge=0, le=1)
    bank_view_bonus: float = Field(default=0.05, ge=0, le=0.5)
    min_score: float = Field(default=0.03, ge=0, le=1)
    # каждое следующее событие с той же главной причиной — оценка × repeat_factor (разнообразие ленты)
    repeat_factor: float = Field(default=0.9, gt=0, le=1)
    # второе по силе слагаемое события — × next_term, третье — × next_term², …
    next_term: float = Field(default=1.0, gt=0, le=1)


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    focus: str
    weights: dict[str, float] = Field(default_factory=dict)

    def weight(self, key: str) -> float:
        if key in self.weights:
            return self.weights[key]
        # «commodity_*» — все коды с этим началом; самый длинный подходящий префикс
        prefixes = [k for k in self.weights if k.endswith("*") and key.startswith(k[:-1])]
        return self.weights[max(prefixes, key=len)] if prefixes else 1.0


class RankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    scoring: Scoring = Field(default_factory=Scoring)
    aliases: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, float] = Field(default_factory=lambda: {"default": 0.9})
    roles: dict[Role, RoleConfig]

    def quality(self, publisher: str | None) -> float:
        return self.sources.get(publisher or "", self.sources.get("default", 0.9))


def load_ranking(path: Path = ROLES_PATH) -> RankingConfig:
    with path.open("rb") as f:
        return RankingConfig.model_validate(tomllib.load(f))


@lru_cache
def default_ranking() -> RankingConfig:
    return load_ranking()


# --- Событие -------------------------------------------------------------------------------------


@dataclass
class NewsEvent:
    """Новость с разметкой — из базы поиска или из снимка `data/demo/news_snapshot.jsonl`."""

    id: str
    title: str
    published_at: dt.datetime | None
    publisher: str | None = None
    url: str | None = None
    fragment: str | None = None
    factors: list[tuple[str, float, str]] = field(default_factory=list)  # код, сила, название
    sectors: list[tuple[str, float]] = field(default_factory=list)  # двузначный ОКВЭД, сила
    tags: SourceTags = field(default_factory=SourceTags)

    def source(self) -> Source:
        return Source(
            id=self.id,
            kind="news",
            title=self.title,
            publisher=self.publisher,
            url=self.url,
            published_at=self.published_at,
            fragment=self.fragment,
            tags=self.tags,
        )


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _date(value: Any) -> dt.datetime | None:
    """Дата публикации всегда с поясом: без пояса — московское время, только дата — полночь по Москве."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        result = value
    elif isinstance(value, dt.date):
        result = dt.datetime.combine(value, dt.time())
    else:
        try:
            result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return result if result.tzinfo else result.replace(tzinfo=MSK)


def event_from(item: Any) -> NewsEvent:
    """Новость из базы поиска (`NewsItem`) или словарь из снимка JSONL → событие для ранжирования."""
    tags = _get(item, "tags") or {}
    factors = _get(item, "factors") or _get(tags, "factors") or []
    links = _get(item, "sector_links") or _get(tags, "sector_links") or []
    return NewsEvent(
        id=_get(item, "id"),
        title=_get(item, "title") or "",
        published_at=_date(_get(item, "published_at")),
        publisher=_get(item, "publisher"),
        url=_get(item, "url"),
        fragment=_get(item, "fragment"),
        factors=[
            (_get(f, "code"), float(_get(f, "strength") or 0), _get(f, "name") or _get(f, "code"))
            for f in factors
        ],
        sectors=[(str(_get(s, "okved")), float(_get(s, "strength") or 0)) for s in links],
        tags=SourceTags(
            topics=_get(tags, "topics") or [],
            sectors=_get(tags, "sectors") or [],
            okved=_get(tags, "okved") or [],
            event_type=_get(tags, "event_type"),
            regions=_get(tags, "regions") or [],
        ),
    )


# --- Оценка --------------------------------------------------------------------------------------


@dataclass
class _Term:
    term: ScoreTerm
    raw: float
    channel: ChannelKind
    channel_text: str
    refs: list[str]
    # на чём держится вклад: своя отрасль, покупатели, поставщики, группа — или сам фактор;
    # фактор карты и канал цепочки с одним основанием — одни и те же данные, считаются один раз
    basis: str


def freshness(published_at: dt.datetime | None, now: dt.datetime, scoring: Scoring) -> float:
    if published_at is None:
        return scoring.min_freshness
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=MSK)
    days = max((now - published_at).total_seconds() / 86400, 0.0)
    return max(0.5 ** (days / scoring.half_life_days), scoring.min_freshness)


ChainFn = Callable[[list[str], dict[str, float]], InfluenceChain]
BankViewFn = Callable[[list[str]], bool]


def _place(value: str) -> str:
    return value.casefold().removeprefix("г. ").strip()


def _factor_basis(factor: FactorExposure) -> str:
    kind = factor.channel.kind if factor.channel else "direct"
    if kind == "direct":
        top_ref = factor.evidence[0].ref if factor.evidence else ""
        return "okved" if top_ref == "feat:MAINOKVED_CODE" else f"factor:{factor.code}"
    return kind


def _times(n: int) -> str:
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} раза"
    return f"{n} раз"


def score_event(
    event: NewsEvent,
    exposure: ExposureMap,
    chain: ChainFn,
    role: Role,
    now: dt.datetime,
    bank_view: BankViewFn | None = None,
    config: RankingConfig | None = None,
    regions: set[str] | None = None,
) -> FeedItem | None:
    """Оценка события для компании (карта и цепочка) и роли; не касается компании — None.

    `regions` — регион и город компании: фактор «События региона» считается, только если событие про них.
    `bank_view(коды факторов)` — есть ли аналитика Альфа-Банка по факторам, которыми событие задевает
    компанию.
    """
    config = config or default_ranking()
    role_cfg = config.roles.get(role) or config.roles["other"]
    by_code = {f.code: f for f in exposure.factors}
    company_places = {_place(r) for r in regions or set() if r}
    event_places = {_place(r) for r in event.tags.regions if r}
    terms: list[_Term] = []
    matched: list[FeedFactor] = []

    # факторы события × чувствительность компании × вес роли
    for code, strength, _name in event.factors:
        code = config.aliases.get(code, code)
        factor = by_code.get(code)
        if not factor or not factor.strength or strength <= 0:
            continue
        if code == "region" and not (company_places & event_places):
            continue  # событие про другой регион
        weight = role_cfg.weight(code)
        raw = strength * factor.strength * weight
        if raw <= 0:
            continue
        matched.append(FeedFactor(code=code, label=factor.label))
        text = factor.channel.text if factor.channel else factor.label
        terms.append(
            _Term(
                ScoreTerm(
                    kind="factor",
                    code=code,
                    label=f"{factor.label}: {text}",
                    value=0.0,
                    event_strength=round(strength, 4),
                    exposure=factor.strength,
                    role_weight=weight,
                ),
                raw,
                factor.channel.kind if factor.channel else "direct",
                text,
                [factor.id, *[e.ref for e in factor.evidence[:2]]],
                _factor_basis(factor),
            )
        )

    # отрасли события → каналы цепочки × вес роли для канала
    if event.sectors:
        weights: dict[str, float] = {}
        for okved, strength in event.sectors:
            weights[okved] = max(weights.get(okved, 0.0), strength)
        result = chain(list(weights), weights)
        for c in result.channels:
            weight = role_cfg.weight(f"chain:{c.kind}")
            raw = c.strength * weight * config.scoring.chain_weight
            if raw <= 0:
                continue
            terms.append(
                _Term(
                    ScoreTerm(
                        kind="chain",
                        code=f"chain:{c.kind}:{c.okved}",
                        label=c.text,
                        value=0.0,
                        event_strength=c.weight,
                        exposure=c.share,
                        role_weight=weight,
                    ),
                    raw,
                    c.kind,
                    c.text,
                    c.refs,
                    "okved" if c.kind == "direct" else c.kind,
                )
            )

    # одно основание — один вклад: из фактора карты и канала цепочки с общим основанием берём больший
    best: dict[str, _Term] = {}
    for t in terms:
        if t.basis.startswith("factor:"):
            continue
        if t.basis not in best or t.raw > best[t.basis].raw:
            best[t.basis] = t
    terms = [t for t in terms if t.basis.startswith("factor:") or best[t.basis] is t]
    if not terms:
        return None

    # каждое следующее слагаемое события весит меньше: новость с десятком слабых тегов не обгоняет профильную
    terms.sort(key=lambda t: -t.raw)
    effective = [t.raw * config.scoring.next_term**i for i, t in enumerate(terms)]
    total = sum(effective)
    if total <= 0:
        return None
    fresh = freshness(event.published_at, now, config.scoring)
    quality = config.quality(event.publisher)
    base = min(total / (1 + total) * fresh * quality, 1.0)
    # порог — до бонуса: аналитика банка не делает релевантным событие, которое компанию не задевает
    if base < config.scoring.min_score:
        return None
    codes = list(dict.fromkeys(f.code for f in matched))
    has_bank_view = bool(codes and bank_view and bank_view(codes))
    bonus = min(config.scoring.bank_view_bonus, 1.0 - base) if has_bank_view else 0.0

    breakdown = []
    for t, value in zip(terms, effective, strict=True):
        t.term.value = round(value / total * base, 4)
        breakdown.append(t.term)
    if bonus:
        labels = ", ".join(f.label.lower() for f in matched)
        breakdown.append(
            ScoreTerm(
                kind="bank",
                code="bank_view",
                label=f"есть аналитика Альфа-Банка по фактору: {labels}",
                value=round(bonus, 4),
            )
        )
    # сумма округлённых слагаемых — оценка
    score = round(sum(t.value for t in breakdown), 4)

    top = terms[0]
    date = event.published_at.astimezone(MSK).date() if event.published_at else None
    return FeedItem(
        event_id=event.id,
        event=InsightEvent(title=event.title, date=date),
        relevance=FeedRelevance(
            score=score,
            reason=top.term.label,
            refs=list(dict.fromkeys([*top.refs, event.id])),
            breakdown=breakdown,
            freshness=round(fresh, 4),
            source_quality=quality,
        ),
        has_bank_view=has_bank_view,
        source=event.source(),
        factors=[FeedFactor(code=c, label=by_code[c].label) for c in codes],
        channel=top.channel,
        channel_text=top.channel_text,
    )


def _published(item: FeedItem) -> float:
    return item.source.published_at.timestamp() if item.source.published_at else 0.0


def rank(
    events: Iterable[NewsEvent],
    exposure: ExposureMap,
    chain: ChainFn,
    role: Role,
    now: dt.datetime,
    bank_view: BankViewFn | None = None,
    config: RankingConfig | None = None,
    regions: set[str] | None = None,
) -> list[FeedItem]:
    """События по убыванию оценки; не касающиеся компании отброшены.

    Цепочки кэшируются по отраслям события: у многих новостей одни и те же отрасли.
    """
    config = config or default_ranking()
    cache: dict[tuple, InfluenceChain] = {}

    def cached_chain(okved: list[str], weights: dict[str, float]) -> InfluenceChain:
        key = tuple(sorted(weights.items()))
        if key not in cache:
            cache[key] = chain(okved, weights)
        return cache[key]

    items = []
    for event in events:
        try:
            item = score_event(event, exposure, cached_chain, role, now, bank_view, config, regions)
        except ValueError:
            continue  # битая запись новости (не тот id, пустой заголовок) не роняет ленту
        if item:
            items.append(item)
    items.sort(key=lambda i: (-i.relevance.score, -_published(i), i.event_id))
    return _diversify(items, config.scoring.repeat_factor)


def _main_term(item: FeedItem) -> str:
    return next((t.code for t in item.relevance.breakdown if t.kind != "bank"), "")


def _diversify(items: list[FeedItem], repeat: float) -> list[FeedItem]:
    """Лента не из одной темы: k-е повторение главной причины — оценка × repeat^k.

    Снижение — отдельное слагаемое разложения «повтор темы», сумма слагаемых по-прежнему равна оценке.
    Жадно: на каждом шаге берётся событие с наибольшей оценкой с учётом уже взятых.
    """
    if repeat >= 1 or not items:
        return items
    seen: dict[str, int] = {}
    pending = list(items)
    result: list[FeedItem] = []
    while pending:
        best = max(
            pending, key=lambda i: (i.relevance.score * repeat ** seen.get(_main_term(i), 0), _published(i))
        )
        pending.remove(best)
        key = _main_term(best)
        times = seen.get(key, 0)
        if times:
            penalty = round(best.relevance.score * (1 - repeat**times), 4)
            best.relevance.breakdown.append(
                ScoreTerm(
                    kind="repeat",
                    code=f"repeat:{key}",
                    label=f"та же главная причина уже выше в ленте ({_times(times)})",
                    value=-penalty,
                )
            )
            best.relevance.score = round(best.relevance.score - penalty, 4)
        seen[key] = times + 1
        result.append(best)
    return result
