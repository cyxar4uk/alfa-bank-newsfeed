"""Схемы ответов модели на шагах агента. Это не контракт: из черновика агент сам собирает `Insight`.

Модель пишет только факты, позицию банка, данные о компании и свои выводы. Оценки в рублях и предложение
продукта добавляют расчётные инструменты — модель их не пишет, поэтому `estimate` и `offer` здесь запрещены.
"""

from typing import Literal

from pydantic import BaseModel, Field

from api.contract import Confidence


class PlanFactor(BaseModel):
    code: str = Field(description="код фактора из карты чувствительности компании")
    why: str = Field(description="почему событие может задеть компанию через этот фактор, одна фраза")


class Plan(BaseModel):
    """Шаг «план»: какие факторы и каналы проверить и что искать."""

    factors: list[PlanFactor] = Field(description="2–4 фактора компании, которые стоит проверить")
    channels: list[Literal["direct", "buyers", "suppliers", "group"]] = Field(
        description="каналы, по которым событие может дойти до компании"
    )
    analytics_queries: list[str] = Field(
        description="1–4 коротких поисковых запроса по аналитике Альфа-Банка (2–5 слов)"
    )
    news_queries: list[str] = Field(
        default_factory=list, description="0–2 запроса по другим новостям: ожидания рынка, контекст"
    )
    need_group: bool = Field(default=False, description="нужно ли смотреть компании группы")
    need_estimates: bool = Field(
        default=False, description="нужен ли расчёт в рублях (ставка, депозит, курс)"
    )
    role_focus: str = Field(description="что важно именно этой роли в событии, одна фраза")


class DraftStatement(BaseModel):
    text: str = Field(min_length=1, description="одно утверждение по-русски, коротко и конкретно")
    origin: Literal["fact", "bank", "data", "ai"] = Field(
        description="fact — из новости или материала; bank — позиция Альфа-Банка; data — данные банка о"
        " компании; ai — твой вывод"
    )
    refs: list[str] = Field(default_factory=list, description="id из контекста: src:… и feat:…")
    confidence: Confidence = Field(default="high", description="для ai: high, medium или low")
    factor: str | None = Field(default=None, description="код фактора карты или канала, к которому относится")
    quote: str | None = Field(
        default=None,
        description=(
            "для fact и bank: дословная выдержка из текста источника (10–200 символов), без изменений",
        ),
    )


class DraftAction(BaseModel):
    text: str = Field(min_length=1)
    kind: Literal["question", "scenario"]
    refs: list[str] = Field(default_factory=list)


class Draft(BaseModel):
    """Черновик инсайта: шесть вопросов кейса, у каждого утверждения — происхождение и ссылки."""

    relevance_reason: str = Field(description="почему событие важно этой компании, одна фраза")
    relevance_refs: list[str] = Field(default_factory=list)
    what_happened: list[DraftStatement] = Field(description="факты события, origin=fact")
    why_it_matters: list[DraftStatement] = Field(
        description="связь с бизнесом: data (признаки компании) и ai (вывод) с учётом роли"
    )
    risks: list[DraftStatement] = Field(default_factory=list)
    opportunities: list[DraftStatement] = Field(default_factory=list)
    watch: list[DraftStatement] = Field(default_factory=list, description="за чем следить дальше")
    bank_view: list[DraftStatement] = Field(
        default_factory=list, description="только origin=bank, из аналитики Альфа-Банка; нет позиции — пусто"
    )
    actions: list[DraftAction] = Field(default_factory=list, description="2–4 конкретных шага для роли")
    warnings: list[str] = Field(default_factory=list, description="чего не хватает в данных")

    def statements(self) -> list[tuple[str, int, DraftStatement]]:
        blocks = {
            "what_happened": self.what_happened,
            "why_it_matters": self.why_it_matters,
            "risks": self.risks,
            "opportunities": self.opportunities,
            "watch": self.watch,
            "bank_view": self.bank_view,
        }
        return [(block, i, s) for block, items in blocks.items() for i, s in enumerate(items)]


class AskAnswer(BaseModel):
    """Ответ на уточняющий вопрос по инсайту."""

    on_topic: bool = Field(description="вопрос про это событие, компанию или их последствия")
    statements: list[DraftStatement] = Field(default_factory=list, description="ответ, 1–5 утверждений")
    refusal: str | None = Field(default=None, description="если вопрос не по теме — вежливый отказ")
