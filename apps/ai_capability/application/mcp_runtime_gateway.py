"""SDK-backed MCP runtime access for AI capability synchronization and execution."""

from __future__ import annotations

import importlib
import os
from typing import Any

from shared.infrastructure.async_runtime import run_awaitable_sync
from shared.infrastructure.mcp_runtime import call_sdk_mcp_tool as _call_sdk_mcp_tool
from shared.infrastructure.mcp_runtime import ensure_sdk_on_path, load_mcp_env_from_repo_config


def list_sdk_mcp_tools(*, include_legacy: bool = False) -> list[Any]:
    """List the default core surface or the explicit legacy compatibility surface."""

    ensure_sdk_on_path()
    load_mcp_env_from_repo_config()
    import agomtradepro_mcp.server as server_module

    previous_legacy_flag = os.environ.get("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS")
    if include_legacy:
        os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = "true"
    try:
        reloaded = importlib.reload(server_module) if include_legacy else server_module
        return run_awaitable_sync(reloaded.server.list_tools)
    finally:
        if include_legacy:
            if previous_legacy_flag is None:
                os.environ.pop("AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS", None)
            else:
                os.environ["AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS"] = previous_legacy_flag
            importlib.reload(server_module)


def list_sdk_mcp_core_tool_names() -> set[str]:
    """Return the fixed core MCP tool names."""

    ensure_sdk_on_path()
    from agomtradepro_mcp.tools.core_tools import CORE_TOOL_NAMES

    return set(CORE_TOOL_NAMES)


def list_sdk_mcp_capability_manifests() -> list[Any]:
    """Return all governed manifests from the canonical registry loader."""

    ensure_sdk_on_path()
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

    return list(CapabilityRegistryLoader().build_registry().values())


def list_sdk_mcp_legacy_dispositions() -> list[Any]:
    """Return curated governance decisions for unreplaced raw MCP tools."""

    ensure_sdk_on_path()
    from agomtradepro_mcp.legacy_dispositions import (
        list_legacy_tool_dispositions,
    )

    return list(list_legacy_tool_dispositions())


def get_sdk_mcp_legacy_disposition(tool_name: str) -> Any | None:
    """Return the curated governance decision for one raw MCP tool."""

    ensure_sdk_on_path()
    from agomtradepro_mcp.legacy_dispositions import get_legacy_tool_disposition

    return get_legacy_tool_disposition(tool_name)


def call_sdk_mcp_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Execute one MCP tool through the SDK server contract."""

    return _call_sdk_mcp_tool(tool_name, params)
