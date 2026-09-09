"""Deterministic 100-task and 30-fault contract evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Callable, Sequence

from src.agents.service_desk import ServiceDeskCoordinator
from src.api import TaskRequest
from src.auth.context import Role, resolve_user
from src.data_schema import EvaluationCase, EvalTool, PermissionResult


@dataclass(frozen=True)
class FaultCase:
    fault_id: str
    category: str
    variant: int


FAULT_CATEGORIES = (
    "unknown_identity",
    "diagnostic_timeout",
    "permission_denied",
    "interrupt_recovery",
    "duplicate_execution",
    "human_rejection",
)

FAULT_CASES = tuple(
    FaultCase(f"fault-{category}-{variant:02d}", category, variant)
    for category in FAULT_CATEGORIES
    for variant in range(1, 6)
)


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _product_id(question: str) -> str:
    for marker, product_id in (
        ("智能助手", "smart-assist"),
        ("知识中心", "knowledge-hub"),
        ("服务控制台", "service-console"),
    ):
        if marker in question:
            return product_id
    return "smart-assist"


def _expected_route(case: EvaluationCase) -> str:
    if case.expected_tool is EvalTool.GET_SERVICE_STATUS:
        return "diagnostic"
    if case.expected_tool is EvalTool.CREATE_TICKET:
        return "ticket"
    return "knowledge"


def run_compound_cases(
    cases: Sequence[EvaluationCase],
    title_to_doc_id: dict[str, str],
) -> dict[str, object]:
    def knowledge_runner(context, query):
        doc_id = next((value for title, value in title_to_doc_id.items() if title in query), "")
        return {
            "answer": "命中可见知识。" if doc_id else "未命中。",
            "citations": [] if not doc_id else [{"doc_id": doc_id, "source_file": "fixture"}],
        }

    def status_runner(context, product_id):
        return {"product_id": product_id, "service_status": "operational"}

    def ticket_starter(**kwargs):
        context = resolve_user(str(kwargs["user_id"]))
        if context.role is Role.READONLY:
            return {"status": "completed", "permission": "denied"}
        return {"status": "interrupted", "permission": "allowed"}

    coordinator = ServiceDeskCoordinator(
        knowledge_runner=knowledge_runner,
        status_runner=status_runner,
        ticket_starter=ticket_starter,
        ticket_resumer=lambda **kwargs: {"status": "completed"},
    )
    details: list[dict[str, object]] = []
    for case in cases:
        product_id = _product_id(case.question)
        payload = {
            "thread_id": case.query_id,
            "user_id": f"{case.role}-demo",
            "query": case.question,
            "product_id": product_id,
            "idempotency_key": f"eval-{case.query_id}",
        }
        schema_valid = TaskRequest.model_validate(payload).model_dump() == payload
        response = coordinator.handle(**payload)
        route_correct = response["route"] == _expected_route(case)
        approval_expected = (
            case.expected_tool is EvalTool.CREATE_TICKET
            and case.expected_permission_result is PermissionResult.ALLOWED
        )
        approval_correct = response["approval_required"] is approval_expected
        permission_correct = True
        if case.expected_tool is EvalTool.CREATE_TICKET:
            permission_correct = (
                response["result"].get("permission")
                == case.expected_permission_result.value
            )
        citation_correct = True
        if case.expected_tool is EvalTool.NONE:
            citations = response["result"].get("citations", [])
            citation_correct = bool(citations) and citations[0]["doc_id"] in case.expected_doc_ids
        passed = (
            schema_valid
            and route_correct
            and approval_correct
            and permission_correct
            and citation_correct
        )
        details.append(
            {
                "query_id": case.query_id,
                "status": "PASS" if passed else "FAIL",
                "route": response["route"],
                "schema_valid": schema_valid,
                "citation_correct": citation_correct,
                "approval_correct": approval_correct,
                "permission_correct": permission_correct,
            }
        )
    passed_count = sum(item["status"] == "PASS" for item in details)
    return {
        "total": len(details),
        "passed": passed_count,
        "failed": len(details) - passed_count,
        "failed_ids": [item["query_id"] for item in details if item["status"] != "PASS"],
        "details": details,
    }


def _base_coordinator(
    *,
    status_runner: Callable | None = None,
    ticket_starter: Callable | None = None,
    ticket_resumer: Callable | None = None,
) -> ServiceDeskCoordinator:
    return ServiceDeskCoordinator(
        knowledge_runner=lambda context, query: {"answer": query, "citations": []},
        status_runner=status_runner
        or (lambda context, product_id: {"product_id": product_id, "service_status": "operational"}),
        ticket_starter=ticket_starter or (lambda **kwargs: {"status": "interrupted"}),
        ticket_resumer=ticket_resumer or (lambda **kwargs: {"status": "completed"}),
    )


def _run_fault(case: FaultCase) -> bool:
    thread_id = f"fault-{case.variant:02d}"
    if case.category == "unknown_identity":
        try:
            _base_coordinator().handle(
                thread_id=thread_id,
                user_id=f"unknown-{case.variant}",
                query="查询服务状态",
                product_id="smart-assist",
                idempotency_key=thread_id,
            )
        except ValueError:
            return True
        return False

    if case.category == "diagnostic_timeout":
        def timeout(context, product_id):
            raise TimeoutError(f"injected-{case.variant}")

        try:
            _base_coordinator(status_runner=timeout).handle(
                thread_id=thread_id,
                user_id="readonly-demo",
                query="查询服务状态",
                product_id="smart-assist",
                idempotency_key=thread_id,
            )
        except TimeoutError:
            return True
        return False

    if case.category == "permission_denied":
        try:
            _base_coordinator().resume_ticket(
                thread_id=thread_id,
                user_id="readonly-demo",
                approved=True,
            )
        except PermissionError:
            return True
        return False

    if case.category == "interrupt_recovery":
        resume_calls: list[bool] = []

        def start(**kwargs):
            return {"status": "interrupted", "thread_id": kwargs["thread_id"]}

        def resume(**kwargs):
            resume_calls.append(bool(kwargs["approved"]))
            return {"status": "completed", "decision": "approved"}

        coordinator = _base_coordinator(ticket_starter=start, ticket_resumer=resume)
        started = coordinator.handle(
            thread_id=thread_id,
            user_id="support-demo",
            query="创建工单",
            product_id="smart-assist",
            idempotency_key=thread_id,
        )
        resumed = coordinator.resume_ticket(
            thread_id=thread_id,
            user_id="support-demo",
            approved=True,
        )
        return (
            started["approval_required"] is True
            and started["result"]["status"] == "interrupted"
            and resumed["result"]["status"] == "completed"
            and resume_calls == [True]
        )

    if case.category == "duplicate_execution":
        calls = 0
        ticket_id = f"ticket-{case.variant:02d}"

        def resume(**kwargs):
            nonlocal calls
            calls += 1
            return {
                "status": "completed",
                "ticket_id": ticket_id,
                "reused": calls > 1,
            }

        coordinator = _base_coordinator(ticket_resumer=resume)
        first = coordinator.resume_ticket(
            thread_id=thread_id,
            user_id="support-demo",
            approved=True,
        )["result"]
        second = coordinator.resume_ticket(
            thread_id=thread_id,
            user_id="support-demo",
            approved=True,
        )["result"]
        return (
            calls == 2
            and first["ticket_id"] == second["ticket_id"] == ticket_id
            and first["reused"] is False
            and second["reused"] is True
        )

    if case.category == "human_rejection":
        def resume(**kwargs):
            return {
                "status": "completed",
                "decision": "approved" if kwargs["approved"] else "rejected",
                "tickets_created": 1 if kwargs["approved"] else 0,
            }

        result = _base_coordinator(ticket_resumer=resume).resume_ticket(
            thread_id=thread_id,
            user_id="support-demo",
            approved=False,
        )["result"]
        return result == {
            "status": "completed",
            "decision": "rejected",
            "tickets_created": 0,
        }

    raise ValueError(f"未知故障类别：{case.category}")


def run_fault_cases(cases: Sequence[FaultCase] = FAULT_CASES) -> dict[str, object]:
    details = [
        {
            "fault_id": case.fault_id,
            "category": case.category,
            "variant": case.variant,
            "status": "PASS" if _run_fault(case) else "FAIL",
        }
        for case in cases
    ]
    passed_count = sum(item["status"] == "PASS" for item in details)
    return {
        "total": len(details),
        "passed": passed_count,
        "failed": len(details) - passed_count,
        "failed_ids": [item["fault_id"] for item in details if item["status"] != "PASS"],
        "details": details,
    }


def compound_rows(cases: Sequence[EvaluationCase]) -> list[dict[str, object]]:
    return [case.as_dict() for case in cases]


def fault_rows(cases: Sequence[FaultCase] = FAULT_CASES) -> list[dict[str, object]]:
    return [asdict(case) for case in cases]


def build_contract_report(
    compound_cases: Sequence[EvaluationCase],
    title_to_doc_id: dict[str, str],
    fault_cases: Sequence[FaultCase] = FAULT_CASES,
) -> dict[str, object]:
    compound = run_compound_cases(compound_cases, title_to_doc_id)
    faults = run_fault_cases(fault_cases)
    passed = (
        compound["total"] == 100
        and compound["passed"] == 100
        and faults["total"] == 30
        and faults["passed"] == 30
    )
    return {
        "suite": "service-desk-contract-v1",
        "status": "PASS" if passed else "FAIL",
        "compound_dataset_sha256": _sha256(compound_rows(compound_cases)),
        "fault_dataset_sha256": _sha256(fault_rows(fault_cases)),
        "compound": compound,
        "faults": faults,
        "boundary": (
            "Deterministic local contract evidence only: routing, request schema, "
            "citation mapping, approval gates and injected failure handling. It does not "
            "prove semantic retrieval quality, real service integration, production IAM, "
            "capacity, external MCP/A2A interoperability or user acceptance."
        ),
    }
