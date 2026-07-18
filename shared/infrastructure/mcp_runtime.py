"""Repository-local SDK MCP bootstrap shared by Django integration points."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from shared.infrastructure.async_runtime import run_awaitable_sync

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SDK_ROOT = REPO_ROOT / "sdk"
MCP_CONFIG_PATH = REPO_ROOT / ".mcp.json"


def ensure_sdk_on_path() -> None:
    """Put this repository's SDK ahead of unrelated installed checkouts."""

    sdk_path = str(SDK_ROOT)
    if sdk_path in sys.path:
        sys.path.remove(sdk_path)
    sys.path.insert(0, sdk_path)


def load_mcp_env_from_repo_config() -> None:
    """Load non-secret MCP process settings from the optional repository config."""

    if not MCP_CONFIG_PATH.exists():
        return
    try:
        payload = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        logger.exception("Failed to load MCP config from %s", MCP_CONFIG_PATH)
        return
    server_conf = (payload.get("mcpServers") or {}).get("agomtradepro_local") or {}
    for key, value in (server_conf.get("env") or {}).items():
        if value is not None:
            os.environ.setdefault(str(key), str(value))


def call_sdk_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Execute one MCP tool through the repository SDK server contract."""

    ensure_sdk_on_path()
    load_mcp_env_from_repo_config()
    from agomtradepro_mcp.server import server

    result = run_awaitable_sync(lambda: server.call_tool(tool_name, params))
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result
