"""Fail-closed mapping from demo user IDs to immutable access contexts."""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from pydantic import BaseModel, ConfigDict

from src.data_schema import Visibility


class Role(str, Enum):
    ADMIN = "admin"
    SUPPORT = "support"
    READONLY = "readonly"


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    user_id: str
    role: Role
    allowed_visibilities: tuple[Visibility, ...]


_IDENTITIES: Final[Mapping[str, UserContext]] = MappingProxyType({
    "admin-demo": UserContext(
        user_id="admin-demo",
        role=Role.ADMIN,
        allowed_visibilities=(Visibility.PUBLIC, Visibility.SUPPORT, Visibility.ADMIN),
    ),
    "support-demo": UserContext(
        user_id="support-demo",
        role=Role.SUPPORT,
        allowed_visibilities=(Visibility.PUBLIC, Visibility.SUPPORT),
    ),
    "readonly-demo": UserContext(
        user_id="readonly-demo",
        role=Role.READONLY,
        allowed_visibilities=(Visibility.PUBLIC,),
    ),
})


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
