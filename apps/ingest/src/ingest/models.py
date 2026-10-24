"""Схема материала (Source) — общий формат обмена с API, см. контракт.

Поля сверх контракта необязательные. У новостей: `image_url`, `source_icon_url`, `text` (полный текст),
`also_reported_by` (тот же сюжет у других издателей), `expectations` (ожидания рынка и аналитиков из текста).
У аналитики: `page`, `file`, `page_ref`, `ocr_engine`, `ocr_confidence`, `ocr_fixes`, `stale`.
В разметке: `factors` и `sector_links` с силой связи, `countries`, `tagged_by`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LEAD_MAX_CHARS = 500
# надёжность источника: официальный, информационное агентство, деловое СМИ, прочее — задаётся у ленты в sources.toml
Reliability = Literal["official", "agency", "business_media", "other"]
RELIABILITY_LABELS: dict[str, str] = {
    "official": "официальный источник",
    "agency": "информационное агентство",
    "business_media": "деловое СМИ",
    "other": "СМИ",
}


class FactorLink(BaseModel):
    """Связь материала с фактором из каталога карты чувствительности. strength 0–1, evidence — найденные слова."""

    code: str
    name: str
    strength: float
    evidence: list[str] = Field(default_factory=list)


class SectorLink(BaseModel):
    """Связь с отраслью (двузначный ОКВЭД 2). via: «text» — отрасль названа в тексте, «factor:<код>» — через фактор."""

    okved: str
    name: str
    strength: float
    via: str
    evidence: list[str] = Field(default_factory=list)


class Tags(BaseModel):
    topics: list[str] = Field(default_factory=list)  # названия факторов — для совместимости с контрактом
    factors: list[FactorLink] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)  # названия отраслей — для совместимости с контрактом
    sector_links: list[SectorLink] = Field(default_factory=list)
    okved: list[str] = Field(default_factory=list)
    event_type: str | None = None
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    tagged_by: list[str] = Field(default_factory=list)


class Expectation(BaseModel):
    """Ожидание из текста новости (фича F): кто ожидает, что, по какому показателю. quote — дословно из лида."""

    who: str
    who_kind: Literal["analysts", "market", "international", "regulator", "government", "company", "bank", "other"]
    indicator: str | None = None  # код фактора, к которому относится ожидание
    values: list[str] = Field(default_factory=list)
    quote: str


class Mention(BaseModel):
    """Та же история у другого издателя — после склейки дублей."""

    publisher: str
    title: str
    url: str
    published_at: datetime | None = None


class Source(BaseModel):
    id: str
    kind: Literal["news", "alfa_analytics"]
    title: str
    publisher: str
    reliability: Reliability | None = None  # у новостей — уровень надёжности ленты
    url: str | None = None
    published_at: datetime | None = None
    fragment: str
    # у новостей: картинка (ссылка из ленты или og:image страницы, файл не храним), значок издания и полный текст —
    # только где его разрешают условия издателя (full_text у ленты в sources.toml)
    image_url: str | None = None
    source_icon_url: str | None = None
    text: str | None = None
    tags: Tags = Field(default_factory=Tags)
    page: int | None = None
    file: str | None = None
    page_ref: str | None = None
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    vlm_text: str | None = None
    ocr_fixes: list[str] | None = None  # у страницы: слова, исправленные по тексту Qwen3-VL («было → стало»)
    stale: bool | None = None
    also_reported_by: list[Mention] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)
