"""Stable standard-library data contracts for the fictional demo dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


_STABLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
SERVICE_STATUSES = frozenset({"operational", "degraded", "maintenance"})


class Visibility(str, Enum):
    PUBLIC = "public"
    SUPPORT = "support"
    ADMIN = "admin"


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not (cleaned := value.strip()):
        raise ValueError(f"{name} 必须是非空文本。")
    return cleaned


def _stable_id(name: str, value: str) -> str:
    cleaned = _required_text(name, value)
    if not _STABLE_ID.fullmatch(cleaned):
        raise ValueError(f"{name} 必须为 3-64 位小写字母、数字或连字符。")
    return cleaned


@dataclass(frozen=True)
class KnowledgeDocument:
    doc_id: str
    title: str
    category: str
    visibility: Visibility
    product_id: str
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "doc_id", _stable_id("doc_id", self.doc_id))
        object.__setattr__(self, "title", _required_text("title", self.title))
        object.__setattr__(self, "category", _required_text("category", self.category))
        try:
            visibility = Visibility(self.visibility)
        except (TypeError, ValueError) as exc:
            raise ValueError("visibility 必须是 public、support 或 admin。") from exc
        object.__setattr__(self, "visibility", visibility)
        object.__setattr__(self, "product_id", _stable_id("product_id", self.product_id))
        object.__setattr__(self, "content", _required_text("content", self.content))

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "doc_id": self.doc_id,
            "visibility": self.visibility.value,
            "category": self.category,
            "product_id": self.product_id,
        }


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    service_status: str
    status_message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", _stable_id("product_id", self.product_id))
        object.__setattr__(self, "name", _required_text("name", self.name))
        status = _required_text("service_status", self.service_status)
        if status not in SERVICE_STATUSES:
            raise ValueError("service_status 必须是 operational、degraded 或 maintenance。")
        object.__setattr__(self, "service_status", status)
        object.__setattr__(
            self, "status_message", _required_text("status_message", self.status_message)
        )


class EvalTool(str, Enum):
    NONE = "none"
    GET_SERVICE_STATUS = "get_service_status"
    CREATE_TICKET = "create_ticket"


class PermissionResult(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"


_EVAL_ROLES = frozenset({"admin", "support", "readonly"})
@dataclass(frozen=True)
class EvaluationCase:
    query_id: str
    question: str
    role: str
    expected_doc_ids: tuple[str, ...]
    expected_tool: EvalTool | str
    expected_permission_result: PermissionResult | str

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _stable_id("query_id", self.query_id))
        object.__setattr__(self, "question", _required_text("question", self.question))
        role = _required_text("role", self.role)
        if role not in _EVAL_ROLES:
            raise ValueError("role 必须是 admin、support 或 readonly。")
        object.__setattr__(self, "role", role)
        doc_ids = tuple(_stable_id("expected_doc_id", value) for value in self.expected_doc_ids)
        if len(doc_ids) != len(set(doc_ids)):
            raise ValueError("expected_doc_ids 不得重复。")
        object.__setattr__(self, "expected_doc_ids", doc_ids)
        try:
            tool = EvalTool(self.expected_tool)
            permission = PermissionResult(self.expected_permission_result)
        except (TypeError, ValueError) as exc:
            raise ValueError("评测工具或权限结果无效。") from exc
        if tool is not EvalTool.NONE and doc_ids:
            raise ValueError("工具用例不得引用评测文档。")
        if tool is not EvalTool.CREATE_TICKET and permission is PermissionResult.DENIED:
            raise ValueError("只有 create_ticket 用例可使用 denied。")
        if tool is EvalTool.CREATE_TICKET and permission is PermissionResult.DENIED and role != "readonly":
            raise ValueError("仅 readonly 可产生拒绝的 create_ticket 用例。")
        if tool is EvalTool.CREATE_TICKET and permission is PermissionResult.ALLOWED and role == "readonly":
            raise ValueError("readonly 不得产生允许的 create_ticket 用例。")
        object.__setattr__(self, "expected_tool", tool)
        object.__setattr__(self, "expected_permission_result", permission)

    def as_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "question": self.question,
            "role": self.role,
            "expected_doc_ids": list(self.expected_doc_ids),
            "expected_tool": self.expected_tool.value,
            "expected_permission_result": self.expected_permission_result.value,
        }
