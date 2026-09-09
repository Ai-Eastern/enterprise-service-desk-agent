"""Small, explicit multi-agent coordinator for the service-desk business flow."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from opentelemetry import trace

from src.auth.context import Role, UserContext, resolve_user
from src.config import PROJECT_PATHS
from src.tools.platform_tools import get_service_status


KnowledgeRunner = Callable[[UserContext, str], dict[str, object]]
StatusRunner = Callable[[UserContext, str], dict[str, str]]
TicketStarter = Callable[..., dict[str, object]]
TicketResumer = Callable[..., dict[str, object]]


@dataclass(frozen=True)
class AuditEvent:
    agent: str
    action: str
    status: str
    elapsed_ms: float


class TriageAgent:
    name = "triage"

    @staticmethod
    def route(query: str) -> str:
        normalized = query.strip()
        if normalized.startswith(("请说明", "请结合")):
            return "knowledge"
        if any(marker in normalized for marker in ("创建工单", "提交工单", "报修")):
            return "ticket"
        if any(marker in normalized for marker in ("服务状态", "故障", "异常", "不可用")):
            return "diagnostic"
        return "knowledge"


class AuditAgent:
    name = "audit"

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, agent: str, action: str, status: str, started_at: float) -> None:
        self._events.append(
            AuditEvent(
                agent=agent,
                action=action,
                status=status,
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
        )

    def export(self) -> list[dict[str, object]]:
        return [asdict(event) for event in self._events]


class ServiceDeskCoordinator:
    """Coordinate specialized agents while keeping ticket writes behind HITL."""

    def __init__(
        self,
        *,
        knowledge_runner: KnowledgeRunner | None = None,
        status_runner: StatusRunner | None = None,
        ticket_starter: TicketStarter | None = None,
        ticket_resumer: TicketResumer | None = None,
        chroma_path: Path | None = None,
    ) -> None:
        self._knowledge_runner = knowledge_runner or self._default_knowledge
        self._status_runner = status_runner or get_service_status
        self._ticket_starter = ticket_starter or self._default_ticket_start
        self._ticket_resumer = ticket_resumer or self._default_ticket_resume
        self._chroma_path = chroma_path or PROJECT_PATHS["runtime"] / "chroma"
        self._tracer = trace.get_tracer("enterprise-service-desk-agent")

    def _default_knowledge(self, context: UserContext, query: str) -> dict[str, object]:
        from src.retrieval.chroma_store import search

        results = search(query, context.allowed_visibilities, 5, self._chroma_path)
        if not results:
            return {"answer": "未检索到可见知识。", "citations": []}
        first = results[0]
        return {
            "answer": f"根据《{first.title}》：{first.text[:160]}",
            "citations": [
                {"doc_id": item.doc_id, "source_file": item.source_file}
                for item in results
            ],
        }

    @staticmethod
    def _default_ticket_start(**kwargs: object) -> dict[str, object]:
        from src.agent.workflow import start_workflow

        return start_workflow(**kwargs)

    @staticmethod
    def _default_ticket_resume(**kwargs: object) -> dict[str, object]:
        from src.agent.workflow import resume_workflow

        return resume_workflow(**kwargs)

    def handle(
        self,
        *,
        thread_id: str,
        user_id: str,
        query: str,
        product_id: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        """Run a query path or stop at the persisted ticket-approval interrupt."""

        trace_id = uuid.uuid4().hex
        audit = AuditAgent()
        started = time.perf_counter()
        context = resolve_user(user_id)
        route = TriageAgent.route(query)
        audit.record("triage", "route", route, started)

        with self._tracer.start_as_current_span("service_desk.handle") as span:
            span.set_attribute("service_desk.route", route)
            span.set_attribute("service_desk.user_role", context.role.value)
            agent_started = time.perf_counter()
            if route == "knowledge":
                result = self._knowledge_runner(context, query)
                active_agent = "knowledge"
                approval_required = False
            elif route == "diagnostic":
                result = self._status_runner(context, product_id)
                active_agent = "diagnostic"
                approval_required = False
            else:
                result = self._ticket_starter(
                    thread_id=thread_id,
                    user_id=user_id,
                    query=query,
                    product_id=product_id,
                    idempotency_key=idempotency_key,
                )
                active_agent = "ticket"
                approval_required = result.get("status") == "interrupted"
            audit.record(active_agent, "execute", str(result.get("status", "completed")), agent_started)
            audit.record("audit", "trace", "recorded", started)

        return {
            "trace_id": trace_id,
            "route": route,
            "agents": ["triage", active_agent, "audit"],
            "approval_required": approval_required,
            "result": result,
            "audit": audit.export(),
        }

    def resume_ticket(
        self,
        *,
        thread_id: str,
        user_id: str,
        approved: bool,
    ) -> dict[str, object]:
        """Resume only an existing LangGraph checkpoint after a human decision."""

        context = resolve_user(user_id)
        if context.role not in (Role.ADMIN, Role.SUPPORT):
            raise PermissionError("当前身份无权审批工单。")
        started = time.perf_counter()
        result = self._ticket_resumer(thread_id=thread_id, approved=approved)
        event = AuditEvent(
            agent="ticket",
            action="resume_after_human_review",
            status=str(result.get("status", "unknown")),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return {
            "trace_id": uuid.uuid4().hex,
            "route": "ticket",
            "agents": ["ticket", "audit"],
            "approval_required": False,
            "result": result,
            "audit": [asdict(event)],
        }
