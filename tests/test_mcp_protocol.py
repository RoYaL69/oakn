import asyncio
import os
import sys
import unittest
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from oakn.mcp import create_mcp_server


class McpProtocolTests(unittest.TestCase):
    def test_declares_the_core_tools_without_global_hermes_configuration(self) -> None:
        server = create_mcp_server(
            index_path=Path("/tmp/oakn-index.sqlite"), claims_directory=Path("knowledge/claims")
        )

        tools = asyncio.run(server.list_tools())

        self.assertEqual(
            {tool.name for tool in tools},
            {"resolve_project", "search", "get", "contribute", "sync", "validate_candidate"},
        )

    def test_contribute_publishes_only_when_draft_mode_is_explicit(self) -> None:
        class Publisher:
            def __init__(self) -> None:
                self.calls: list[tuple[dict, str, str]] = []

            def publish(
                self, candidate: dict, repository_path: str, github_repository: str
            ) -> dict[str, str]:
                self.calls.append((candidate, repository_path, github_repository))
                return {
                    "status": "draft_pr_created",
                    "url": "https://github.com/RoYaL69/oakn/pull/99",
                    "branch": "oakn/claim",
                }

        publisher = Publisher()
        server = create_mcp_server(
            index_path=Path("/tmp/oakn-index.sqlite"),
            claims_directory=Path("knowledge/claims"),
            publisher=publisher,
        )
        result = asyncio.run(
            server.call_tool(
                "contribute",
                {
                    "candidate": {"id": "99999999-9999-4999-8999-999999999999"},
                    "publish_mode": "draft_pr",
                    "repository_path": "/tmp/oakn",
                    "github_repository": "RoYaL69/oakn",
                },
            )
        )

        self.assertEqual(len(publisher.calls), 1)
        self.assertIn("draft_pr_created", result.content[0].text)

    def test_stdio_server_completes_mcp_tool_discovery(self) -> None:
        async def list_tools() -> set[str]:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "oakn.mcp"],
                env={**os.environ, "PYTHONPATH": str(Path.cwd() / "src")},
                cwd=Path.cwd(),
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return {tool.name for tool in result.tools}

        self.assertIn("search", asyncio.run(list_tools()))


if __name__ == "__main__":
    unittest.main()
