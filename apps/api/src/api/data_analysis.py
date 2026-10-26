"""Сводный контракт аналитики платежных связей компании."""

from pydantic import BaseModel

from api.contract import CompanyProfile, Indicator
from api.data_quality import DataQualityPassport
from api.indirect import LIMITATION, IndirectPath


class DataAnalysisPath(IndirectPath):
    intermediary_name: str
    intermediary_industry: str | None = None
    counterparty_name: str
    counterparty_industry: str | None = None
    first_share_basis: str
    second_share_basis: str


class DataAnalysisIndirect(BaseModel):
    company_id: str
    paths: list[DataAnalysisPath]
    intermediaries_checked: int
    limitation: str = LIMITATION


class DataAnalysisResponse(BaseModel):
    company: CompanyProfile
    indicators: list[Indicator]
    quality: DataQualityPassport
    indirect: DataAnalysisIndirect | None
