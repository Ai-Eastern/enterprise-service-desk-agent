"""Run the local A2A 0.3 diagnosis task without an external service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.a2a_poc import build_diagnostic_agent_card, run_diagnostic_task


def main() -> int:
    card = build_diagnostic_agent_card()
    history = run_diagnostic_task(
        user_id="readonly-demo",
        product_id="smart-assist",
        products_path=PROJECT_ROOT / "data" / "products.csv",
    )
    print(
        json.dumps(
            {
                "agent_card": card.model_dump(by_alias=True, exclude_none=True),
                "task_history": [item.model_dump(by_alias=True, exclude_none=True) for item in history],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if history[-1].status.state.value == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
