"""SDK-backed MCP runtime access for AI capability synchronization and execution."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "sdk"
_MCP_CONFIG_PATH = _REPO_ROOT / ".mcp.json"


def _ensure_sdk_on_path() -> None:
    sdk_path = str(_SDK_ROOT)
    if sdk_path not in sys.path:
        sys.path.insert(0, sdk_path)


def _load_mcp_env_from_repo_config() -> None:
    if not _MCP_CONFIG_PATH.exists():
        return
    try:
        payload = json.loads(_MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load MCP config from %s", _MCP_CONFIG_PATH)
        return
    server_conf = (payload.get("mcpServers") or {}).get("agomtradepro_local") or {}
    for key, value in (server_conf.get("env") or {}).items():
        if value is not None:
            os.environ.setdefault(str(key), str(value))


def list_sdk_mcp_tools(*, include_legacy: bool = False) -> list[Any]:
    """List the default core surface or the explicit legacy compatibility surface."""

    _ensure_sdk_on_path()
    _load_mcp_env_from_repo_config()
    import agomtradepro_mcp.server as server_module

    previous_legacy_flag = os.environ.get("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS")
    if include_legacy:
        os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = "true"
    try:
        reloaded = importlib.reload(server_module) if include_legacy else server_module
        return asyncio.run(reloaded.server.list_tools())
    finally:
        if include_legacy:
            if previous_legacy_flag is None:
                os.environ.pop("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", None)
            else:
                os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = previous_legacy_flag
            importlib.reload(server_module)


def list_sdk_mcp_core_tool_names() -> set[str]:
    """Return the fixed core MCP tool names."""

    _ensure_sdk_on_path()
    from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES

    return set(CORE_TOOL_NAMES)


def list_sdk_mcp_capability_manifests() -> list[Any]:
    """Return all governed manifests from the canonical registry loader."""

    _ensure_sdk_on_path()
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

    return list(CapabilityRegistryLoader().build_registry().values())


def list_sdk_mcp_legacy_dispositions() -> list[Any]:
    """Return curated governance decisions for unreplaced raw MCP tools."""

    _ensure_sdk_on_path()
    from agomtradepro_mcp.legacy_dispositions import (
        list_legacy_tool_dispositions,
    )

    return list(list_legacy_tool_dispositions())


def get_sdk_mcp_legacy_disposition(tool_name: str) -> Any | None:
    """Return the curated governance decision for one raw MCP tool."""

    _ensure_sdk_on_path()
    from agomtradepro_mcp.legacy_dispositions import get_legacy_tool_disposition

    return get_legacy_tool_disposition(tool_name)


def call_sdk_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Execute one MCP tool through the SDK server contract."""

    _ensure_sdk_on_path()
    _load_mcp_env_from_repo_config()
    from agomtradepro_mcp.server import server

    result = asyncio.run(server.call_tool(tool_name, params))
    if isinstance(result, tuple) and len(result) == 2:
        return result[1]
    return result
