"""Схемы ответов модели на шагах агента. Это не контракт: из черновика агент сам собирает `Insight`.

Модель пишет только факты, позицию банка, данные о компании и свои выводы. Оценки в рублях и предложение
продукта добавляют расчётные инструменты — модель их не пишет, поэтому `estimate` и `offer` здесь запрещены.
"""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from api.contract import BankConflict, Confidence, HypothesisCheck, Statement

_SHORT_SOURCE = re.compile(r"^(?:alfa|news):")


def _normalize_refs(refs: list[str]) -> list[str]:
    """Модель иногда сокращает ссылку («alfa:keyrate-2026-09#p1-6») — дописываем «src:»."""
    return [f"src:{r}" if _SHORT_SOURCE.match(r) else r for r in (x.strip() for x in refs) if r]


Refs = Annotated[list[str], AfterValidator(_normalize_refs)]


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


class DraftConflict(BaseModel):
    text: str = Field(min_length=1, description="в чём вывод расходится с позицией Альфа-Банка, одна фраза")
    refs: Refs = Field(description="фрагменты аналитики банка (src:alfa:…), с которыми вывод расходится")


class DraftStatement(BaseModel):
    text: str = Field(min_length=1, description="одно утверждение по-русски, коротко и конкретно")
    origin: Literal["fact", "bank", "data", "ai", "hypothesis"] = Field(
        description="fact — из новости или материала; bank — позиция Альфа-Банка; data — данные банка о"
        " компании; ai — твой вывод, опирающийся на данные; hypothesis — предположение, которое данные пока"
        " не подтверждают"
    )
    refs: Refs = Field(default_factory=list, description="id из контекста: src:… и feat:…")
    confidence: Confidence = Field(default="high", description="для ai и hypothesis: high, medium или low")
    factor: str | None = Field(default=None, description="код фактора карты или канала, к которому относится")
    quote: str | None = Field(
        default=None,
        description="для fact и bank: дословная выдержка из текста источника (10–200 символов),"
        " без изменений",
    )
    confirm: str | None = Field(default=None, description="для hypothesis: что её подтвердит")
    refute: str | None = Field(default=None, description="для hypothesis: что её опровергнет")
    bank_conflict: DraftConflict | None = Field(
        default=None, description="для ai и hypothesis: только если вывод расходится с позицией банка"
    )


def to_statement(s: DraftStatement) -> Statement:
    """Утверждение контракта из черновика: с условиями проверки гипотезы и расхождением с банком."""
    check = None
    if s.origin == "hypothesis" and (s.confirm or s.refute):
        check = HypothesisCheck(confirm=s.confirm, refute=s.refute)
    conflict = None
    if s.bank_conflict is not None and s.origin in ("ai", "hypothesis"):
        conflict = BankConflict(text=s.bank_conflict.text, refs=list(dict.fromkeys(s.bank_conflict.refs)))
    return Statement(
        text=s.text,
        origin=s.origin,
        refs=list(dict.fromkeys(s.refs)),
        confidence=s.confidence,
        bank_conflict=conflict,
        check=check,
    )


def cited(s: DraftStatement) -> list[str]:
    """Все ссылки утверждения, включая материалы банка, с которыми вывод расходится."""
    return [*s.refs, *(s.bank_conflict.refs if s.bank_conflict else [])]


class DraftAction(BaseModel):
    text: str = Field(min_length=1)
    kind: Literal["question", "scenario"]
    refs: Refs = Field(default_factory=list)


class Draft(BaseModel):
    """Черновик инсайта: шесть вопросов кейса, у каждого утверждения — происхождение и ссылки."""

    relevance_reason: str = Field(description="почему событие важно этой компании, одна фраза")
    relevance_refs: Refs = Field(default_factory=list)
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
