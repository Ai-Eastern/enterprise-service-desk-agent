from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from a2a.types import TaskState

from src.a2a_poc import build_diagnostic_agent_card, run_diagnostic_task


class A2APocTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.products_path = Path(self.temp_dir.name) / "products.csv"
        with self.products_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("product_id", "name", "service_status", "status_message"),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "product_id": "smart-assist",
                    "name": "智能服务助手",
                    "service_status": "degraded",
                    "status_message": "部分请求延迟",
                }
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_agent_card_declares_one_readonly_diagnosis_skill(self) -> None:
        card = build_diagnostic_agent_card()
        self.assertEqual(card.protocol_version, "0.3.0")
        self.assertEqual([skill.id for skill in card.skills], ["get-service-status"])

    def test_success_returns_submitted_working_completed_and_artifact(self) -> None:
        history = run_diagnostic_task(
            user_id="readonly-demo",
            product_id="smart-assist",
            products_path=self.products_path,
        )
        self.assertEqual(
            [item.status.state for item in history],
            [TaskState.submitted, TaskState.working, TaskState.completed],
        )
        payload = json.loads(history[-1].artifacts[0].parts[0].root.text)
        self.assertEqual(payload["service_status"], "degraded")

    def test_unknown_identity_returns_failed_task(self) -> None:
        history = run_diagnostic_task(
            user_id="unknown-user",
            product_id="smart-assist",
            products_path=self.products_path,
        )
        self.assertEqual(history[-1].status.state, TaskState.failed)
        self.assertIsNotNone(history[-1].status.message)


if __name__ == "__main__":
    unittest.main()
