"""Схема материала (Source) — общий формат обмена с API, см. контракт.

Поля сверх контракта необязательные: `page`, `file`, `ocr_confidence` у фрагментов аналитики,
`also_reported_by` у склеенных новостей, `tags.countries` и `tags.tagged_by`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LEAD_MAX_CHARS = 500


class Tags(BaseModel):
    topics: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    okved: list[str] = Field(default_factory=list)
    event_type: str | None = None
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    tagged_by: list[str] = Field(default_factory=list)


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
    url: str | None = None
    published_at: datetime | None = None
    fragment: str
    tags: Tags = Field(default_factory=Tags)
    page: int | None = None
    file: str | None = None
    ocr_confidence: float | None = None
    also_reported_by: list[Mention] = Field(default_factory=list)
