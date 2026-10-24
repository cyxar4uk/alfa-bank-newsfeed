"""Что агент берёт у других модулей — протоколы и плоские модели результатов.

Карту чувствительности, цепочку через контрагентов и группу считает модуль профиля (#28, #29, I), поиск
новостей и аналитики — модуль поиска. Агент зависит только от этих протоколов: адаптеры к настоящим функциям
лежат в `api.agent.adapters`, подделки для тестов — в тестах. Модели здесь — то, что видит агент: поля
с `refs`, по которым самопроверка сверяет ссылки утверждений.
"""

import datetime as dt
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from api.contract import CompanyProfile, Persona, Relevance, Source

Level = Literal["high", "medium", "low", "none", "no_data"]
LEVEL_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0, "no_data": 0}


class ExposureFactor(BaseModel):
    """Фактор карты чувствительности компании."""

    code: str = Field(examples=["rate", "demand_56"])
    label: str
    level: Level
    strength: float | None = Field(default=None, ge=0, le=1)
    channel_text: str = ""
    refs: list[str] = Field(default_factory=list, description="признаки-доказательства: feat:…")
    coverage: float | None = Field(default=None, ge=0, le=1)


class ChainCounterparty(BaseModel):
    id: str
    display_name: str
    sector: str | None = None
    share: float | None = None
    intra_group: bool = False


class Channel(BaseModel):
    """Канал, по которому событие доходит до компании."""

    kind: Literal["direct", "buyers", "suppliers", "group"]
    factor: str | None = Field(default=None, description="код фактора карты, если канал на него ложится")
    okved: str | None = None
    sector: str | None = None
    share: float | None = Field(default=None, description="доля соответствующей стороны оборота")
    coverage: float | None = None
    strength: float | None = None
    text: str
    refs: list[str] = Field(default_factory=list)
    counterparties: list[ChainCounterparty] = Field(default_factory=list)


class Chain(BaseModel):
    channels: list[Channel] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="чего не хватает: нет платежей, мало покрытие")


class GroupMember(BaseModel):
    id: str
    display_name: str
    sector: str | None = None
    revenue: float | None = None
    factors: list[str] = Field(default_factory=list)


class GroupImpact(BaseModel):
    group_id: str
    size: int
    members: list[GroupMember] = Field(default_factory=list, description="задетые участники")
    revenue_total: float | None = None
    text: str = ""
    refs: list[str] = Field(default_factory=list)


class CompanyData(Protocol):
    """Данные банка о компании и пользователе (модуль профиля)."""

    def persona(self, persona_id: str) -> Persona | None: ...

    def profile(self, company_id: str) -> CompanyProfile | None: ...

    def exposure_map(self, company_id: str) -> list[ExposureFactor]: ...

    def counterparty_chain(self, company_id: str, event: Source) -> Chain: ...

    def group_impact(self, company_id: str, event: Source) -> GroupImpact | None: ...

    def relevance(self, persona: Persona, event: Source) -> Relevance | None: ...


class FactorTag(BaseModel):
    code: str
    strength: float = 1.0
    evidence: list[str] = Field(default_factory=list)


class SectorTag(BaseModel):
    okved: str
    name: str = ""
    strength: float = 1.0
    via: str = "text"


class Expectation(BaseModel):
    who: str
    indicator: str | None = None
    values: list[str] = Field(default_factory=list)
    quote: str


class Event(BaseModel):
    """Событие с разметкой парсера: материал из контракта + факторы, отрасли, ожидания рынка."""

    source: Source
    factors: list[FactorTag] = Field(default_factory=list)
    sectors: list[SectorTag] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)
    body: str | None = Field(default=None, description="полный текст своей новости (у ленты — только лид)")
    warnings: list[str] = Field(
        default_factory=list, description="замечания разбора: обрезан, похоже на команды"
    )

    @property
    def id(self) -> str:
        return self.source.id

    @property
    def text(self) -> str:
        """Текст события целиком: заголовок и полный текст, если есть, иначе лид."""
        body = self.body or self.source.fragment or ""
        return f"{self.source.title}\n{body}" if body and body != self.source.title else self.source.title


class AnalyticsHit(BaseModel):
    """Фрагмент аналитики Альфа-Банка: адрес страницы, дата материала, текст фрагмента."""

    source: Source = Field(description="id фрагмента src:alfa:<материал>#p<стр>-<n>, page, title, fragment")
    page_ref: str = Field(description="src:alfa:<материал>#p<стр> — по нему берётся текст страницы")
    material_date: dt.date | None = None
    stale: bool = False


class Library(Protocol):
    """Новости и аналитика банка (модуль поиска)."""

    def get_event(self, event_id: str) -> Event | None: ...

    def search_news(
        self,
        query: str,
        *,
        factors: list[str] | None = None,
        before: dt.datetime | None = None,
        limit: int = 5,
    ) -> list[Event]: ...

    def search_alfa_analytics(
        self, query: str, *, factors: list[str] | None = None, limit: int = 5, material: str | None = None
    ) -> list[AnalyticsHit]: ...

    def alfa_page_text(self, ref: str) -> str | None: ...

    def parse_news(self, *, text: str | None = None, url: str | None = None) -> Event: ...


class ParseError(ValueError):
    """Свою новость не удалось разобрать: пустой текст, ссылка не открылась, это не новость."""
