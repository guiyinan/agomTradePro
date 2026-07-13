#!/usr/bin/env python
"""Check that the default MCP tool surface stays within the governed budget."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES


def list_default_tool_names() -> list[str]:
    """Return the default top-level MCP tool names exposed by the server."""
    from agomtradepro_mcp.server import server

    tools = asyncio.run(server.list_tools())
    return sorted(str(tool.name) for tool in tools)


def validate_default_tool_budget(tool_names: list[str], *, max_tools: int = 10) -> None:
    """Raise when the default top-level MCP surface exceeds the governed budget."""
    expected = set(CORE_TOOL_NAMES)
    actual = set(tool_names)
    if len(tool_names) > max_tools:
        raise ValueError(
            f"Default MCP tool budget exceeded: {len(tool_names)} tools > {max_tools}"
        )
    missing = expected - actual
    if missing:
        raise ValueError(f"Default MCP tool surface is missing core tools: {sorted(missing)}")
    unexpected = actual - expected
    if unexpected:
        raise ValueError(
            "Default MCP tool surface exposes unexpected tools: "
            f"{sorted(unexpected)}"
        )


def main() -> int:
    """CLI entrypoint for the MCP tool budget check."""
    parser = argparse.ArgumentParser(
        description="Validate the default MCP top-level tool budget.",
    )
    parser.add_argument(
        "--max-tools",
        type=int,
        default=10,
        help="Maximum allowed number of default top-level MCP tools.",
    )
    args = parser.parse_args()

    tool_names = list_default_tool_names()
    validate_default_tool_budget(tool_names, max_tools=args.max_tools)
    print(f"Default MCP tool budget OK: {len(tool_names)} tools")
    for name in tool_names:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
