"""Minimal LangGraph workflow with approval before side effects."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import NotRequired, TypedDict

from src.config import PROJECT_PATHS

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.auth.context import resolve_user
from src.retrieval.chroma_store import CHROMA_PATH, search
from src.tools.platform_tools import (
    CreateTicketInput,
    ServiceStatusInput,
    TOOL_SPECS,
    ToolError,
    ToolErrorCode,
    create_ticket,
    get_service_status,
)


CHECKPOINT_PATH = PROJECT_PATHS["runtime"] / "checkpoints.sqlite"
TICKETS_PATH = PROJECT_PATHS["runtime"] / "tickets.sqlite"
_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")


class WorkflowState(TypedDict):
    thread_id: str
    user_id: str
    query: str
    product_id: str
    idempotency_key: str
    tickets_path: str
    chroma_path: str
    role: NotRequired[str]
    allowed_visibilities: NotRequired[list[str]]
    retrievals: NotRequired[list[dict[str, object]]]
    tool_name: NotRequired[str]
    tool_args: NotRequired[dict[str, object]]
    permission_result: NotRequired[str]
    review_approved: NotRequired[bool]
    tool_result: NotRequired[dict[str, object]]
    tool_error: NotRequired[dict[str, str]]
    answer: NotRequired[str]
    citations: NotRequired[list[dict[str, str]]]


def _context_node(state: WorkflowState) -> dict[str, object]:
    context = resolve_user(state["user_id"])
    return {
        "role": context.role.value,
        "allowed_visibilities": [value.value for value in context.allowed_visibilities],
    }


def _retrieve_node(state: WorkflowState) -> dict[str, object]:
    results = search(
        state["query"],
        state["allowed_visibilities"],
        5,
        Path(state["chroma_path"]),
    )
    return {"retrievals": [asdict(result) for result in results]}


def _decide_tool_node(state: WorkflowState) -> dict[str, object]:
    if "创建工单" in state["query"]:
        tool_args = CreateTicketInput.model_validate(
            {
                "product_id": state["product_id"],
                "summary": state["query"],
                "idempotency_key": state["idempotency_key"],
            }
        ).model_dump()
        return {"tool_name": "create_ticket", "tool_args": tool_args}
    if "服务状态" in state["query"]:
        tool_args = ServiceStatusInput.model_validate({"product_id": state["product_id"]}).model_dump()
        return {"tool_name": "get_service_status", "tool_args": tool_args}
    return {"tool_name": "", "tool_args": {}}


def _permission_node(state: WorkflowState) -> dict[str, str]:
    if not state["tool_name"]:
        return {"permission_result": "not_required"}
    context = resolve_user(state["user_id"])
    trusted = (
        context.role.value == state["role"]
        and [value.value for value in context.allowed_visibilities] == state["allowed_visibilities"]
    )
    allowed = trusted and context.role in TOOL_SPECS[state["tool_name"]].allowed_roles
    return {"permission_result": "allowed" if allowed else "denied"}


def _review_node(state: WorkflowState) -> dict[str, bool]:
    approved = interrupt(
        {
            "action": state["tool_name"],
            "user_id": state["user_id"],
            "role": state["role"],
            "permission_result": state["permission_result"],
            "retrieved_doc_ids": list(
                dict.fromkeys(str(result["doc_id"]) for result in state["retrievals"])
            ),
            "tool_args": state["tool_args"],
            "message": "创建工单会写入本地数据库，是否批准？",
        }
    )
    return {"review_approved": bool(approved)}


def _after_permission(state: WorkflowState) -> str:
    if state["permission_result"] != "allowed":
        return "answer"
    return "review" if TOOL_SPECS[state["tool_name"]].side_effect else "execute_tool"


def _after_review(state: WorkflowState) -> str:
    return "execute_tool" if state["review_approved"] else "answer"


def _execute_tool_node(state: WorkflowState) -> dict[str, object]:
    context = resolve_user(state["user_id"])
    try:
        if state["tool_name"] == "create_ticket":
            result = create_ticket(
                context,
                state["tool_args"],
                db_path=Path(state["tickets_path"]),
            )
        else:
            result = get_service_status(context, str(state["tool_args"]["product_id"]))
        return {"tool_result": result}
    except TimeoutError as exc:
        return {
            "tool_error": {
                "code": ToolErrorCode.TIMEOUT.value,
                "message": "工具执行超时。",
            }
        }
    except ToolError as exc:
        return {"tool_error": {"code": exc.code.value, "message": exc.message}}


def _answer_node(state: WorkflowState) -> dict[str, object]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in state.get("retrievals", []):
        doc_id = str(result["doc_id"])
        if doc_id not in seen:
            citations.append({"doc_id": doc_id, "source_file": str(result["source_file"])})
            seen.add(doc_id)
    if state.get("review_approved") is False:
        answer = "人工复核已拒绝，未创建工单。"
    elif state.get("permission_result") == "denied":
        answer = "当前身份无权执行该工具。"
    elif state.get("tool_error"):
        answer = state["tool_error"]["message"]
    elif state.get("tool_result"):
        if state["tool_name"] == "create_ticket":
            ticket_id = str(state["tool_result"]["ticket_id"])
            reused = bool(state["tool_result"]["reused"])
            answer = f"工单 {ticket_id} 已{'复用' if reused else '创建'}。"
        else:
            answer = str(state["tool_result"]["status_message"])
    else:
        first = state["retrievals"][0]
        answer = f"根据《{first['title']}》：{str(first['text'])[:160]}"
    if citations:
        references = "、".join(
            f"[{citation['doc_id']}]({citation['source_file']})" for citation in citations
        )
        answer = f"{answer} 引用：{references}"
    return {"answer": answer, "citations": citations}


def _compile(checkpointer: SqliteSaver):
    builder = StateGraph(WorkflowState)
    builder.add_node("context", _context_node)
    builder.add_node("retrieve", _retrieve_node)
    builder.add_node("decide_tool", _decide_tool_node)
    builder.add_node("permission", _permission_node)
    builder.add_node("review", _review_node)
    builder.add_node("execute_tool", _execute_tool_node)
    builder.add_node("answer", _answer_node)
    builder.add_edge(START, "context")
    builder.add_edge("context", "retrieve")
    builder.add_edge("retrieve", "decide_tool")
    builder.add_edge("decide_tool", "permission")
    builder.add_conditional_edges(
        "permission",
        _after_permission,
        {"review": "review", "execute_tool": "execute_tool", "answer": "answer"},
    )
    builder.add_conditional_edges(
        "review", _after_review, {"execute_tool": "execute_tool", "answer": "answer"}
    )
    builder.add_edge("execute_tool", "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=checkpointer)


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    if not isinstance(thread_id, str) or not _THREAD_ID_PATTERN.fullmatch(thread_id):
        raise ValueError("thread_id 必须是 3-128 位字母、数字、下划线或连字符。")
    return {"configurable": {"thread_id": thread_id}}


def _public_result(result: dict[str, object], thread_id: str) -> dict[str, object]:
    interrupts = result.get("__interrupt__", ())
    if interrupts:
        return {
            "status": "interrupted",
            "thread_id": thread_id,
            "interrupt": interrupts[0].value,
        }
    payload: dict[str, object] = {
        "status": "completed",
        "thread_id": thread_id,
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
    }
    if result.get("tool_result"):
        payload["tool_result"] = result["tool_result"]
    if result.get("tool_error"):
        payload["tool_error"] = result["tool_error"]
    return payload


def start_workflow(
    *,
    thread_id: str,
    user_id: str,
    query: str,
    product_id: str,
    idempotency_key: str,
    checkpoint_path: Path = CHECKPOINT_PATH,
    tickets_path: Path = TICKETS_PATH,
    chroma_path: Path = CHROMA_PATH,
) -> dict[str, object]:
    """Run until completion or the first human-review interrupt."""

    config = _config(thread_id)
    resolve_user(user_id)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    state: WorkflowState = {
        "thread_id": thread_id,
        "user_id": user_id,
        "query": query,
        "product_id": product_id,
        "idempotency_key": idempotency_key,
        "tickets_path": str(tickets_path),
        "chroma_path": str(chroma_path),
    }
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        result = _compile(checkpointer).invoke(state, config)
    return _public_result(result, thread_id)


def resume_workflow(
    *,
    thread_id: str,
    approved: bool,
    checkpoint_path: Path = CHECKPOINT_PATH,
) -> dict[str, object]:
    """Resume one persisted interrupt with the same stable thread ID."""

    config = _config(thread_id)
    if not isinstance(approved, bool):
        raise ValueError("approved 必须是布尔值。")
    if not checkpoint_path.is_file():
        raise ValueError("未找到可恢复的检查点数据库。")
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        result = _compile(checkpointer).invoke(Command(resume=approved), config)
    return _public_result(result, thread_id)
