"""Адаптеры к настоящим модулям: карта и цепочка (`api.service`, #28/#29) и поиск (`api.search.SearchRepo`).

Сигнатуры — из раздела «Функции для агента» контракта команды. Модули приходят отдельными PR: пока какого-то
нет в коде, `build_service` берёт временную реализацию из `api.agent.adapters`. Здесь только перевод моделей
модулей в плоские модели агента (`api.agent.ports`) — без своей логики.
"""

import datetime as dt
import importlib
import re

from api.agent.adapters import ProfileCompanyData
from api.agent.ports import (
    AnalyticsHit,
    Chain,
    ChainCounterparty,
    Channel,
    Event,
    Expectation,
    ExposureFactor,
    FactorTag,
    ParseError,
    SectorTag,
)
from api.contract import Source

_CHANNEL_FACTOR = {"buyers": "demand", "suppliers": "supply"}


def optional(module: str, name: str):
    """Функция модуля, если модуль уже в коде; иначе None."""
    try:
        return getattr(importlib.import_module(module), name, None)
    except ImportError:
        return None


class ServiceCompanyData(ProfileCompanyData):
    """Профиль, карта и цепочка — функциями api-core; группа и персоны — как во временной реализации."""

    def __init__(self, repo, exposure_fn=None, chain_fn=None, profile_fn=None) -> None:
        super().__init__(repo)
        self._exposure_fn = exposure_fn
        self._chain_fn = chain_fn
        self._profile_fn = profile_fn

    def profile(self, company_id):
        if self._profile_fn is None:
            return super().profile(company_id)
        if company_id not in self._profiles:
            profile = self._profile_fn(self.repo, company_id)
            if profile is None:
                return None
            self._profiles[company_id] = profile
        return self._profiles[company_id]

    def exposure_map(self, company_id):
        if self._exposure_fn is None:
            return super().exposure_map(company_id)
        result = self._exposure_fn(self.repo, company_id)
        if result is None:
            return []
        out = []
        for f in result.factors:
            channel = getattr(f, "channel", None)
            out.append(
                ExposureFactor(
                    code=f.code,
                    label=f.label,
                    level=f.level,
                    strength=f.strength,
                    channel_text=(channel.text if channel else "")
                    + (" (оценка по отрасли)" if f.estimate else ""),
                    # в refs утверждений идут только признаки профиля: «exp:…» контракт инсайта не разрешает
                    refs=sorted({e.ref for e in f.evidence if e.ref.startswith("feat:")}),
                    coverage=f.coverage,
                )
            )
        return out

    def counterparty_chain(self, company_id, event: Source):
        if self._chain_fn is None:
            return super().counterparty_chain(company_id, event)
        okved = list(event.tags.okved)
        result = self._chain_fn(self.repo, company_id, okved) if okved else None
        if result is None:
            return Chain(
                gaps=["у события нет отраслей — цепочка через контрагентов не строится"] if not okved else []
            )
        channels = []
        for ch in result.channels:
            prefix = _CHANNEL_FACTOR.get(ch.kind)
            nodes = getattr(ch, "nodes", None) or []
            channels.append(
                Channel(
                    kind=ch.kind,
                    factor=f"{prefix}_{ch.okved}" if prefix and ch.okved else None,
                    okved=ch.okved,
                    sector=ch.sector,
                    share=ch.share,
                    coverage=ch.coverage,
                    strength=ch.strength,
                    text=ch.text,
                    refs=[r for r in ch.refs if r.startswith("feat:")],
                    counterparties=[
                        ChainCounterparty(
                            id=n.id,
                            display_name=n.display_name,
                            sector=n.sector,
                            share=n.share,
                            intra_group=bool(getattr(n, "intra_group", False)),
                        )
                        for n in nodes
                    ],
                )
            )
        gaps = list(getattr(result, "gaps", []) or [])
        if not channels and getattr(result, "reason", None):
            gaps.append(result.reason)
        return Chain(channels=channels, gaps=gaps)


def _event_from_news(item, body: str | None = None) -> Event:
    source = Source.model_validate(item.model_dump(include=set(Source.model_fields)))
    return Event(
        source=source,
        factors=[
            FactorTag(code=f.code, strength=f.strength, evidence=list(f.evidence)) for f in item.factors
        ],
        sectors=[
            SectorTag(okved=s.okved, name=s.name, strength=s.strength, via=s.via) for s in item.sector_links
        ],
        expectations=[
            Expectation(who=e.who, indicator=e.indicator, values=list(e.values), quote=e.quote)
            for e in item.expectations
        ],
        body=body,
    )


class SearchLibrary:
    """Поиск новостей и аналитики через `SearchRepo` модуля поиска."""

    def __init__(self, search, analyze_fn=None, analyze_error=None) -> None:
        self.search = search
        self._analyze = analyze_fn
        self._analyze_error = analyze_error
        self._bodies: dict[str, str] = {}

    def get_event(self, event_id):
        item = self.search.find_news(event_id)
        return _event_from_news(item, self._bodies.get(event_id)) if item else None

    def search_news(self, query, *, factors=None, before=None, limit=5):
        items = self.search.search_news(query, factors=factors or None, limit=limit, until=before)
        return [_event_from_news(i) for i in items]

    def search_alfa_analytics(self, query, *, factors=None, limit=5, material=None):
        out = []
        for f in self.search.search_alfa_analytics(query, material, limit=limit, factors=factors or None):
            source = Source.model_validate(f.model_dump(include=set(Source.model_fields)))
            published = f.published_at
            out.append(
                AnalyticsHit(
                    source=source,
                    page_ref=f.page_ref or re.sub(r"(#p\d+)-\d+$", r"\1", f.id),
                    material_date=published.date() if isinstance(published, dt.datetime) else None,
                    stale=f.stale,
                )
            )
        return out

    def alfa_page_text(self, ref):
        return self.search.alfa_page_text(ref)

    def parse_news(self, *, text=None, url=None):
        if self._analyze is None:
            raise ParseError("разбор своей новости недоступен")
        try:
            analyzed = self._analyze(url=url, text=text, store=self.search)
        except Exception as exc:
            if self._analyze_error is not None and isinstance(exc, self._analyze_error):
                raise ParseError(getattr(exc, "message", None) or str(exc)) from exc
            raise
        self._bodies[analyzed.news.id] = analyzed.text
        event = _event_from_news(analyzed.news, analyzed.text)
        event.warnings = list(analyzed.warnings)
        return event
