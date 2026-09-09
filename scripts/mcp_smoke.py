"""One local stdio MCP smoke call; print only after the protocol closes."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters


ROOT = Path(__file__).resolve().parents[1]
MANAGED_CACHE = ROOT / ".cache" / "mcp"
MANAGED_TEMP = ROOT / ".tmp" / "mcp"


def _structured(result: object) -> dict[str, str]:
    payload = getattr(result, "structuredContent", None)
    if payload is None:
        content = getattr(result, "content", ())
        payload = json.loads(content[0].text)
    if "result" in payload and isinstance(payload["result"], dict):
        payload = payload["result"]
    return payload


async def run() -> dict[str, object]:
    MANAGED_CACHE.mkdir(parents=True, exist_ok=True)
    MANAGED_TEMP.mkdir(parents=True, exist_ok=True)
    child_env = os.environ.copy()
    child_env.update(
        {
            "PIP_CACHE_DIR": str(MANAGED_CACHE),
            "TEMP": str(MANAGED_TEMP),
            "TMP": str(MANAGED_TEMP),
        }
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "src" / "mcp_server.py")],
        cwd=str(ROOT),
        env=child_env,
    )
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        names = [tool.name for tool in listed.tools]
        result = await client.call_tool(
            "get_service_status",
            {"user_id": "readonly-demo", "product_id": "smart-assist"},
        )
        payload = _structured(result)
    return {
        "status": "ok",
        "tool_names": names,
        "call": {
            "tool": "get_service_status",
            "product_id": "smart-assist",
            "field_count": len(payload),
        },
    }


def main() -> int:
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
