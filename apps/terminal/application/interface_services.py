"""Application-facing helpers for terminal interface views."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.terminal.application.repository_provider import (
    get_terminal_command_repository,
    get_terminal_runtime_settings_repository,
)


def get_terminal_config_page_context() -> dict[str, Any]:
    """Build the template context for the terminal config page."""

    commands = sorted(
        get_terminal_command_repository().get_all(),
        key=lambda command: (command.category, command.name),
    )
    categories: dict[str, list[Any]] = defaultdict(list)
    for command in commands:
        categories[command.category].append(command)

    return {
        "page_title": "Terminal Command Config",
        "page_description": "Configure terminal commands",
        "commands": commands,
        "categories": dict(categories),
    }


def can_create_terminal_runtime_settings() -> bool:
    """Return whether the singleton runtime settings row can be created."""

    return not get_terminal_runtime_settings_repository().has_settings()
