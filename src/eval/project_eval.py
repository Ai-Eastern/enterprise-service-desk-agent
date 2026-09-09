"""Project evaluation: reuse the production retrieval, decision and permission rules."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from src.config import PROJECT_ROOT, PROJECT_PATHS
from src.data_schema import EvaluationCase, EvalTool, PermissionResult
from src.auth.context import resolve_user
from src.agent.workflow import _decide_tool_node
from src.tools.platform_tools import TOOL_SPECS
from src.retrieval.chroma_store import CHROMA_PATH, MODEL_REVISION, search
from src.eval.chroma_snapshot import copy_snapshot, file_manifest


PROJECT_EVAL_PATH = PROJECT_ROOT / "data" / "eval" / "project_eval.json"
PROJECT_EVAL_ROOT = PROJECT_PATHS["runtime"] / "eval" / "project"
EXPECTED_CASE_COUNT = 60
EXPECTED_KNOWLEDGE_COUNT = 24
EXPECTED_TOOL_COUNT = 36


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, root: Path = PROJECT_ROOT) -> Path:
    resolved, base = path.resolve(), root.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("评测路径必须位于项目根目录内。")
    return resolved


def load_project_cases(path: Path = PROJECT_EVAL_PATH) -> tuple[EvaluationCase, ...]:
    path = _inside(Path(path))
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("项目评测数据无法读取。") from exc
    if not isinstance(rows, list):
        raise ValueError("项目评测数据必须是数组。")
    cases = tuple(
        EvaluationCase(
            row.get("query_id"),
            row.get("question"),
            row.get("role"),
            tuple(row.get("expected_doc_ids", ())),
            row.get("expected_tool"),
            row.get("expected_permission_result"),
        )
        for row in rows
        if isinstance(row, dict)
    )
    if len(cases) != len(rows):
        raise ValueError("项目评测数据每项必须是对象。")
    validate_project_cases(cases)
    return cases


def validate_project_cases(cases: Sequence[EvaluationCase]) -> None:
    if len(cases) != EXPECTED_CASE_COUNT:
        raise ValueError("项目评测必须包含 60 条用例。")
    ids = [case.query_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("项目评测 query_id 不得重复。")
    knowledge = [case for case in cases if case.expected_tool is EvalTool.NONE]
    tools = [case for case in cases if case.expected_tool is not EvalTool.NONE]
    if len(knowledge) != EXPECTED_KNOWLEDGE_COUNT or len(tools) != EXPECTED_TOOL_COUNT:
        raise ValueError("项目评测知识与工具用例数量不符合合同。")


def _dedupe(ranked: Sequence[str], top_k: int = 5) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for doc_id in ranked:
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc_id)
        if len(result) == top_k:
            break
    return result


def score_knowledge(cases: Sequence[EvaluationCase], retrievals: Mapping[str, Sequence[str]]) -> dict[str, object]:
    knowledge = [case for case in cases if case.expected_tool is EvalTool.NONE]
    details: list[dict[str, object]] = []
    for case in knowledge:
        ranked = _dedupe(retrievals.get(case.query_id, ()))
        expected = set(case.expected_doc_ids)
        rank = next((index for index, doc_id in enumerate(ranked, 1) if doc_id in expected), None)
        details.append({"query_id": case.query_id, "ranked_doc_ids": ranked, "first_hit_rank": rank})
    hits = sum(item["first_hit_rank"] is not None for item in details)
    reciprocal = sum(0.0 if item["first_hit_rank"] is None else 1.0 / int(item["first_hit_rank"]) for item in details)
    return {
        "total": len(details),
        "hit_queries": hits,
        "hit_at_5": round(hits / len(details), 8) if details else 0.0,
        "mrr": round(reciprocal / len(details), 8) if details else 0.0,
        "failed_query_ids": [item["query_id"] for item in details if item["first_hit_rank"] is None],
        "queries": details,
    }


def score_tool_and_permission(
    case: EvaluationCase,
    actual_tool: str,
    actual_permission: str,
    schema_valid: bool,
) -> dict[str, bool]:
    return {
        "tool_correct": actual_tool == case.expected_tool.value,
        "permission_correct": actual_permission == case.expected_permission_result.value,
        "schema_valid": bool(schema_valid),
    }


def build_project_report(
    cases: Sequence[EvaluationCase],
    retrievals: Mapping[str, Sequence[str]],
    actual_tools: Mapping[str, str],
    actual_permissions: Mapping[str, str],
    schemas: Mapping[str, bool],
    *,
    data_sha256: str = "",
    started_at_utc: str = "",
    elapsed_seconds: float = 0.0,
) -> dict[str, object]:
    knowledge = score_knowledge(cases, retrievals)
    tool_cases = [case for case in cases if case.expected_tool is not EvalTool.NONE]
    tool_scores = {
        case.query_id: score_tool_and_permission(
            case,
            actual_tools.get(case.query_id, "none"),
            actual_permissions.get(case.query_id, "denied"),
            schemas.get(case.query_id, False),
        )
        for case in cases
    }
    tool_correct = sum(tool_scores[case.query_id]["tool_correct"] for case in cases)
    permission_correct = sum(tool_scores[case.query_id]["permission_correct"] for case in cases)
    schema_valid = sum(tool_scores[case.query_id]["schema_valid"] for case in tool_cases)
    return {
        "run_id": uuid.uuid4().hex[:12],
        "started_at_utc": started_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "data_sha256": data_sha256,
        "model_revision": MODEL_REVISION,
        "collection": "zhida-knowledge-v1",
        "total_cases": len(cases),
        "knowledge_total": knowledge["total"],
        "knowledge_hit_queries": knowledge["hit_queries"],
        "knowledge_hit_at_5": knowledge["hit_at_5"],
        "knowledge_mrr": knowledge["mrr"],
        "knowledge_failed_query_ids": knowledge["failed_query_ids"],
        "tool_selection_total": len(cases),
        "tool_selection_correct": tool_correct,
        "tool_selection_accuracy": round(tool_correct / len(cases), 8) if cases else 0.0,
        "permission_total": len(cases),
        "permission_correct": permission_correct,
        "permission_accuracy": round(permission_correct / len(cases), 8) if cases else 0.0,
        "tool_schema_total": len(tool_cases),
        "tool_schema_valid": schema_valid,
        "tool_schema_accuracy": round(schema_valid / len(tool_cases), 8) if tool_cases else 0.0,
        "tool_selection_failed_query_ids": [case.query_id for case in cases if not tool_scores[case.query_id]["tool_correct"]],
        "permission_failed_query_ids": [case.query_id for case in cases if not tool_scores[case.query_id]["permission_correct"]],
        "tool_schema_failed_query_ids": [case.query_id for case in tool_cases if not tool_scores[case.query_id]["schema_valid"]],
        "boundary": "Knowledge Hit@5/MRR denominator is 24 knowledge cases; tool and permission metrics use all 60; schema metrics use 36 tool cases. No create_ticket or human approval is executed.",
    }


def _product_id(question: str) -> str:
    for marker, product_id in (("智能助手", "smart-assist"), ("知识中心", "knowledge-hub"), ("服务控制台", "service-console")):
        if marker in question:
            return product_id
    raise ValueError("评测问题未包含虚构产品。")


def _decision(case: EvaluationCase) -> tuple[str, str, bool]:
    user_id = f"{case.role}-demo"
    context = resolve_user(user_id)
    state = {
        "query": case.question,
        # The production decision rule only inspects query intent; knowledge
        # cases may omit a product, so use a fictional valid placeholder.
        "product_id": _product_id(case.question) if any(marker in case.question for marker in ("智能助手", "知识中心", "服务控制台")) else "smart-assist",
        "idempotency_key": f"eval-{case.query_id}",
    }
    decided = _decide_tool_node(state)  # reuse the production deterministic decision rule
    tool_name = str(decided["tool_name"])
    if not tool_name:
        return "none", "allowed", True
    spec = TOOL_SPECS[tool_name]
    allowed = context.role in spec.allowed_roles
    args = decided["tool_args"]
    try:
        spec.input_model.model_validate(args)
        schema_valid = True
    except Exception:
        schema_valid = False
    return tool_name, "allowed" if allowed else "denied", schema_valid


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, path)


def run_project_evaluation(
    *,
    cases_path: Path = PROJECT_EVAL_PATH,
    chroma_path: Path = CHROMA_PATH,
    output_root: Path = PROJECT_EVAL_ROOT,
) -> dict[str, object]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cases = load_project_cases(cases_path)
    data_sha = _sha256(_inside(Path(cases_path)))
    run_id = uuid.uuid4().hex[:12]
    run_dir = _inside(Path(output_root)) / run_id
    normal_chroma_path = Path(chroma_path).resolve()
    normal_chroma_manifest = file_manifest(normal_chroma_path)
    snapshot_path = copy_snapshot(normal_chroma_path, run_dir / "chroma")
    retrievals: dict[str, Sequence[str]] = {}
    actual_tools: dict[str, str] = {}
    actual_permissions: dict[str, str] = {}
    schemas: dict[str, bool] = {}
    for case in cases:
        if case.expected_tool is EvalTool.NONE:
            context = resolve_user(f"{case.role}-demo")
            retrievals[case.query_id] = [result.doc_id for result in search(case.question, context.allowed_visibilities, 5, snapshot_path)]
        actual_tools[case.query_id], actual_permissions[case.query_id], schemas[case.query_id] = _decision(case)
    normal_unchanged = file_manifest(normal_chroma_path) == normal_chroma_manifest
    report = build_project_report(
        cases, retrievals, actual_tools, actual_permissions, schemas,
        data_sha256=data_sha, started_at_utc=started_at, elapsed_seconds=time.perf_counter() - started,
    )
    report["run_id"] = run_id
    report["normal_chroma_unchanged"] = normal_unchanged
    report["boundary"] = "Knowledge Hit@5/MRR denominator is 24 knowledge cases; tool and permission metrics use all 60; schema metrics use 36 tool cases. Normal Chroma is copied to a run-isolated snapshot; no create_ticket or human approval is executed."
    report_path = run_dir / "report.json"
    _write_json(report_path, report)
    return report
