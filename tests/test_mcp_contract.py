from __future__ import annotations

import unittest

from src.mcp_server import mcp


class McpContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_readonly_status_tool_is_registered(self) -> None:
        tools = await mcp.list_tools()
        self.assertEqual([tool.name for tool in tools], ["get_service_status"])
        tool = tools[0]
        self.assertEqual(set(tool.inputSchema["required"]), {"user_id", "product_id"})
        self.assertNotIn("role", tool.inputSchema["properties"])
        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertFalse(tool.annotations.destructiveHint)


if __name__ == "__main__":
    unittest.main()
