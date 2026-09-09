"""Run one local multi-agent service-status request."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.service_desk import ServiceDeskCoordinator


def main() -> int:
    response = ServiceDeskCoordinator().handle(
        thread_id="multi-agent-demo-001",
        user_id="readonly-demo",
        query="查询 smart-assist 服务状态",
        product_id="smart-assist",
        idempotency_key="multi-agent-demo-001",
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
