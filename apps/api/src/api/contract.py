"""Контракт между бэком, фронтом и агентом — источник правды.

Профиль компании, тестовый пользователь, материал, инсайт и трасса. Поля по-английски, тексты по-русски.
Из этих моделей FastAPI строит OpenAPI (`/api/openapi.json`).

Ссылки (`refs`) указывают на `Source.id` (`src:...`, у фрагмента — `src:...#p2`)
и на `Feature.id` (`feat:...`).
"""

import datetime as dt
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Origin = Literal["fact", "bank", "ai", "data", "estimate", "offer"]
# происхождение, которое обязано ссылаться на источник или признак
SOURCED_ORIGINS = ("fact", "bank", "data")
Confidence = Literal["high", "medium", "low"]
Role = Literal["owner", "ceo", "cfo", "chief_accountant", "treasury", "other"]
BankProduct = Literal["rko", "guarantee", "credit", "leasing", "deposit", "salary_project", "factoring", "fx"]

ROLE_LABELS: dict[str, str] = {
    "owner": "Собственник",
    "ceo": "Генеральный директор",
    "cfo": "Финансовый директор",
    "chief_accountant": "Главный бухгалтер",
    "treasury": "Казначей",
    "other": "Сотрудник",
}


# --- Утверждение ----------------------------------------------------------------------------------


class Statement(BaseModel):
    """Единица любого вывода в инсайте: текст, происхождение и источники."""

    text: str = Field(min_length=1)
    origin: Origin = Field(
        description=(
            "fact — факт из новости, bank — позиция Альфа-Банка, ai — вывод модели, data — из данных банка"
            " о компании, estimate — расчёт по формуле, offer — предложение продукта банка"
        )
    )
    refs: list[str] = Field(
        default_factory=list, description="id источников (src:...) и признаков (feat:...)"
    )
    confidence: Confidence = Field(
        default="high", description="уверенность вывода модели; у fact, bank и data — high"
    )

    @model_validator(mode="after")
    def _check_origin(self) -> Self:
        if self.origin in SOURCED_ORIGINS:
            if not self.refs:
                raise ValueError(f"утверждение с origin={self.origin} должно ссылаться на источник (refs)")
            self.confidence = "high"
        return self


# --- Профиль компании -----------------------------------------------------------------------------

FeatureValue = str | int | float | bool | list[str] | None


class Feature(BaseModel):
    """Признак компании. `source=dataset` — поле выгрузки банка, `derived` — вычислен из других признаков."""

    id: str = Field(pattern=r"^feat:", examples=["feat:MAINOKVED_CODE"])
    label: str = Field(examples=["Основная деятельность"])
    value: FeatureValue
    display: str | None = Field(default=None, description="значение для показа человеку, если value — число")
    source: Literal["dataset", "derived"]
    derived_from: list[str] = Field(
        default_factory=list, description="признаки или наборы данных, из которых выведен"
    )


class MissingFeature(BaseModel):
    """Признак, которого нет в данных, — показываем честно."""

    id: str = Field(pattern=r"^feat:")
    label: str
    reason: str = "нет данных в выгрузке"


class Counterparty(BaseModel):
    """Крупный контрагент по платежам: роль, отрасль и доля в обороте компании."""

    id: str
    display_name: str
    in_dataset: bool = Field(description="есть ли контрагент в таблице компаний (иначе отрасль неизвестна)")
    okved: str | None = None
    sector: str | None = None
    role: Literal["supplier", "customer", "both"] = Field(
        description="supplier — компания ему платит, customer — он платит компании"
    )
    amount: float = Field(description="сумма платежей в обе стороны, ₽")
    payments: int = Field(description="число платежей")
    share: float = Field(ge=0, le=1, description="доля в платёжном обороте компании")
    intra_group: bool = Field(default=False, description="контрагент из той же группы компаний")


class CompanyGroup(BaseModel):
    id: str
    size: int = Field(description="число компаний в группе в выгрузке, включая эту")
    members: list[str] = Field(default_factory=list, description="другие компании группы (не больше 20)")


class SectorShare(BaseModel):
    """Доля одной стороны платёжного оборота, приходящаяся на контрагентов из класса ОКВЭД."""

    okved: str = Field(description="двузначный код ОКВЭД контрагентов", examples=["56"])
    sector: str | None = Field(description="отрасль по карте ОКВЭД")
    amount: float = Field(description="сумма платежей, ₽")
    share: float = Field(ge=0, le=1, description="доля от внешнего оборота этой стороны")
    counterparties: int


class PaymentSide(BaseModel):
    """Внешние платежи одной стороны: покупатели (платят компании) или поставщики (компания им платит)."""

    amount: float = Field(description="сумма внешних платежей, ₽ (без самоплатежей, выбросов и группы)")
    counterparties: int
    coverage: float = Field(
        ge=0,
        le=1,
        description="доля суммы, у которой отрасль контрагента известна (он есть в выгрузке с ОКВЭД)",
    )
    sectors: list[SectorShare] = Field(
        default_factory=list, description="по убыванию доли; неизвестные не входят"
    )


class PaymentStructure(BaseModel):
    """Структура платёжного оборота компании — основа каналов «через покупателей» и «через поставщиков»."""

    turnover: float = Field(description="весь учтённый оборот в обе стороны, включая группу, ₽")
    counterparties: int
    intra_group_amount: float = Field(description="оборот с компаниями своей группы, ₽ — в стороны не входит")
    intra_group_share: float = Field(ge=0, le=1)
    customers: PaymentSide
    suppliers: PaymentSide
    revenue_coverage: float | None = Field(
        default=None, description="оборот / выручка: какую часть бизнеса видно в платежах; нет выручки — null"
    )
    excluded_self_payments: int = 0
    excluded_outliers: int = 0


class IndustryPosition(BaseModel):
    """Место по выручке среди компаний того же ОКВЭД в данных банка — не доля рынка."""

    okved: str = Field(description="код ОКВЭД компании", examples=["45.31.1"])
    rank: int = Field(ge=1, description="место по выручке, 1 — крупнейшая")
    total: int = Field(description="компаний с этим кодом и известной выручкой")
    okved_class: str = Field(description="двузначный класс", examples=["45"])
    class_rank: int = Field(ge=1)
    class_total: int
    percentile: float = Field(ge=0, le=1, description="доля компаний с тем же кодом и меньшей выручкой")


class CompanyProfile(BaseModel):
    id: str = Field(examples=["U_1595"])
    display_name: str = Field(examples=["Компания №1595 · торговля розничная лекарственными средствами"])
    features: list[Feature]
    group: CompanyGroup | None = None
    counterparties: list[Counterparty] = Field(
        default_factory=list, description="топ-10 по сумме в обе стороны"
    )
    payments: PaymentStructure | None = Field(default=None, description="нет платежей в выгрузке — null")
    industry: IndustryPosition | None = Field(default=None, description="нет кода ОКВЭД или выручки — null")
    missing: list[MissingFeature] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list, description="что исправлено или отброшено при сборке")

    def feature(self, feature_id: str) -> Feature | None:
        return next((f for f in self.features if f.id == feature_id), None)


class CompanySummary(BaseModel):
    """Строка списка компаний."""

    id: str
    display_name: str
    sector: str | None
    okved: str | None
    revenue: float | None = Field(description="выручка, ₽")
    region: str | None
    client_type: str | None


# --- Пользователь ---------------------------------------------------------------------------------


class Persona(BaseModel):
    id: str = Field(examples=["u-cfo-1595"])
    company_id: str
    role: Role
    role_label: str = Field(examples=["Финансовый директор"])
    name: str = Field(examples=["Тестовый финансовый директор"])
    company_name: str
    sector: str | None = None


# --- Материал -------------------------------------------------------------------------------------


class SourceTags(BaseModel):
    topics: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list, description="отрасли по словарю разметки новостей")
    okved: list[str] = Field(
        default_factory=list, description="двузначные коды ОКВЭД — по ним материал сопоставляется с компанией"
    )
    event_type: str | None = None
    regions: list[str] = Field(default_factory=list)


class Source(BaseModel):
    id: str = Field(pattern=r"^src:", examples=["src:news:8f2a", "src:alfa:keyrate-2026-09#p2"])
    kind: Literal["news", "alfa_analytics"]
    title: str
    publisher: str | None = None
    url: str | None = None
    published_at: dt.datetime | None = None
    page: int | None = Field(default=None, description="страница материала банка, на которую ссылаемся")
    fragment: str | None = Field(default=None, description="цитата или фрагмент, на который ссылаемся")
    tags: SourceTags = Field(default_factory=SourceTags)


# --- Инсайт ---------------------------------------------------------------------------------------


class InsightEvent(BaseModel):
    title: str
    date: dt.date | None = None


class Relevance(BaseModel):
    score: float = Field(ge=0, le=1)
    reason: str
    refs: list[str] = Field(default_factory=list)


class Consequences(BaseModel):
    risks: list[Statement] = Field(default_factory=list)
    opportunities: list[Statement] = Field(default_factory=list)
    factors: list[Statement] = Field(default_factory=list)


class Action(BaseModel):
    text: str
    kind: Literal["question", "scenario", "product"]
    product: BankProduct | None = Field(
        default=None, description="продукт банка, если предложение обосновано"
    )
    refs: list[str] = Field(default_factory=list)


class Quality(BaseModel):
    checks_passed: list[str] = Field(
        default_factory=list, examples=[["refs", "facts_in_source", "multi_factor"]]
    )
    warnings: list[str] = Field(default_factory=list)


class Insight(BaseModel):
    """Ответ агента по паре «событие × пользователь»."""

    id: str = Field(pattern=r"^ins:")
    event: InsightEvent
    relevance: Relevance
    what_happened: list[Statement] = Field(default_factory=list)
    why_it_matters: list[Statement] = Field(default_factory=list)
    consequences: Consequences = Field(default_factory=Consequences)
    bank_view: list[Statement] = Field(
        default_factory=list, description="только origin=bank; пусто — позиции банка по теме нет"
    )
    actions: list[Action] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    features_used: list[str] = Field(default_factory=list)
    quality: Quality = Field(default_factory=Quality)
    trace_id: str | None = None

    @model_validator(mode="after")
    def _check_bank_view(self) -> Self:
        if any(s.origin != "bank" for s in self.bank_view):
            raise ValueError("в bank_view только утверждения с origin=bank")
        return self

    def statements(self) -> list[Statement]:
        c = self.consequences
        return [
            *self.what_happened,
            *self.why_it_matters,
            *c.risks,
            *c.opportunities,
            *c.factors,
            *self.bank_view,
        ]

    def unresolved_refs(self) -> set[str]:
        """Ссылки, которым нет источника в `sources` или признака в `features_used` — для самопроверки."""
        source_ids = {s.id for s in self.sources}
        features = set(self.features_used)
        refs = {r for s in self.statements() for r in s.refs}
        refs |= set(self.relevance.refs) | {r for a in self.actions for r in a.refs}

        def resolved(ref: str) -> bool:
            if ref.startswith("feat:"):
                return ref in features
            return ref in source_ids or ref.split("#", 1)[0] in source_ids

        return {r for r in refs if not resolved(r)}


# --- Трасса ---------------------------------------------------------------------------------------


class TraceStep(BaseModel):
    n: int = Field(ge=1)
    kind: Literal["plan", "tool", "llm", "check", "retry"]
    summary: str | None = None
    tool: str | None = None
    input: dict | None = None
    output_refs: list[str] = Field(default_factory=list)
    model: str | None = None
    purpose: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_rub: float | None = None
    verdict: Literal["pass", "fail"] | None = None


class Trace(BaseModel):
    id: str = Field(pattern=r"^tr:")
    insight_id: str | None = None
    steps: list[TraceStep] = Field(default_factory=list)


# --- Служебное ------------------------------------------------------------------------------------


class ImportedFile(BaseModel):
    file: str
    rows_read: int
    rows_loaded: int
    rows_skipped: int
    loaded_at: dt.datetime


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unavailable"]
    data: list[ImportedFile] = Field(default_factory=list)
