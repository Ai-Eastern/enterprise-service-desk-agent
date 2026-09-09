"""Isolated, deterministic workflow fault evidence for the fictional demo."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from src.config import PROJECT_ROOT, PROJECT_PATHS
from src.agent.workflow import start_workflow
from src.eval.chroma_snapshot import copy_snapshot, file_manifest


WORKFLOW_EVAL_ROOT = PROJECT_PATHS["runtime"] / "eval" / "workflow"


def _run_demo(args: list[str]) -> tuple[dict[str, object], int, int]:
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "demo.py"), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
    return payload, completed.returncode, int(payload.get("process_id", 0))


def _db_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _write_report(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, path)


def run_workflow_faults(*, output_root: Path = WORKFLOW_EVAL_ROOT) -> dict[str, object]:
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    run_dir = Path(output_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    normal_chroma_path = PROJECT_PATHS["runtime"] / "chroma"
    normal_chroma_manifest = file_manifest(normal_chroma_path)
    chroma_path = copy_snapshot(normal_chroma_path, run_dir / "chroma")
    cases: dict[str, dict[str, object]] = {}

    timeout_cp, timeout_tickets = run_dir / "timeout-checkpoints.sqlite", run_dir / "timeout-tickets.sqlite"
    with patch("src.agent.workflow.get_service_status", side_effect=TimeoutError("injected")):
        timeout_result = start_workflow(
            thread_id="eval-tool-timeout",
            user_id="readonly-demo",
            query="请查询智能助手服务状态",
            product_id="smart-assist",
            idempotency_key="eval-timeout-key",
            checkpoint_path=timeout_cp,
            tickets_path=timeout_tickets,
            chroma_path=chroma_path,
        )
    timeout_error = timeout_result.get("tool_error", {})
    cases["tool_timeout"] = {
        "status": "PASS"
        if timeout_result.get("status") == "completed"
        and "interrupt" not in timeout_result
        and timeout_error.get("code") == "timeout"
        and not timeout_tickets.exists()
        else "FAIL",
        "result": timeout_error.get("code", "missing"),
        "waited_seconds": 0,
        "side_effect": timeout_tickets.exists(),
        "execution": "start_workflow.execute_tool",
    }

    denied_cp, denied_tickets = run_dir / "permission-checkpoints.sqlite", run_dir / "permission-tickets.sqlite"
    denied, code, pid = _run_demo([
        "start", "--thread-id", "eval-permission-denied", "--user-id", "readonly-demo",
        "--query", "请为智能助手创建工单", "--product-id", "smart-assist", "--idempotency-key", "eval-permission-key",
        "--checkpoint-path", str(denied_cp), "--tickets-path", str(denied_tickets), "--chroma-path", str(chroma_path),
    ])
    cases["permission_denied"] = {"status": "PASS" if code == 0 and pid > 0 and denied.get("status") == "completed" and "无权" in str(denied.get("answer")) and "interrupt" not in denied and not denied_tickets.exists() else "FAIL", "process_ids": [pid], "tickets_created": denied_tickets.exists()}

    replay_tickets = run_dir / "replay-tickets.sqlite"
    replay_results: list[dict[str, object]] = []
    replay_pids: list[int] = []
    replay_start_codes: list[int] = []
    replay_resume_codes: list[int] = []
    replay_starts: list[dict[str, object]] = []
    for thread in ("eval-replay-one", "eval-replay-two"):
        cp = run_dir / f"{thread}.sqlite"
        started_result, start_code, start_pid = _run_demo([
            "start", "--thread-id", thread, "--user-id", "support-demo", "--query", "请为智能助手创建工单",
            "--product-id", "smart-assist", "--idempotency-key", "eval-replay-key", "--checkpoint-path", str(cp),
            "--tickets-path", str(replay_tickets), "--chroma-path", str(chroma_path),
        ])
        resumed, resume_code, resume_pid = _run_demo(["resume", "--thread-id", thread, "--decision", "approve", "--checkpoint-path", str(cp)])
        replay_starts.append(started_result)
        replay_start_codes.append(start_code)
        replay_resume_codes.append(resume_code)
        replay_results.append(resumed)
        replay_pids.extend([start_pid, resume_pid])
    same_ticket = len({str(result.get("tool_result", {}).get("ticket_id")) for result in replay_results}) == 1
    cases["idempotency_replay"] = {"status": "PASS" if all(code == 0 for code in replay_start_codes + replay_resume_codes) and all(start.get("status") == "interrupted" for start in replay_starts) and all(result.get("status") == "completed" for result in replay_results) and all(pid > 0 for pid in replay_pids) and len(set(replay_pids)) == 4 and same_ticket and replay_results[0].get("tool_result", {}).get("reused") is False and replay_results[1].get("tool_result", {}).get("reused") is True and _db_count(replay_tickets, "tickets") == 1 else "FAIL", "process_ids": replay_pids, "database_rows": _db_count(replay_tickets, "tickets")}

    reject_cp, reject_tickets = run_dir / "reject-checkpoints.sqlite", run_dir / "reject-tickets.sqlite"
    reject_start, c1, p1 = _run_demo([
        "start", "--thread-id", "eval-human-reject", "--user-id", "support-demo", "--query", "请为智能助手创建工单",
        "--product-id", "smart-assist", "--idempotency-key", "eval-reject-key", "--checkpoint-path", str(reject_cp),
        "--tickets-path", str(reject_tickets), "--chroma-path", str(chroma_path),
    ])
    reject_resume, c2, p2 = _run_demo(["resume", "--thread-id", "eval-human-reject", "--decision", "reject", "--checkpoint-path", str(reject_cp)])
    cases["human_rejection"] = {"status": "PASS" if c1 == c2 == 0 and p1 > 0 and p2 > 0 and p1 != p2 and reject_start.get("status") == "interrupted" and reject_resume.get("status") == "completed" and not reject_tickets.exists() else "FAIL", "process_ids": [p1, p2], "tickets_created": reject_tickets.exists()}

    resume_cp, resume_tickets = run_dir / "restart-checkpoints.sqlite", run_dir / "restart-tickets.sqlite"
    paused, c1, p1 = _run_demo([
        "start", "--thread-id", "eval-process-restart", "--user-id", "support-demo", "--query", "请为智能助手创建工单",
        "--product-id", "smart-assist", "--idempotency-key", "eval-restart-key", "--checkpoint-path", str(resume_cp),
        "--tickets-path", str(resume_tickets), "--chroma-path", str(chroma_path),
    ])
    restart_no_ticket_before = not resume_tickets.exists()
    resumed, c2, p2 = _run_demo(["resume", "--thread-id", "eval-process-restart", "--decision", "approve", "--checkpoint-path", str(resume_cp)])
    restart_pass = c1 == c2 == 0 and p1 > 0 and p2 > 0 and p1 != p2 and paused.get("status") == "interrupted" and resumed.get("status") == "completed" and restart_no_ticket_before and resume_cp.exists() and resume_tickets.exists() and _db_count(resume_tickets, "tickets") == 1
    cases["process_restart_resume"] = {"status": "PASS" if restart_pass else "FAIL", "process_ids": [p1, p2], "checkpoint_exists_after_pause": resume_cp.exists(), "database_rows": _db_count(resume_tickets, "tickets") if resume_tickets.exists() else 0}

    report = {
        "run_id": run_id,
        "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cases": cases,
        "normal_chroma_unchanged": file_manifest(normal_chroma_path) == normal_chroma_manifest,
        "boundary": "Workflow fault evidence is excluded from retrieval Hit@5/MRR; normal tickets/checkpoints are unused; normal Chroma is copied before execution and the copied snapshot is used; the normal Chroma hash manifest remains unchanged during this accepted run.",
    }
    _write_report(run_dir / "report.json", report)
    return report
