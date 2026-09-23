#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from oakn.demo import run_demo  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explicitly run one local OAKN MCP sync-and-search demonstration."
    )
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--purl", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--topic")
    parser.add_argument("--expect-claim-id")
    parser.add_argument("--index-path", type=Path, default=ROOT / ".oakn" / "demo-index.sqlite")
    arguments = parser.parse_args()

    async def execute() -> dict[str, object]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "oakn.mcp"],
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT / "src"),
                "OAKN_INDEX_PATH": str(arguments.index_path.resolve()),
                "OAKN_CLAIMS_DIR": str(ROOT / "knowledge" / "claims"),
            },
            cwd=ROOT,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await run_demo(
                    session,
                    arguments.manifest_url,
                    arguments.query,
                    arguments.purl,
                    arguments.version,
                    arguments.topic,
                    arguments.expect_claim_id,
                )

    print(json.dumps(asyncio.run(execute()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
