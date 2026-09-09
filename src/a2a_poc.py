"""A2A 0.3 proof of concept for an isolated read-only diagnosis agent."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from a2a.compat.v0_3.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)

from src.auth.context import resolve_user
from src.tools.platform_tools import ToolError, get_service_status


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _message(text: str, *, task_id: str, context_id: str) -> Message:
    return Message(
        messageId=uuid.uuid4().hex,
        taskId=task_id,
        contextId=context_id,
        role=Role.agent,
        parts=[Part(root=TextPart(text=text))],
    )


def build_diagnostic_agent_card() -> AgentCard:
    """Describe the capability without claiming a deployed remote endpoint."""

    return AgentCard(
        name="service-status-diagnostic-agent",
        description="查询本地虚构产品的服务状态并返回诊断结果。",
        url="http://127.0.0.1:8091/a2a",
        version="0.3.0-poc",
        protocolVersion="0.3.0",
        preferredTransport="JSONRPC",
        capabilities=AgentCapabilities(
            streaming=False,
            pushNotifications=False,
            stateTransitionHistory=True,
        ),
        defaultInputModes=["application/json"],
        defaultOutputModes=["application/json"],
        skills=[
            AgentSkill(
                id="get-service-status",
                name="服务状态诊断",
                description="基于可信 user_id 查询指定 product_id 的服务状态。",
                tags=["service-desk", "readonly", "diagnosis"],
                examples=["查询 smart-assist 当前服务状态"],
            )
        ],
    )


def run_diagnostic_task(
    *,
    user_id: str,
    product_id: str,
    products_path: Path,
    task_id: str | None = None,
    context_id: str | None = None,
) -> list[Task]:
    """Return an auditable A2A task-state history for one local diagnosis request."""

    resolved_task_id = task_id or uuid.uuid4().hex
    resolved_context_id = context_id or uuid.uuid4().hex
    history = [
        Task(
            id=resolved_task_id,
            contextId=resolved_context_id,
            status=TaskStatus(state=TaskState.submitted, timestamp=_timestamp()),
        ),
        Task(
            id=resolved_task_id,
            contextId=resolved_context_id,
            status=TaskStatus(state=TaskState.working, timestamp=_timestamp()),
        ),
    ]
    try:
        result = get_service_status(
            resolve_user(user_id),
            product_id,
            products_path=products_path,
        )
    except (ToolError, ValueError) as exc:
        history.append(
            Task(
                id=resolved_task_id,
                contextId=resolved_context_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    timestamp=_timestamp(),
                    message=_message(
                        f"诊断失败：{exc}",
                        task_id=resolved_task_id,
                        context_id=resolved_context_id,
                    ),
                ),
            )
        )
        return history

    history.append(
        Task(
            id=resolved_task_id,
            contextId=resolved_context_id,
            status=TaskStatus(state=TaskState.completed, timestamp=_timestamp()),
            artifacts=[
                Artifact(
                    artifactId=uuid.uuid4().hex,
                    name="service-status-result",
                    parts=[Part(root=TextPart(text=json.dumps(result, ensure_ascii=False)))],
                )
            ],
        )
    )
    return history
