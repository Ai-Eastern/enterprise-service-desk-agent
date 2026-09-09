"""Local ASGI capacity baseline with deterministic in-memory adapters."""

from __future__ import annotations

import asyncio
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import httpx

from src.agents.service_desk import ServiceDeskCoordinator
from src.api import app, get_coordinator


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, (len(ordered) * percentile + 99) // 100 - 1)
    return round(ordered[index], 3)


def _request(index: int) -> tuple[dict[str, object], str, bool]:
    bucket = index % 10
    if bucket < 4:
        route, query, user_id, approval = "knowledge", "请说明演示使用规则", "readonly-demo", False
    elif bucket < 7:
        route, query, user_id, approval = "diagnostic", "查询服务状态", "readonly-demo", False
    else:
        route, query, user_id, approval = "ticket", "请创建工单", "support-demo", True
    task_id = f"capacity-{index:05d}"
    return (
        {
            "thread_id": task_id,
            "user_id": user_id,
            "query": query,
            "product_id": "smart-assist",
            "idempotency_key": task_id,
        },
        route,
        approval,
    )


async def run_capacity_baseline(total: int = 1000, concurrency: int = 20) -> dict[str, object]:
    if total < 1 or concurrency < 1:
        raise ValueError("total 和 concurrency 必须为正整数。")

    coordinator = ServiceDeskCoordinator(
        knowledge_runner=lambda context, query: {
            "answer": "本地容量基线回答。",
            "citations": [{"doc_id": "capacity-fixture", "source_file": "in-memory"}],
        },
        status_runner=lambda context, product_id: {
            "product_id": product_id,
            "service_status": "operational",
        },
        ticket_starter=lambda **kwargs: {
            "status": "interrupted",
            "thread_id": kwargs["thread_id"],
        },
        ticket_resumer=lambda **kwargs: {"status": "completed"},
    )
    app.dependency_overrides[get_coordinator] = lambda: coordinator
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    routes: Counter[str] = Counter()
    failures: list[dict[str, object]] = []

    async def send(client: httpx.AsyncClient, index: int) -> None:
        payload, expected_route, expected_approval = _request(index)
        async with semaphore:
            started = time.perf_counter()
            response = await client.post("/v1/tasks", json=payload)
            latencies.append((time.perf_counter() - started) * 1000)
        routes[expected_route] += 1
        body = response.json() if response.status_code == 200 else {}
        if (
            response.status_code != 200
            or body.get("route") != expected_route
            or body.get("approval_required") is not expected_approval
        ):
            failures.append(
                {
                    "index": index,
                    "status_code": response.status_code,
                    "expected_route": expected_route,
                    "actual_route": body.get("route"),
                }
            )

    transport = httpx.ASGITransport(app=app)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://capacity.local") as client:
            await asyncio.gather(*(send(client, index) for index in range(total)))
    finally:
        app.dependency_overrides.clear()
    elapsed = time.perf_counter() - started
    succeeded = total - len(failures)
    return {
        "suite": "local-asgi-capacity-v1",
        "status": "PASS" if succeeded == total else "FAIL",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "workload": {
            "total": total,
            "concurrency": concurrency,
            "routes": dict(sorted(routes.items())),
        },
        "results": {
            "succeeded": succeeded,
            "failed": len(failures),
            "elapsed_seconds": round(elapsed, 3),
            "throughput_tasks_per_second": round(total / elapsed, 2),
            "latency_ms": {
                "mean": round(statistics.fmean(latencies), 3),
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "p99": _percentile(latencies, 99),
                "max": round(max(latencies), 3),
            },
            "failure_samples": failures[:10],
        },
        "boundary": (
            "Local in-process ASGI simulation with deterministic in-memory adapters. "
            "It validates 1,000 mixed request contracts under bounded concurrency, not daily "
            "production traffic, network/server capacity, real RAG latency, Milvus/PostgreSQL/Redis, "
            "production IAM, external services or user acceptance."
        ),
    }
