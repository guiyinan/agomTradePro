"""Runtime metadata contracts for the dedicated calendar workbench screen."""

from __future__ import annotations

from typing import Any

from apps.terminal.infrastructure.tui_information_architecture import (
    load_tui_information_architecture,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_registry import (
    RUNTIME_METADATA_INJECTIONS,
)

SCREEN_KEY = "data-center.calendar-workbench"
ACTION_PREFIX = "data-center.calendar-workbench-"
CONFIRM_ACTION_KEY = "data-center.calendar-workbench-confirm"


def _runtime_actions() -> dict[str, dict[str, Any]]:
    """Return runtime-injected actions keyed by their canonical key."""

    return {
        str(action["key"]): action
        for bundle in RUNTIME_METADATA_INJECTIONS
        for action in bundle.actions
    }


def test_calendar_workbench_is_a_dedicated_admin_task_screen() -> None:
    """The IA must define the dedicated screen before runtime injection is useful."""

    ia = load_tui_information_architecture()
    screen = next(
        (item for item in ia["runtime_screens"] if item["key"] == SCREEN_KEY),
        None,
    )

    assert screen is not None
    assert screen["module_key"] == "system-governance"
    assert screen["group"] == "system"
    assert screen["audience"] == "admin"
    assert screen["default_action_key"] == f"{ACTION_PREFIX}scope"
    assert screen["dashboard_layout"] == "task_flow"
    assert screen["user_experience"]["journey"] == "admin"
    assert screen["user_experience"]["primary_task"]
    assert screen["user_experience"]["primary_outcome"]
    assert screen["user_experience"]["empty_state_hint"]
    assert screen["user_experience"]["next_step_hint"]


def test_calendar_workbench_runtime_actions_are_exact_and_session_protected() -> None:
    """Expose only the four owner actions with their strict request shapes."""

    actions = _runtime_actions()
    expected_keys = {
        f"{ACTION_PREFIX}scope",
        f"{ACTION_PREFIX}current",
        f"{ACTION_PREFIX}prepare",
        CONFIRM_ACTION_KEY,
    }
    assert expected_keys <= set(actions)

    for key in expected_keys:
        action = actions[key]
        assert action["screen_key"] == SCREEN_KEY
        assert action["session_auth_required"] is True
        assert action["audience"] == "admin"
        assert action["raw_debug"] is False
        assert "/api/" not in action["label"]
        assert "/api/" not in action["description"]

    scope = actions[f"{ACTION_PREFIX}scope"]
    assert scope["method"] == "GET"
    assert scope["endpoint"] == "/api/data-center/exchange-calendars/workbench/scope/"
    assert scope["effect"] == "read"
    assert scope["fields"] == []
    assert scope["view_model"] == {"kind": "message"}

    current = actions[f"{ACTION_PREFIX}current"]
    assert current["method"] == "GET"
    assert current["endpoint"] == "/api/data-center/exchange-calendars/workbench/current/"
    assert current["view_model"] == {
        "kind": "datagrid",
        "rows_path": "current.calendar_days",
        "columns": [
            {"key": "calendar_date", "label": "日期"},
            {"key": "calendar_state", "label": "状态"},
            {"key": "previous_open_date", "label": "前一开市日"},
        ],
    }
    assert [(field["key"], field["binding"], field["required"]) for field in current["fields"]] == [
        ("exchange", "query", True),
    ]
    assert all("default" not in field for field in current["fields"])
    assert all("options" not in field for field in current["fields"])

    prepare = actions[f"{ACTION_PREFIX}prepare"]
    assert prepare["method"] == "POST"
    assert prepare["endpoint"] == "/api/data-center/exchange-calendars/workbench/prepare/"
    assert prepare["confirmation_required"] is True
    assert prepare["audit_required"] is True
    assert prepare["effect"] == "create"
    assert [field["key"] for field in prepare["fields"]] == [
        "exchange",
        "coverage_start",
        "coverage_end",
    ]
    assert all(field["required"] is True for field in prepare["fields"])
    assert all("default" not in field for field in prepare["fields"])
    assert all("options" not in field for field in prepare["fields"])
    assert prepare["result_continuation"] == {
        "target_action_key": CONFIRM_ACTION_KEY,
        "field_map": {"confirmation_token": "confirmation_token"},
    }

    confirm = actions[CONFIRM_ACTION_KEY]
    assert confirm["method"] == "POST"
    assert confirm["endpoint"] == "/api/data-center/exchange-calendars/workbench/confirm/"
    assert confirm["confirmation_required"] is True
    assert confirm["audit_required"] is True
    assert confirm["effect"] == "create"
    assert confirm["fields"] == [
        {
            "key": "confirmation_token",
            "label": "发布确认",
            "binding": "body",
            "input_type": "hidden",
            "value_type": "string",
            "required": True,
            "presentation_semantic": "api_token",
        }
    ]


def test_calendar_workbench_screen_has_p0_scope_and_current_panels() -> None:
    """The first screenful must expose configuration and explicit current lookup."""

    screen_fragments = [
        screen
        for bundle in RUNTIME_METADATA_INJECTIONS
        for screen in bundle.screens
        if screen.get("key") == SCREEN_KEY
    ]
    assert len(screen_fragments) == 1
    panels = {str(panel["key"]): panel for panel in screen_fragments[0]["dashboard_panels"]}
    assert panels["calendar-capture-scope"]["user_priority"] == "p0"
    assert panels["calendar-capture-scope"]["kind"] == "detail"
    assert panels["calendar-capture-scope"]["action_key"] == f"{ACTION_PREFIX}scope"
    assert panels["calendar-current-reference"]["user_priority"] == "p0"
    assert panels["calendar-current-reference"]["kind"] == "datagrid"
    assert panels["calendar-current-reference"]["action_key"] == f"{ACTION_PREFIX}current"
    assert "SSE" not in str(panels)
    current_empty_message = panels["calendar-current-reference"]["empty_message"]
    assert "交易所标识" in current_empty_message
    assert "无当前版本" in current_empty_message
