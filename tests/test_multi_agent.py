from __future__ import annotations

import unittest

from src.agents.service_desk import ServiceDeskCoordinator
from src.infrastructure.production_adapters import build_visibility_filter


class MultiAgentCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.started: list[dict[str, object]] = []
        self.resumed: list[dict[str, object]] = []

        def knowledge(context, query):
            return {"answer": f"knowledge:{context.role.value}:{query}", "citations": []}

        def status(context, product_id):
            return {"product_id": product_id, "service_status": "operational"}

        def start(**kwargs):
            self.started.append(kwargs)
            return {"status": "interrupted", "thread_id": kwargs["thread_id"]}

        def resume(**kwargs):
            self.resumed.append(kwargs)
            return {"status": "completed", "thread_id": kwargs["thread_id"]}

        self.coordinator = ServiceDeskCoordinator(
            knowledge_runner=knowledge,
            status_runner=status,
            ticket_starter=start,
            ticket_resumer=resume,
        )

    def test_diagnostic_path_does_not_require_approval(self) -> None:
        response = self.coordinator.handle(
            thread_id="task-001",
            user_id="readonly-demo",
            query="查询服务状态",
            product_id="smart-assist",
            idempotency_key="task-001",
        )
        self.assertEqual(response["route"], "diagnostic")
        self.assertFalse(response["approval_required"])
        self.assertEqual(response["agents"], ["triage", "diagnostic", "audit"])

    def test_ticket_path_stops_at_human_review(self) -> None:
        response = self.coordinator.handle(
            thread_id="task-002",
            user_id="support-demo",
            query="请提交工单处理故障",
            product_id="smart-assist",
            idempotency_key="task-002",
        )
        self.assertEqual(response["route"], "ticket")
        self.assertTrue(response["approval_required"])
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.resumed, [])

    def test_only_authorized_role_can_resume_ticket(self) -> None:
        response = self.coordinator.resume_ticket(
            thread_id="task-002",
            user_id="support-demo",
            approved=True,
        )
        self.assertEqual(response["result"]["status"], "completed")
        with self.assertRaises(PermissionError):
            self.coordinator.resume_ticket(
                thread_id="task-003",
                user_id="readonly-demo",
                approved=True,
            )

    def test_milvus_filter_accepts_only_closed_visibility_values(self) -> None:
        self.assertEqual(
            build_visibility_filter(["public", "support"]),
            'visibility in ["public", "support"]',
        )
        with self.assertRaises(ValueError):
            build_visibility_filter(["public\" or true"])


if __name__ == "__main__":
    unittest.main()
