"""Tests for the published TUI action MCP coverage guard."""

from types import SimpleNamespace

import pytest

from scripts.check_mcp_tui_action_coverage import validate_tui_action_coverage


def _registry():
    return {
        "terminal.search.user_actions": SimpleNamespace(requires_confirmation=False),
        "terminal.read.user_action_schema": SimpleNamespace(requires_confirmation=False),
        "terminal.read.user_action_result": SimpleNamespace(requires_confirmation=False),
        "terminal.execute.user_action": SimpleNamespace(
            requires_confirmation=True,
            idempotency="required",
        ),
    }


def test_validate_tui_action_coverage_classifies_every_published_action():
    summary = validate_tui_action_coverage(
        actions=[
            {"key": "account.positions", "risk": "read"},
            {"key": "account.position.create", "risk": "write"},
            {"key": "ai.analysis.run", "risk": "ai"},
            {"key": "system.setting.update", "risk": "admin"},
        ],
        registry=_registry(),
    )

    assert summary["published_action_count"] == 4
    assert summary["read_bridge_count"] == 1
    assert summary["confirmed_bridge_count"] == 3


def test_validate_tui_action_coverage_rejects_unroutable_action_key():
    with pytest.raises(ValueError, match="unsupported action keys"):
        validate_tui_action_coverage(
            actions=[{"key": "unsafe/action", "risk": "read"}],
            registry=_registry(),
        )
