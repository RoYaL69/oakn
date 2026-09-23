from __future__ import annotations

import json
from typing import Any

from mcp.client.session import ClientSession
from mcp.types import CallToolResult


class DemoError(RuntimeError):
    """A local MCP demonstration did not produce a safe, expected result."""


def parse_tool_payload(
    result: CallToolResult | Any, expected_claim_id: str | None = None
) -> dict[str, Any]:
    """Read one structured MCP result and retain the untrusted-data boundary."""
    content = getattr(result, "content", [])
    if not content or not isinstance(getattr(content[0], "text", None), str):
        raise DemoError("MCP tool response did not contain structured text")
    try:
        payload = json.loads(content[0].text)
    except json.JSONDecodeError as error:
        raise DemoError("MCP tool response was not JSON") from error
    if not isinstance(payload, dict) or payload.get("untrusted_reference_data") is not True:
        raise DemoError("MCP result is missing the untrusted-reference-data marker")
    if expected_claim_id is not None:
        results = payload.get("results")
        if not isinstance(results, list) or not any(
            isinstance(item, dict) and item.get("claim_id") == expected_claim_id for item in results
        ):
            raise DemoError("expected claim was not returned by local retrieval")
    return payload


async def run_demo(
    session: ClientSession,
    manifest_url: str,
    query: str,
    purl: str,
    version: str,
    topic: str | None = None,
    expected_claim_id: str | None = None,
) -> dict[str, Any]:
    """Sync and search through an already-established session-local MCP client."""
    sync_result = await session.call_tool("sync", {"manifest_url": manifest_url})
    sync_payload = parse_tool_payload(sync_result)
    if sync_payload.get("status") != "synced":
        raise DemoError("MCP sync did not complete")
    search_result = await session.call_tool(
        "search",
        {"query": query, "purl": purl, "version": version, "topic": topic},
    )
    return parse_tool_payload(search_result, expected_claim_id)
