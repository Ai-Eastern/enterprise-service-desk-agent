"""Run and persist the local 1,000-task capacity baseline."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.capacity_baseline import run_capacity_baseline


REPORT_PATH = PROJECT_ROOT / "docs" / "evidence" / "capacity-baseline.json"


def main() -> int:
    report = asyncio.run(run_capacity_baseline())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    part = REPORT_PATH.with_name(REPORT_PATH.name + ".part")
    part.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(part, REPORT_PATH)
    print(
        json.dumps(
            {
                "status": report["status"],
                "succeeded": report["results"]["succeeded"],
                "total": report["workload"]["total"],
                "elapsed_seconds": report["results"]["elapsed_seconds"],
                "throughput_tasks_per_second": report["results"]["throughput_tasks_per_second"],
                "p95_ms": report["results"]["latency_ms"]["p95"],
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
