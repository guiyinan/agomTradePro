"""Load and validate the versioned TUI information-architecture registry."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

TUI_IA_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "tui"
    / "ia"
    / "tui_information_architecture.v1.json"
)


@lru_cache(maxsize=1)
def load_tui_information_architecture() -> dict[str, Any]:
    """Return the validated declarative TUI IA registry."""

    raw_payload = json.loads(TUI_IA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_payload, dict):
        raise ValueError("TUI IA registry root must be an object")
    payload = cast(dict[str, Any], raw_payload)
    _validate_tui_information_architecture(payload)
    return payload


def screen_aliases(registry: dict[str, Any] | None = None) -> dict[str, str]:
    """Return every source screen key mapped to one canonical screen key."""

    source = registry or load_tui_information_architecture()
    aliases: dict[str, str] = {}
    for screen in [
        *source.get("published_screens", []),
        *source.get("runtime_screens", []),
    ]:
        target = str(screen["key"])
        for alias in [
            *screen.get("sources", []),
            *screen.get("runtime_sources", []),
        ]:
            aliases[str(alias)] = target
        aliases[target] = target
    return aliases


def screen_specs(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return canonical published and runtime screen specs keyed by screen key."""

    source = registry or load_tui_information_architecture()
    return {
        str(screen["key"]): dict(screen)
        for screen in [
            *source.get("published_screens", []),
            *source.get("runtime_screens", []),
        ]
    }


def public_screen_spec(screen: dict[str, Any]) -> dict[str, Any]:
    """Strip compiler-only source aliases from a screen definition."""

    return {
        key: value for key, value in screen.items() if key not in {"sources", "runtime_sources"}
    }


def _validate_tui_information_architecture(payload: dict[str, Any]) -> None:
    """Fail fast when the IA registry has duplicate or dangling definitions."""

    required = {"version", "groups", "modules", "published_screens", "runtime_screens", "workflow"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"TUI IA registry missing keys: {sorted(missing)}")

    groups = {str(group["key"]) for group in payload["groups"]}
    modules = {str(module["key"]): module for module in payload["modules"]}
    screens = [*payload["published_screens"], *payload["runtime_screens"]]
    screen_keys = [str(screen["key"]) for screen in screens]
    if len(screen_keys) != len(set(screen_keys)):
        raise ValueError("TUI IA registry contains duplicate canonical screen keys")

    aliases: dict[str, str] = {}
    for screen in screens:
        screen_key = str(screen["key"])
        module_key = str(screen["module_key"])
        group_key = str(screen["group"])
        if module_key not in modules:
            raise ValueError(f"TUI screen {screen_key} references unknown module {module_key}")
        if group_key not in groups or str(modules[module_key]["group"]) != group_key:
            raise ValueError(f"TUI screen {screen_key} has inconsistent group/module ownership")
        for source in [
            *screen.get("sources", []),
            *screen.get("runtime_sources", []),
        ]:
            source_key = str(source)
            previous = aliases.setdefault(source_key, screen_key)
            if previous != screen_key:
                raise ValueError(f"TUI source screen {source_key} maps to multiple targets")

    published_keys = {str(screen["key"]) for screen in payload["published_screens"]}
    workflow_keys = [str(step["screen_key"]) for step in payload["workflow"]]
    if len(workflow_keys) != 8 or len(workflow_keys) != len(set(workflow_keys)):
        raise ValueError("TUI daily workflow must contain eight unique screens")
    if not set(workflow_keys).issubset(published_keys):
        raise ValueError("TUI daily workflow references a non-published screen")
