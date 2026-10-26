"""Независимая сверка платежных показателей с исходными CSV.

Запуск из корня: python -m uv run --project apps/api python scripts/validate_company_metrics.py
CSV-файлы компаний и платежей каждый читаются ровно один раз. Expected считается непосредственно из строк CSV,
с ручным применением фильтров self / intragroup / directional outlier; api.profile.aggregate_flows не используется
для expected. Сравнение — детерминированная арифметическая сверка, не оценка точности модели или LLM.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from api.indicators import company_indicators
from api.okved import okved_prefix
from api.records import (
    CompanyRecord,
    Flow,
    clean_flag,
    clean_id,
    clean_number,
    clean_text,
)

TARGETS = ("U_8318", "U_34911", "U_258116")
COMPANIES_FILE = "df_Uid_data_hack.csv"
PAYMENTS_FILE = "df_Uid_payment_hack.csv"
ID_RE = re.compile(r"^[A-Za-z]+_[0-9]+$")
COUNTRY_WARNING = (
    "Страна ВЭД не указывает валюту или направление расчётов; одна сумма может относиться к нескольким "
    "странам, поэтому доли пересекаются и не складываются в долю оборота."
)


def _record(row: dict[str, str]) -> CompanyRecord | None:
    company_id = clean_id(row.get("SYNTHETIC_U"))
    if company_id is None:
        return None
    revenue = clean_number(row.get("REVENUE_COMPANY"))
    if revenue is None or revenue <= 0 or revenue == 1000:
        revenue = None
    return CompanyRecord(
        id=company_id,
        group_id=clean_text(row.get("GROUP_ID")),
        revenue=revenue,
        okved_code=clean_text(row.get("MAINOKVED_CODE")),
        okved_name=clean_text(row.get("MAINOKVED_NAME")),
        region=clean_text(row.get("REGION")),
        city=clean_text(row.get("CITY")),
        fts_flag=clean_flag(row.get("FTS_FLAG")),
        fts_countries=clean_text(row.get("FTS_COUNTRY_NAME")),
    )


def _read_companies(path: Path) -> tuple[dict[str, CompanyRecord], int]:
    records: dict[str, CompanyRecord] = {}
    counts: Counter[str] = Counter()
    rows_read = 0
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as source:
        reader = csv.reader(source, delimiter=";")
        header = [cell.strip().upper() for cell in next(reader, [])]
        for cells in reader:
            if not cells or (len(cells) == 1 and not cells[0].strip()):
                continue
            rows_read += 1
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells, strict=True))
            company = _record(row)
            if company is None:
                continue
            counts[company.id] += 1
            records.setdefault(company.id, company)
    for duplicate_id in (key for key, count in counts.items() if count > 1):
        records.pop(duplicate_id, None)  # тот же контракт импорта: неоднозначный id исключается полностью
    return records, rows_read


def _read_payments(
    path: Path, targets: set[str]
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, int], int]:
    amounts: dict[str, dict[str, dict[str, float]]] = {
        target: defaultdict(lambda: {"in": 0.0, "out": 0.0}) for target in targets
    }
    self_payments = Counter()
    rows_read = 0
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as source:
        reader = csv.reader(source, delimiter=";")
        header = [cell.strip().upper() for cell in next(reader, [])]
        index = {name: header.index(name) for name in ("BENEFICIARY", "PAYER", "PAY_AMT")}
        for cells in reader:
            if not cells or (len(cells) == 1 and not cells[0].strip()):
                continue
            rows_read += 1
            if len(cells) != len(header):
                continue
            beneficiary = clean_id(cells[index["BENEFICIARY"]])
            payer = clean_id(cells[index["PAYER"]])
            try:
                amount = float(cells[index["PAY_AMT"]].strip().replace(" ", "").replace(",", "."))
            except (ValueError, AttributeError):
                continue
            # Импорт принимает только валидные id и конечную строго положительную сумму.
            if not beneficiary or not payer or not math.isfinite(amount) or amount <= 0:
                continue
            if payer == beneficiary:
                if payer in targets:
                    self_payments[payer] += 1
                continue
            if payer in targets:
                amounts[payer][beneficiary]["out"] += amount
            if beneficiary in targets:
                amounts[beneficiary][payer]["in"] += amount
    return amounts, dict(self_payments), rows_read


def _countries(raw: str | None) -> list[str]:
    result = []
    for part in (raw or "").split(","):
        country = part.strip()
        if not country:
            continue
        if len(country) > 3:
            country = " ".join(
                word.lower() if word.lower() in {"и", "о"} else word.capitalize() for word in country.split()
            )
        if country not in result:
            result.append(country)
    return result


def _expected(
    company: CompanyRecord, amounts: dict[str, dict[str, float]], records: dict[str, CompanyRecord]
):
    # Независимый oracle: сначала суммы по контрагенту и стороне из платежных CSV, затем те же фильтры,
    # что описаны в profile.aggregate_flows/Flows.external, без вызова этих функций.
    external: dict[str, dict[str, float]] = {}
    excluded_group: set[str] = set()
    excluded_outlier: set[str] = set()
    for cp_id, sides in amounts.items():
        cp = records.get(cp_id)
        kept = {side: amount for side, amount in sides.items() if amount > 0}
        if company.revenue:
            for side in tuple(kept):
                if kept[side] > company.revenue:
                    excluded_outlier.add(cp_id)
                    del kept[side]
        if company.group_id and cp and cp.group_id == company.group_id:
            excluded_group.add(cp_id)
            continue
        if any(kept.values()):
            external[cp_id] = kept

    expected: dict[str, float] = {}
    totals = {side: sum(sides.get(side, 0.0) for sides in external.values()) for side in ("in", "out")}
    for side, noun in (("in", "customer"), ("out", "supplier")):
        total = totals[side]
        if not total:
            continue
        ranked = sorted(
            ((sides.get(side, 0.0), cp_id) for cp_id, sides in external.items() if sides.get(side, 0.0) > 0),
            reverse=True,
        )
        values = [amount for amount, _ in ranked]
        expected[f"top_{noun}_share"] = max(values) / total
        for n in (3, 5):
            expected[f"top{n}_{noun}_share"] = sum(values[:n]) / total
        expected[f"hhi_{noun}"] = sum((amount / total) ** 2 for amount in values)

        unknown_counterparty = sum(amount for amount, cp_id in ranked if cp_id not in records)
        unknown_industry = sum(
            amount
            for amount, cp_id in ranked
            if cp_id not in records or not okved_prefix(records[cp_id].okved_code)
        )
        unknown_region = sum(
            amount
            for amount, cp_id in ranked
            if cp_id not in records or not (records[cp_id].region or records[cp_id].city)
        )
        for key, amount in (
            ("counterparty", unknown_counterparty),
            ("industry", unknown_industry),
            ("region", unknown_region),
        ):
            expected[f"unknown_{key}_{side}_share"] = amount / total

        regions: dict[str, float] = defaultdict(float)
        for amount, cp_id in ranked:
            cp = records.get(cp_id)
            region = cp.region.strip() if cp and cp.region else ""
            if region:
                regions[region] += amount
        if regions:
            top_region = max(regions.items(), key=lambda item: (item[1], item[0]))
            expected[f"top_region_share_{side}"] = top_region[1] / total

        memberships: dict[str, float] = defaultdict(float)
        for amount, cp_id in ranked:
            cp = records.get(cp_id)
            if not cp or cp.fts_flag is not True:
                continue
            for country in _countries(cp.fts_countries):
                memberships[country] += amount
        top_countries = sorted(memberships.items(), key=lambda item: (-item[1], item[0]))[:5]
        for rank, (country, amount) in enumerate(top_countries, 1):
            expected[f"ved_country_{side}_share_{rank}"] = amount / total
            expected[f"ved_country_{side}_label_{rank}"] = country

    diagnostics = {
        "incoming_total": totals["in"],
        "outgoing_total": totals["out"],
        "external_counterparties": len(external),
        "excluded_group_counterparties": len(excluded_group),
        "excluded_outlier_counterparties": len(excluded_outlier),
    }
    return expected, diagnostics


def validate(data_dir: Path) -> int:
    records, company_rows = _read_companies(data_dir / COMPANIES_FILE)
    payments, self_payments, payment_rows = _read_payments(data_dir / PAYMENTS_FILE, set(TARGETS))
    failures = 0
    print(
        f"CSV прочитаны по одному разу: companies rows={company_rows}, "
        f"payments rows={payment_rows}; расчёт — арифметическая сверка, не оценка точности LLM."
    )
    for company_id in TARGETS:
        company = records.get(company_id)
        if company is None:
            print(f"\n{company_id}: нет однозначной записи компании в CSV")
            failures += 1
            continue
        raw_pairs = payments[company_id]
        flow_rows = []
        for cp_id, sides in raw_pairs.items():
            cp = records.get(cp_id)
            for side in ("in", "out"):
                if sides[side] > 0:
                    flow_rows.append(Flow(cp_id, side, sides[side], 1, cp))
        actual = {item.code: item for item in company_indicators(company, flow_rows)}
        expected, info = _expected(company, raw_pairs, records)
        print(
            f"\n{company_id}: revenue={company.revenue!r}, group={company.group_id!r}; "
            f"external cp={info['external_counterparties']}, intra-group excluded="
            f"{info['excluded_group_counterparties']}, outlier excluded="
            f"{info['excluded_outlier_counterparties']}, self-payment rows={self_payments.get(company_id, 0)}"
        )
        print(
            f"  coverage bases: поступления={info['incoming_total']:,.2f} ₽, "
            f"платежи={info['outgoing_total']:,.2f} ₽; неизвестные регион/отрасль/контрагент "
            "остаются в side-знаменателе"
        )
        for code, expected_value in expected.items():
            if "_label_" in code:
                continue
            actual_indicator = actual.get(code)
            actual_value = actual_indicator.value if actual_indicator else None
            delta = abs(actual_value - expected_value) if actual_value is not None else None
            match = delta is not None and delta <= 0.00011
            if not match:
                failures += 1
            label_code = code.replace("_share_", "_label_")
            country = expected.get(label_code)
            suffix = f"; membership={country}" if country else ""
            print(
                f"  {code}: csv={expected_value:.6f}, api={actual_value!r}, "
                f"delta={delta!r} {'OK' if match else 'MISMATCH'}{suffix}"
            )
        if actual.get("top_region_share_in") or actual.get("top_region_share_out"):
            for side in ("in", "out"):
                item = actual.get(f"top_region_share_{side}")
                if item:
                    print(f"  {item.code} details: {item.text}")
        if any(code.startswith("ved_country_") for code in actual):
            print(f"  ВЭД caveat: {COUNTRY_WARNING}")
    print(f"\nИтог: {'OK' if not failures else f'{failures} mismatch(ей)'}.")
    return 0 if not failures else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    default_data = Path(__file__).resolve().parents[1] / "data" / "raw" / "companies"
    parser.add_argument("--data-dir", type=Path, default=default_data, help="каталог исходных CSV")
    args = parser.parse_args()
    return validate(args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
