"""Run the small synthetic regression set; this is not a real-world accuracy estimate."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "ingest" / "src"))

from api.agent.checks import evidence_problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "scripts" / "data_reasoning_cases.json")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    failed = []
    for case in cases:
        observed = evidence_problem(case["claim"], case["quote"]) is not None
        if observed != case["problem"]:
            failed.append(
                {"id": case["id"], "expected_problem": case["problem"], "observed_problem": observed}
            )
    passed = len(cases) - len(failed)
    print(
        json.dumps(
            {
                "suite": "synthetic regression",
                "checks": len(cases),
                "passed": passed,
                "failed": len(failed),
                "accuracy_claim": False,
                "failures": failed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
