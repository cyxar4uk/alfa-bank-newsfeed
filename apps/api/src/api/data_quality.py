"""Паспорт качества платежных связей; только вычисления, без чтения БД и побочных эффектов."""

from pydantic import BaseModel, Field

from api.okved import okved_prefix
from api.profile import aggregate_flows
from api.records import CompanyRecord, Flow


class DataQualityDimension(BaseModel):
    known_amount: float = Field(ge=0)
    total_amount: float = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    unknown_share: float = Field(ge=0, le=1)


class DataQualityPassport(BaseModel):
    payments_present: bool
    external_counterparties: int = Field(ge=0)
    excluded_self_payments: int = Field(ge=0)
    excluded_outlier_counterparties: int = Field(ge=0)
    industry: DataQualityDimension
    counterparty: DataQualityDimension
    region: DataQualityDimension


def _dimension(total: float, known: float) -> DataQualityDimension:
    coverage = min(max(known / total, 0.0), 1.0) if total > 0 else 0.0
    return DataQualityDimension(
        known_amount=round(known, 2),
        total_amount=round(total, 2),
        coverage=round(coverage, 4),
        unknown_share=round(1.0 - coverage, 4) if total > 0 else 0.0,
    )


def data_quality(company: CompanyRecord, flows: list[Flow]) -> DataQualityPassport:
    """Сводка заполненности атрибутов по сумме внешних платежей (без группы, самоплатежей и выбросов)."""
    agg = aggregate_flows(company, flows)
    pairs = agg.external()
    total = sum(p.in_amount + p.out_amount for p in pairs)
    known_industry = sum(
        p.in_amount + p.out_amount
        for p in pairs
        if p.counterparty and okved_prefix(p.counterparty.okved_code)
    )
    known_region = sum(
        p.in_amount + p.out_amount
        for p in pairs
        if p.counterparty and (p.counterparty.region or p.counterparty.city)
    )
    known_counterparty = sum(p.in_amount + p.out_amount for p in pairs if p.counterparty is not None)
    return DataQualityPassport(
        payments_present=bool(flows),
        external_counterparties=len(pairs),
        excluded_self_payments=agg.self_payments,
        excluded_outlier_counterparties=len(agg.outliers),
        industry=_dimension(total, known_industry),
        counterparty=_dimension(total, known_counterparty),
        region=_dimension(total, known_region),
    )
