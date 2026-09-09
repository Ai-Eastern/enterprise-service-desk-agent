from __future__ import annotations

import unittest

from src.mcp_server import mcp


class McpContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_readonly_status_tool_is_registered(self) -> None:
        tools = await mcp.list_tools()
        self.assertEqual([tool.name for tool in tools], ["get_service_status"])
        tool = tools[0]
        self.assertEqual(set(tool.input_schema["required"]), {"user_id", "product_id"})
        self.assertNotIn("role", tool.input_schema["properties"])
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertFalse(tool.annotations.destructive_hint)


if __name__ == "__main__":
    unittest.main()
