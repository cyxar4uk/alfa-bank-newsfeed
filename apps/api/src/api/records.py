"""Записи выгрузки банка после очистки: пустое и мусор — None, а не ошибка."""

import math
import re
from dataclasses import dataclass, fields

COMPANY_COLUMNS = [
    "SYNTHETIC_U",
    "ORG_TYPE",
    "OKFS_NAME",
    "COMPANY_AGE_YEARS_GRADATION",
    "ECO_MARK_LABEL",
    "MAINOKVED_CODE",
    "MAINOKVED_NAME",
    "NEGATIVEMARK",
    "AMOUNT_WORKERS_FNS_GRADATION",
    "AMOUNT_WORKERS_SPARK_GRADATION",
    "CL_TYPE",
    "CL_PRODUCT_RKO_MARK",
    "CL_PRODUCT_GAR_MARK",
    "CL_PRODUCT_LOA_MARK",
    "CL_PRODUCT_LEA_MARK",
    "CL_PRODUCT_DEP_MARK",
    "CL_PRODUCT_ZPP_MARK",
    "FTS_FLAG",
    "FTS_COUNTRY_NAME",
    "FACTORING_MARK",
    "REVENUE_COMPANY",
    "GROUP_ID",
    "CITY",
    "REGION",
]

_ID = re.compile(r"^[A-Za-z]+_\d+$")
_EMPTY = {"nan", "none", "null", "n/a", "-"}
_FLAG_VALUES = {
    "1": True,
    "1.0": True,
    "true": True,
    "да": True,
    "0": False,
    "0.0": False,
    "false": False,
    "нет": False,
}


@dataclass
class CompanyRecord:
    id: str
    org_type: str | None = None
    okfs_name: str | None = None
    age_gradation: str | None = None
    eco_mark: str | None = None
    okved_code: str | None = None
    okved_name: str | None = None
    negative_mark: bool | None = None
    workers_fns: str | None = None
    workers_spark: str | None = None
    client_type: str | None = None
    rko: bool | None = None
    guarantee: bool | None = None
    credit: bool | None = None
    leasing: bool | None = None
    deposit: bool | None = None
    salary_project: bool | None = None
    fts_flag: bool | None = None
    fts_countries: str | None = None
    factoring: bool | None = None
    revenue: float | None = None
    group_id: str | None = None
    city: str | None = None
    region: str | None = None
    # сколько раз id встретился в выгрузке; больше 1 — взята первая запись
    duplicates: int = 1


COMPANY_FIELDS = [f.name for f in fields(CompanyRecord)]

# поле записи ← колонка CSV
_COLUMN_OF = dict(zip(COMPANY_FIELDS[1:-1], COMPANY_COLUMNS[1:], strict=True))
_FLAGS = {
    "negative_mark",
    "rko",
    "guarantee",
    "credit",
    "leasing",
    "deposit",
    "salary_project",
    "fts_flag",
    "factoring",
}


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value or (len(value) <= 4 and value.lower() in _EMPTY):
        return None
    return value


def clean_id(value: str | None) -> str | None:
    value = clean_text(value)
    return value if value and _ID.match(value) else None


def clean_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    return _FLAG_VALUES.get(value.strip().replace(",", ".").lower())


def clean_number(value: str | None) -> float | None:
    value = clean_text(value)
    if value is None:
        return None
    try:
        number = float(value.replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def company_from_row(row: dict[str, str | None]) -> CompanyRecord | None:
    """Строка CSV компаний → запись; без валидного id — None."""
    company_id = clean_id(row.get("SYNTHETIC_U"))
    if company_id is None:
        return None
    values: dict[str, object] = {}
    for field, column in _COLUMN_OF.items():
        raw = row.get(column)
        if field in _FLAGS:
            values[field] = clean_flag(raw)
        elif field == "revenue":
            revenue = clean_number(raw)
            # нулевая и отрицательная выручка в выгрузке означает «нет данных»
            values[field] = revenue if revenue is not None and revenue > 0 else None
        else:
            values[field] = clean_text(raw)
    return CompanyRecord(id=company_id, **values)


@dataclass
class Flow:
    """Сумма платежей между компанией и одним контрагентом в одну сторону."""

    counterparty_id: str
    direction: str  # "out" — компания платит контрагенту, "in" — контрагент платит компании
    amount: float
    payments: int
    counterparty: CompanyRecord | None = None
