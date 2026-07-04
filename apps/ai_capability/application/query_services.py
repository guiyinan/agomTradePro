"""Application-level query helpers for AI capability operations."""

from __future__ import annotations

from typing import Any

from apps.ai_capability.application.repository_provider import (
    get_capability_repository,
    get_capability_sync_log_repository,
)


def get_ai_capability_surface_status_payload() -> dict[str, Any]:
    """Return MCP and terminal capability catalog health for operators."""

    repository = get_capability_repository()
    stats = repository.get_stats()
    return {
        "status": _catalog_status(stats),
        "catalog": {
            "total": stats["total"],
            "enabled": stats["enabled"],
            "disabled": stats["disabled"],
        },
        "mcp_tools": _source_summary("mcp_tool"),
        "terminal_capabilities": _source_summary("terminal_command"),
    }


def _source_summary(source_type: str) -> dict[str, Any]:
    repository = get_capability_repository()
    capabilities = repository.get_by_source_type(source_type)
    latest_sync = get_capability_sync_log_repository().get_latest(source_type)
    return {
        "total": len(capabilities),
        "routing_enabled": sum(1 for item in capabilities if item.enabled_for_routing),
        "terminal_enabled": sum(1 for item in capabilities if item.enabled_for_terminal),
        "chat_enabled": sum(1 for item in capabilities if item.enabled_for_chat),
        "agent_enabled": sum(1 for item in capabilities if item.enabled_for_agent),
        "requires_confirmation": sum(
            1 for item in capabilities if item.requires_confirmation
        ),
        "latest_sync_at": latest_sync.finished_at.isoformat() if latest_sync else None,
        "status": "ok" if capabilities else "empty",
    }


def _catalog_status(stats: dict[str, Any]) -> str:
    by_source = stats.get("by_source") or {}
    has_mcp = int(by_source.get("mcp_tool", 0) or 0) > 0
    has_terminal = int(by_source.get("terminal_command", 0) or 0) > 0
    return "ok" if has_mcp and has_terminal else "incomplete"
