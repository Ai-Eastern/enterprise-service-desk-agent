from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.generate_demo_data import generate
from src.auth.context import Role, UserContext, resolve_user
from src.data_schema import DEMO_DATA_CLASSIFICATION, Visibility
from src.tools.platform_tools import (
    ToolError,
    ToolErrorCode,
    create_ticket,
    get_service_status,
)


class V01BusinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.products_path = root / "products.csv"
        with self.products_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("product_id", "name", "service_status", "status_message"),
            )
            writer.writeheader()
            writer.writerow(
                {
                    "product_id": "smart-assist",
                    "name": "虚构智能服务",
                    "service_status": "operational",
                    "status_message": "虚构演示服务正常",
                }
            )
            writer.writerow(
                {
                    "product_id": "knowledge-hub",
                    "name": "虚构知识中心",
                    "service_status": "degraded",
                    "status_message": "虚构演示服务降级",
                }
            )
        self.db_path = root / "tickets.sqlite"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_readonly_status_query_has_no_ticket_side_effect(self) -> None:
        result = get_service_status(
            resolve_user("readonly-demo"),
            "smart-assist",
            products_path=self.products_path,
        )
        self.assertEqual(result["service_status"], "operational")
        self.assertFalse(self.db_path.exists())

    def test_readonly_and_forged_context_are_denied_before_write(self) -> None:
        payload = {
            "product_id": "smart-assist",
            "summary": "需要人工处理",
            "idempotency_key": "case-001",
        }
        forged = UserContext(
            user_id="support-demo",
            role=Role.ADMIN,
            allowed_visibilities=(Visibility.PUBLIC, Visibility.SUPPORT, Visibility.ADMIN),
        )
        for context in (resolve_user("readonly-demo"), forged):
            with self.subTest(context=context.user_id):
                with self.assertRaises(ToolError) as raised:
                    create_ticket(
                        context,
                        payload,
                        db_path=self.db_path,
                        products_path=self.products_path,
                    )
                self.assertEqual(raised.exception.code, ToolErrorCode.PERMISSION_DENIED)
        self.assertFalse(self.db_path.exists())

    def test_create_and_exact_retry_are_idempotent_and_audited(self) -> None:
        context = resolve_user("support-demo")
        payload = {
            "product_id": "smart-assist",
            "summary": "记录虚构故障",
            "idempotency_key": "case-002",
        }
        first = create_ticket(context, payload, db_path=self.db_path, products_path=self.products_path)
        second = create_ticket(context, payload, db_path=self.db_path, products_path=self.products_path)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["ticket_id"], second["ticket_id"])
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT actor_user_id, actor_role, action, outcome, resource_type, "
                "resource_id, product_id, idempotency_key FROM audit_events ORDER BY rowid"
            ).fetchall()
            count = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual([row[3] for row in rows], ["created", "reused"])
        self.assertTrue(all(row[0] == "support-demo" for row in rows))
        self.assertTrue(all(row[1] == "support" and row[2] == "create_ticket" for row in rows))
        self.assertTrue(all(row[4] == "ticket" and row[5] == first["ticket_id"] for row in rows))
        self.assertTrue(all(row[6:] == ("smart-assist", "case-002") for row in rows))

    def test_changed_payload_or_actor_fails_closed_without_new_ticket(self) -> None:
        support = resolve_user("support-demo")
        payload = {
            "product_id": "smart-assist",
            "summary": "原始摘要",
            "idempotency_key": "case-003",
        }
        create_ticket(support, payload, db_path=self.db_path, products_path=self.products_path)
        variants = (
            (support, {**payload, "summary": "不同摘要"}),
            (support, {**payload, "product_id": "knowledge-hub"}),
            (resolve_user("admin-demo"), payload),
        )
        for context, variant in variants:
            with self.subTest(user_id=context.user_id, payload=variant):
                with self.assertRaises(ToolError) as raised:
                    create_ticket(
                        context,
                        variant,
                        db_path=self.db_path,
                        products_path=self.products_path,
                    )
                self.assertEqual(raised.exception.code, ToolErrorCode.IDEMPOTENCY_CONFLICT)
        with sqlite3.connect(self.db_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            outcomes = connection.execute(
                "SELECT outcome FROM audit_events ORDER BY rowid"
            ).fetchall()
        self.assertEqual(count, 1)
        self.assertEqual(
            [row[0] for row in outcomes],
            ["created", "idempotency_conflict", "idempotency_conflict", "idempotency_conflict"],
        )

    def test_generator_is_deterministic_and_marks_demo_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = generate(Path(first_dir))
            second = generate(Path(second_dir))
            first_files = sorted(path.relative_to(first_dir) for path in first)
            second_files = sorted(path.relative_to(second_dir) for path in second)
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(
                    (Path(first_dir) / relative).read_bytes(),
                    (Path(second_dir) / relative).read_bytes(),
                )
            with (Path(first_dir) / "identities.csv").open(encoding="utf-8", newline="") as stream:
                identities = list(csv.DictReader(stream))
            with (Path(first_dir) / "audit.csv").open(encoding="utf-8", newline="") as stream:
                audit = list(csv.DictReader(stream))
            with (Path(first_dir) / "tickets.csv").open(encoding="utf-8", newline="") as stream:
                tickets_header = next(csv.reader(stream))
            self.assertEqual(len(identities), 3)
            self.assertEqual({row["data_classification"] for row in identities}, {DEMO_DATA_CLASSIFICATION})
            self.assertEqual(audit, [])
            self.assertIn("user_id", tickets_header)
            self.assertEqual((Path(first_dir) / "audit.csv").read_text(encoding="utf-8").splitlines()[0].split(",")[-1], "data_classification")


if __name__ == "__main__":
    unittest.main()
