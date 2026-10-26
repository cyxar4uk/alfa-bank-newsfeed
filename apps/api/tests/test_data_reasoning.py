import json
from pathlib import Path

import pytest

from api.agent.checks import evidence_numbers, evidence_problem

CASES = json.loads(
    (Path(__file__).resolve().parents[3] / "scripts" / "data_reasoning_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_evidence_regression_cases(case):
    assert (evidence_problem(case["claim"], case["quote"]) is not None) is case["problem"]


def test_unsupported_number_keeps_its_unit():
    assert evidence_numbers("Выручка — 14 млрд ₽", "Ставка — 14%") == ["14"]
