"""Application-level query helpers for terminal and TUI operations."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.repository_provider import (
    get_terminal_command_repository,
    get_tui_metadata_repository,
)


def get_terminal_surface_status_payload() -> dict[str, Any]:
    """Return terminal command and TUI metadata health for operators."""

    command_summary = _terminal_command_summary()
    tui_summary = _tui_metadata_summary()
    return {
        "status": "ok"
        if command_summary["terminal_enabled"] > 0 and tui_summary["status"] == "ok"
        else "incomplete",
        "terminal_commands": command_summary,
        "tui_metadata": tui_summary,
    }


def _terminal_command_summary() -> dict[str, Any]:
    commands = get_terminal_command_repository().get_all_active()
    terminal_enabled = [item for item in commands if item.enabled_in_terminal]
    return {
        "active": len(commands),
        "terminal_enabled": len(terminal_enabled),
        "requires_mcp": sum(1 for item in terminal_enabled if item.requires_mcp),
        "api_type": sum(1 for item in terminal_enabled if item.is_api_type),
        "prompt_type": sum(1 for item in terminal_enabled if item.is_prompt_type),
        "status": "ok" if terminal_enabled else "empty",
    }


def _tui_metadata_summary() -> dict[str, Any]:
    metadata = get_tui_metadata_repository().load_published()
    modules = list(metadata.get("modules") or [])
    screens = list(metadata.get("screens") or [])
    actions = list(metadata.get("actions") or [])
    return {
        "status": "ok" if screens and actions else "empty",
        "version": metadata.get("version"),
        "schema_version": metadata.get("schema_version"),
        "modules": len(modules),
        "screens": len(screens),
        "actions": len(actions),
        "default_screen": metadata.get("default_screen"),
        "coverage_summary": dict(metadata.get("coverage_summary") or {}),
    }
