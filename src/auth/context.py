"""Fail-closed mapping from demo user IDs to immutable access contexts."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from pydantic import BaseModel, ConfigDict

from src.data_schema import DEMO_IDENTITIES, Visibility


class Role(str, Enum):
    ADMIN = "admin"
    SUPPORT = "support"
    READONLY = "readonly"


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    user_id: str
    role: Role
    allowed_visibilities: tuple[Visibility, ...]


_IDENTITIES: Final[Mapping[str, UserContext]] = MappingProxyType(
    {
        identity.user_id: UserContext(
            user_id=identity.user_id,
            role=Role(identity.role),
            allowed_visibilities=identity.allowed_visibilities,
        )
        for identity in DEMO_IDENTITIES
    }
)


def resolve_user(user_id: str) -> UserContext:
    """Resolve only the three hard-coded demo identities; unknown IDs fail closed."""

    if not isinstance(user_id, str):
        raise ValueError("未知演示身份。")
    context = _IDENTITIES.get(user_id.strip())
    if context is None:
        raise ValueError("未知演示身份。")
    return context


def is_trusted_context(context: UserContext) -> bool:
    """Check that a context exactly matches the immutable hard mapping."""

    return isinstance(context, UserContext) and _IDENTITIES.get(context.user_id) == context
