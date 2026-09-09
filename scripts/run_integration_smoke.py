"""Exercise the real local PostgreSQL, Redis and Milvus adapters."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pymilvus import MilvusClient

from src.data_schema import Visibility
from src.infrastructure.production_adapters import (
    MilvusKnowledgeRepository,
    PostgresIdempotencyRepository,
    RedisTaskStateRepository,
)


REPORT_PATH = PROJECT_ROOT / "docs" / "evidence" / "integration-report.json"
POSTGRES_DSN = os.getenv(
    "DEMO_POSTGRES_DSN",
    "postgresql://demo:demo-only-password@127.0.0.1:15432/demo",
)
REDIS_URL = os.getenv("DEMO_REDIS_URL", "redis://127.0.0.1:16379/0")
MILVUS_URI = os.getenv("DEMO_MILVUS_URI", "http://127.0.0.1:19530")


def _postgres_case() -> dict[str, object]:
    import psycopg

    with psycopg.connect(POSTGRES_DSN) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS ticket_idempotency ("
            "idempotency_key TEXT PRIMARY KEY, ticket_id TEXT NOT NULL)"
        )
    key = f"integration-{uuid.uuid4().hex}"
    repository = PostgresIdempotencyRepository(POSTGRES_DSN)
    first = repository.reserve(key, "ticket-first")
    second = repository.reserve(key, "ticket-second")
    return {
        "status": "PASS" if first == second == "ticket-first" else "FAIL",
        "assertion": "same idempotency key returns the original ticket id",
    }


def _redis_case() -> dict[str, object]:
    task_id = f"integration-{uuid.uuid4().hex}"
    payload = {"status": "working", "attempt": 1}
    repository = RedisTaskStateRepository(REDIS_URL, ttl_seconds=60)
    repository.save(task_id, payload)
    loaded = repository.load(task_id)
    return {
        "status": "PASS" if loaded == payload else "FAIL",
        "assertion": "task state survives a Redis round trip with TTL",
    }


def _milvus_case() -> dict[str, object]:
    collection = f"integration_{uuid.uuid4().hex[:12]}"
    client = MilvusClient(uri=MILVUS_URI)
    try:
        client.create_collection(collection_name=collection, dimension=2, metric_type="COSINE")
        client.insert(
            collection_name=collection,
            data=[
                {
                    "id": 1,
                    "vector": [1.0, 0.0],
                    "doc_id": "public-doc",
                    "title": "公开资料",
                    "source_file": "fixture",
                    "visibility": "public",
                    "text": "公开内容",
                },
                {
                    "id": 2,
                    "vector": [1.0, 0.0],
                    "doc_id": "admin-doc",
                    "title": "管理员资料",
                    "source_file": "fixture",
                    "visibility": "admin",
                    "text": "管理员内容",
                },
            ],
        )
        client.flush(collection_name=collection)
        results = MilvusKnowledgeRepository(MILVUS_URI, collection).search(
            [1.0, 0.0],
            [Visibility.PUBLIC],
            limit=5,
        )
        doc_ids = [str(item["entity"]["doc_id"]) for item in results]
        return {
            "status": "PASS" if doc_ids == ["public-doc"] else "FAIL",
            "assertion": "Milvus query-time visibility filter returns only public data",
            "returned_doc_ids": doc_ids,
        }
    finally:
        if client.has_collection(collection_name=collection):
            client.drop_collection(collection_name=collection)


def main() -> int:
    cases: dict[str, dict[str, object]] = {}
    for name, runner in (
        ("postgres_idempotency", _postgres_case),
        ("redis_task_state", _redis_case),
        ("milvus_visibility", _milvus_case),
    ):
        try:
            cases[name] = runner()
        except Exception as exc:
            cases[name] = {
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    passed = sum(case["status"] == "PASS" for case in cases.values())
    report = {
        "suite": "local-container-integration-v1",
        "status": "PASS" if passed == len(cases) else "FAIL",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("pymilvus", "psycopg", "redis")
        },
        "cases": cases,
        "summary": {"passed": passed, "total": len(cases)},
        "boundary": (
            "Real local Docker containers and real client libraries. This proves only one "
            "bounded adapter round trip per service; it does not prove production topology, "
            "HA, backup, security hardening, failover, sustained load or external systems."
        ),
    }
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
            {"status": report["status"], **report["summary"], "report": str(REPORT_PATH)},
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
