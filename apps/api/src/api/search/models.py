"""Материалы в выдаче поиска и ленте: `Source` по контракту плюс разметка парсера.

Оба класса — наследники `Source`: их можно класть в `Insight.sources` как есть, в ответе инсайта останутся
только поля контракта. Фрагмент аналитики банка при этом не длиннее 600 знаков: материалы банка нельзя
копировать целиком, наружу — короткий фрагмент с файлом и страницей.
"""

from typing import Literal, Self

from ingest.models import Expectation, FactorLink, Mention, Reliability, SectorLink
from ingest.structured_event import StructuredEvent
from pydantic import BaseModel, Field, model_validator

from api.contract import Source


class NewsItem(Source):
    """Новость: фрагмент — лид дословно (до 500 знаков), разметка факторами и отраслями с силой связи 0–1."""

    kind: Literal["news"] = "news"
    structured_event: StructuredEvent | None = None
    reliability: Reliability | None = Field(
        default=None, description="надёжность источника: official, agency, business_media, other"
    )
    image_url: str | None = Field(
        default=None, description="картинка материала: ссылка из ленты или og:image страницы (файл не храним)"
    )
    source_icon_url: str | None = Field(default=None, description="значок издания")
    text: str | None = Field(
        default=None,
        description="полный текст — только у одной новости по id и только где его разрешают условия издателя",
    )
    factors: list[FactorLink] = Field(
        default_factory=list, description="факторы каталога карты чувствительности с силой и доказательствами"
    )
    sector_links: list[SectorLink] = Field(
        default_factory=list, description="двузначные ОКВЭД с силой; via: text | factor:<код> | llm"
    )
    countries: list[str] = Field(default_factory=list)
    expectations: list[Expectation] = Field(
        default_factory=list, description="ожидания рынка из текста (фича F)"
    )
    also_reported_by: list[Mention] = Field(
        default_factory=list, description="тот же сюжет у других издателей"
    )
    score: float | None = Field(default=None, description="оценка совпадения с запросом 0–1; только в поиске")


PUBLIC_FRAGMENT_CHARS = 600


def short_fragment(text: str | None, limit: int = PUBLIC_FRAGMENT_CHARS) -> str | None:
    """Обрезать по слову, с многоточием; короткий текст — как есть."""
    if text is None or len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.6 else cut).rstrip(" ,;:—-") + "…"


class AlfaFragment(Source):
    """Фрагмент аналитики Альфа-Банка: файл, страница, название и дата материала.

    `fragment` всегда не длиннее 600 знаков — и в API, и в `Insight.sources`; весь фрагмент — в `text`, только
    внутри сервиса (агенту для контекста), в JSON не попадает.
    """

    kind: Literal["alfa_analytics"] = "alfa_analytics"
    material: str = Field(description="id материала: src:alfa:<материал>")
    file: str | None = Field(default=None, description="имя PDF-файла материала")
    page_ref: str | None = Field(default=None, description="id страницы: src:alfa:<материал>#p<N>")
    ocr_engine: str | None = Field(default=None, description="tesseract | qwen3-vl — каким движком распознан")
    stale: bool = Field(default=False, description="устаревший материал: позицией банка не считается")
    factors: list[FactorLink] = Field(default_factory=list)
    score: float | None = Field(default=None, description="оценка совпадения с запросом 0–1; только в поиске")
    text: str | None = Field(default=None, exclude=True, description="фрагмент целиком; не сериализуется")

    @model_validator(mode="after")
    def _short(self) -> Self:
        if self.fragment is not None and len(self.fragment) > PUBLIC_FRAGMENT_CHARS:
            self.text = self.text or self.fragment
            self.fragment = short_fragment(self.fragment)
        return self


class NewsPage(BaseModel):
    items: list[NewsItem]
    total: int = Field(description="всего новостей под фильтрами")
    limit: int
    offset: int
