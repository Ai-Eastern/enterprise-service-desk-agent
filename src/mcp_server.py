"""Local stdio MCP adapter for the read-only service-status tool."""

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.auth.context import resolve_user
from src.tools.platform_tools import get_service_status as _get_service_status


mcp = FastMCP("enterprise-service-desk-agent")


@mcp.tool(
    name="get_service_status",
    description="查询指定产品的服务状态。身份只接受可信 user_id 映射。",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def get_service_status(user_id: str, product_id: str) -> dict[str, str]:
    """Resolve a trusted local identity before calling the existing read-only tool."""

    context = resolve_user(user_id)
    return _get_service_status(context, product_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
