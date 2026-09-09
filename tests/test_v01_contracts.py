from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.auth.context import resolve_user
from src.tools.platform_tools import ToolError, ToolErrorCode, get_service_status


class V01ContractsTest(unittest.TestCase):
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
                    "service_status": "online",
                    "status_message": "服务正常",
                }
            )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_readonly_user_can_query_service_status(self) -> None:
        result = get_service_status(
            resolve_user("readonly-demo"),
            "smart-assist",
            products_path=self.products_path,
        )
        self.assertEqual(result["service_status"], "online")

    def test_unknown_identity_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            resolve_user("unknown-user")

    def test_readonly_user_cannot_create_ticket(self) -> None:
        from src.tools.platform_tools import create_ticket

        with self.assertRaises(ToolError) as raised:
            create_ticket(
                resolve_user("readonly-demo"),
                {
                    "product_id": "smart-assist",
                    "summary": "需要人工处理",
                    "idempotency_key": "case-001",
                },
                db_path=Path(self.temp_dir.name) / "tickets.sqlite",
                products_path=self.products_path,
            )
        self.assertEqual(raised.exception.code, ToolErrorCode.PERMISSION_DENIED)


if __name__ == "__main__":
    unittest.main()
