#!/usr/bin/env python
"""Verify that every published TUI action is reachable through governed MCP bridges."""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO_ROOT / "sdk"
ACTION_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
BRIDGE_CAPABILITIES = {
    "terminal.search.user_actions",
    "terminal.read.user_action_schema",
    "terminal.read.user_action_result",
    "terminal.execute.user_action",
}
SUPPORTED_RISKS = {"read", "ai", "write", "admin"}


def setup_runtime() -> None:
    """Initialize Django and prefer the repository SDK."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    for path in (str(REPO_ROOT), str(SDK_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import django

    django.setup()


def validate_tui_action_coverage(
    *,
    actions: list[dict[str, Any]],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Validate complete published-action classification and bridge contracts."""

    keys = [str(action.get("key") or "").strip() for action in actions]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    invalid_keys = sorted(key for key in keys if ACTION_KEY_PATTERN.fullmatch(key) is None)
    invalid_risks = sorted(
        {
            str(action.get("risk") or "")
            for action in actions
            if str(action.get("risk") or "") not in SUPPORTED_RISKS
        }
    )
    missing_bridges = sorted(BRIDGE_CAPABILITIES - set(registry))
    errors = []
    if not actions:
        errors.append("published TUI action catalog is empty")
    if any(not key for key in keys):
        errors.append("published TUI action key is empty")
    if duplicate_keys:
        errors.append(f"duplicate action keys: {duplicate_keys}")
    if invalid_keys:
        errors.append(f"unsupported action keys: {invalid_keys}")
    if invalid_risks:
        errors.append(f"unsupported action risks: {invalid_risks}")
    if missing_bridges:
        errors.append(f"missing MCP bridge capabilities: {missing_bridges}")

    read_bridge = registry.get("terminal.read.user_action_result")
    write_bridge = registry.get("terminal.execute.user_action")
    if read_bridge is not None and read_bridge.requires_confirmation:
        errors.append("read action bridge must not require confirmation")
    if write_bridge is not None and (
        not write_bridge.requires_confirmation or write_bridge.idempotency != "required"
    ):
        errors.append("write action bridge must require confirmation and idempotency")
    if errors:
        raise ValueError("MCP TUI action coverage failed:\n- " + "\n- ".join(errors))

    risk_counts = Counter(str(action.get("risk") or "") for action in actions)
    return {
        "published_action_count": len(actions),
        "unique_action_count": len(set(keys)),
        "read_bridge_count": risk_counts.get("read", 0),
        "confirmed_bridge_count": sum(
            risk_counts.get(risk, 0) for risk in ("ai", "write", "admin")
        ),
        "bridge_capability_count": len(BRIDGE_CAPABILITIES),
    }


def main() -> int:
    """Run the repository coverage check."""

    setup_runtime()
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

    from apps.terminal.application.repository_provider import get_tui_metadata_repository

    metadata = get_tui_metadata_repository().load_published()
    summary = validate_tui_action_coverage(
        actions=list(metadata.get("actions") or []),
        registry=CapabilityRegistryLoader().build_registry(),
    )
    print("MCP TUI action coverage OK")
    for key, value in summary.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
