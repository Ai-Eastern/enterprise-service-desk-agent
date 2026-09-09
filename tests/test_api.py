from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from src.agents.service_desk import ServiceDeskCoordinator
from src.api import app, get_coordinator


class ApiTest(unittest.TestCase):
    def setUp(self) -> None:
        coordinator = ServiceDeskCoordinator(
            knowledge_runner=lambda context, query: {"answer": query, "citations": []},
            status_runner=lambda context, product_id: {
                "product_id": product_id,
                "service_status": "operational",
            },
            ticket_starter=lambda **kwargs: {
                "status": "interrupted",
                "thread_id": kwargs["thread_id"],
            },
            ticket_resumer=lambda **kwargs: {
                "status": "completed",
                "thread_id": kwargs["thread_id"],
            },
        )
        app.dependency_overrides[get_coordinator] = lambda: coordinator
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "version": "1.0.0"})

    def test_ticket_api_returns_approval_required(self) -> None:
        response = self.client.post(
            "/v1/tasks",
            json={
                "thread_id": "task-api-001",
                "user_id": "support-demo",
                "query": "请创建工单",
                "product_id": "smart-assist",
                "idempotency_key": "task-api-001",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["approval_required"])


if __name__ == "__main__":
    unittest.main()
