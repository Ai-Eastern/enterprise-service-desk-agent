"""Generate and run the deterministic public contract evidence pack."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_demo_data import DOCUMENTS, EVALUATION_CASES
from src.contract_suite import (
    FAULT_CASES,
    build_contract_report,
    compound_rows,
    fault_rows,
)


COMPOUND_PATH = PROJECT_ROOT / "tests" / "fixtures" / "compound_tasks.json"
FAULT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "fault_cases.json"
REPORT_PATH = PROJECT_ROOT / "docs" / "evidence" / "contract-report.json"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(part, path)


def main() -> int:
    title_to_doc_id = {document.title: document.doc_id for document in DOCUMENTS}
    report = build_contract_report(EVALUATION_CASES, title_to_doc_id)
    _write_json(COMPOUND_PATH, compound_rows(EVALUATION_CASES))
    _write_json(FAULT_PATH, fault_rows(FAULT_CASES))
    _write_json(REPORT_PATH, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "compound": {
                    "passed": report["compound"]["passed"],
                    "total": report["compound"]["total"],
                },
                "faults": {
                    "passed": report["faults"]["passed"],
                    "total": report["faults"]["total"],
                },
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
