"""Permission-checked local tools for the fictional platform demo."""

from __future__ import annotations

import csv
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.auth.context import Role, UserContext, is_trusted_context
from src.config import PROJECT_PATHS


_PRODUCT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$"
_PRODUCTS_PATH = PROJECT_PATHS["data"] / "products.csv"
_TICKETS_PATH = PROJECT_PATHS["runtime"] / "tickets.sqlite"


class ToolErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    PERMISSION_DENIED = "permission_denied"
    PRODUCT_NOT_FOUND = "product_not_found"
    DATABASE_BUSY = "database_busy"
    INTERNAL_ERROR = "internal_error"
    TIMEOUT = "timeout"


class ToolError(Exception):
    def __init__(self, code: ToolErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ServiceStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: str = Field(min_length=3, max_length=64, pattern=_PRODUCT_ID_PATTERN)


class CreateTicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: str = Field(min_length=3, max_length=64, pattern=_PRODUCT_ID_PATTERN)
    summary: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=3, max_length=128)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    input_model: type[BaseModel]
    side_effect: bool
    allowed_roles: tuple[Role, ...]


TOOL_SPECS: dict[str, ToolSpec] = {
    "get_service_status": ToolSpec(
        name="get_service_status",
        input_model=ServiceStatusInput,
        side_effect=False,
        allowed_roles=(Role.ADMIN, Role.SUPPORT, Role.READONLY),
    ),
    "create_ticket": ToolSpec(
        name="create_ticket",
        input_model=CreateTicketInput,
        side_effect=True,
        allowed_roles=(Role.ADMIN, Role.SUPPORT),
    ),
}


def _validation(model: type[BaseModel], payload: object) -> BaseModel:
    try:
        return payload if isinstance(payload, model) else model.model_validate(payload)
    except ValidationError as exc:
        raise ToolError(ToolErrorCode.VALIDATION_ERROR, "输入参数不符合要求。") from exc


def _require_permission(context: UserContext, spec_name: str) -> None:
    spec = TOOL_SPECS[spec_name]
    if not is_trusted_context(context) or context.role not in spec.allowed_roles:
        raise ToolError(ToolErrorCode.PERMISSION_DENIED, "当前身份无权执行该工具。")


def _read_products(products_path: Path = _PRODUCTS_PATH) -> dict[str, dict[str, str]]:
    try:
        with products_path.open("r", encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream)
            required_fields = {"product_id", "name", "service_status", "status_message"}
            if not rows.fieldnames or not required_fields.issubset(rows.fieldnames):
                raise KeyError("产品数据缺少必需列。")
            products: dict[str, dict[str, str]] = {}
            for row in rows:
                if not all(row.get(field) for field in required_fields):
                    raise KeyError("产品数据缺少必需值。")
                products[row["product_id"]] = row
            return products
    except (OSError, UnicodeError, csv.Error, KeyError) as exc:
        raise ToolError(ToolErrorCode.INTERNAL_ERROR, "服务状态暂不可用。") from exc


def get_service_status(
    context: UserContext,
    product_id: str,
    *,
    products_path: Path = _PRODUCTS_PATH,
) -> dict[str, str]:
    """Read one fictional product status without network access."""

    _require_permission(context, "get_service_status")
    validated = _validation(ServiceStatusInput, {"product_id": product_id})
    row = _read_products(products_path).get(validated.product_id)
    if row is None:
        raise ToolError(ToolErrorCode.PRODUCT_NOT_FOUND, "产品不存在。")
    return {
        "product_id": row["product_id"],
        "name": row["name"],
        "service_status": row["service_status"],
        "status_message": row["status_message"],
    }


def _open_ticket_db(db_path: Path | str) -> sqlite3.Connection:
    resolved_path = Path(db_path)
    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(resolved_path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection
    except sqlite3.OperationalError as exc:
        raise ToolError(ToolErrorCode.DATABASE_BUSY, "工单数据库正忙，请稍后重试。") from exc
    except sqlite3.Error as exc:
        raise ToolError(ToolErrorCode.INTERNAL_ERROR, "工单暂时无法保存。") from exc
    except OSError as exc:
        raise ToolError(ToolErrorCode.INTERNAL_ERROR, "工单暂时无法保存。") from exc


def create_ticket(
    context: UserContext,
    payload: Mapping[str, object] | CreateTicketInput,
    *,
    db_path: Path | str = _TICKETS_PATH,
    products_path: Path = _PRODUCTS_PATH,
) -> dict[str, object]:
    """Create one ticket transactionally, reusing an existing idempotency key."""

    _require_permission(context, "create_ticket")
    validated = _validation(CreateTicketInput, payload)
    products = _read_products(products_path)
    if validated.product_id not in products:
        raise ToolError(ToolErrorCode.PRODUCT_NOT_FOUND, "产品不存在。")

    connection = _open_ticket_db(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tickets ("
            "ticket_id TEXT PRIMARY KEY, "
            "idempotency_key TEXT NOT NULL UNIQUE, "
            "user_id TEXT NOT NULL, role TEXT NOT NULL, product_id TEXT NOT NULL, "
            "summary TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL"
            ")"
        )
        ticket_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            connection.execute(
                "INSERT INTO tickets "
                "(ticket_id, idempotency_key, user_id, role, product_id, summary, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ticket_id,
                    validated.idempotency_key,
                    context.user_id,
                    context.role.value,
                    validated.product_id,
                    validated.summary,
                    "open",
                    created_at,
                ),
            )
            reused = False
        except sqlite3.IntegrityError:
            existing = connection.execute(
                "SELECT ticket_id FROM tickets WHERE idempotency_key = ?",
                (validated.idempotency_key,),
            ).fetchone()
            if existing is None:
                raise
            ticket_id = str(existing[0])
            reused = True
        connection.commit()
        return {"ticket_id": ticket_id, "reused": reused}
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise ToolError(ToolErrorCode.DATABASE_BUSY, "工单数据库正忙，请稍后重试。") from exc
        raise ToolError(ToolErrorCode.INTERNAL_ERROR, "工单暂时无法保存。") from exc
    except sqlite3.Error as exc:
        connection.rollback()
        raise ToolError(ToolErrorCode.INTERNAL_ERROR, "工单暂时无法保存。") from exc
    finally:
        connection.close()
