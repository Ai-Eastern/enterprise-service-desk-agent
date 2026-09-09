"""Local stdio MCP adapter for the read-only service-status tool."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp_types import ToolAnnotations

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.context import resolve_user
from src.tools.platform_tools import get_service_status as _get_service_status


mcp = MCPServer("enterprise-service-desk-agent")


@mcp.tool(
    name="get_service_status",
    description="查询指定产品的服务状态。",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    structured_output=True,
)
def get_service_status(ctx: Context, user_id: str, product_id: str) -> dict[str, str]:
    """Reject undeclared arguments and resolve role only from the trusted server map."""

    raw_arguments = ctx.request_context.params.get("arguments")
    if not isinstance(raw_arguments, dict) or set(raw_arguments) != {"user_id", "product_id"}:
        raise ValueError("仅允许 user_id 和 product_id 参数。")
    context = resolve_user(user_id)
    return _get_service_status(context, product_id)


if __name__ == "__main__":
    mcp.run()
