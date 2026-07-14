#!/usr/bin/env python
"""Check that the default MCP tool surface stays within the governed budget."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
SDK_PATH = str(SDK_ROOT)
if SDK_PATH in sys.path:
    sys.path.remove(SDK_PATH)
sys.path.insert(0, SDK_PATH)

from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES


def list_default_tools() -> list[Any]:
    """Return the default top-level MCP tool definitions exposed by the server."""
    from agomtradepro_mcp.server import server

    return list(asyncio.run(server.list_tools()))


def list_default_tool_names() -> list[str]:
    """Return the default top-level MCP tool names exposed by the server."""
    return sorted(str(tool.name) for tool in list_default_tools())


def measure_tool_schema_bytes(tools: list[Any]) -> int:
    """Measure compact UTF-8 JSON bytes for MCP tool definitions."""
    payload = []
    for tool in tools:
        if hasattr(tool, "model_dump"):
            payload.append(tool.model_dump(mode="json", exclude_none=True))
        elif isinstance(tool, dict):
            payload.append(dict(tool))
        else:
            payload.append(str(tool))
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(serialized.encode("utf-8"))


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
        raise ValueError(f"Default MCP tool surface exposes unexpected tools: {sorted(unexpected)}")


def validate_default_tool_schema_budget(
    schema_bytes: int,
    *,
    max_schema_bytes: int = 12_000,
) -> None:
    """Raise when serialized default tool metadata exceeds the byte budget."""
    if schema_bytes > max_schema_bytes:
        raise ValueError(
            "Default MCP tool schema budget exceeded: "
            f"{schema_bytes} bytes > {max_schema_bytes} bytes"
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
    parser.add_argument(
        "--max-schema-bytes",
        type=int,
        default=12_000,
        help="Maximum serialized UTF-8 bytes for default tool definitions.",
    )
    args = parser.parse_args()

    tools = list_default_tools()
    tool_names = sorted(str(tool.name) for tool in tools)
    schema_bytes = measure_tool_schema_bytes(tools)
    validate_default_tool_budget(tool_names, max_tools=args.max_tools)
    validate_default_tool_schema_budget(
        schema_bytes,
        max_schema_bytes=args.max_schema_bytes,
    )
    print(
        f"Default MCP tool budget OK: {len(tool_names)} tools, "
        f"{schema_bytes} schema bytes"
    )
    for name in tool_names:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
