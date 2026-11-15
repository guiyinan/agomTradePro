"""Contract tests for the private institutional-calendar TUI metadata slice."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from apps.terminal.application.tui_institutional_calendar_result import (
    project_institutional_calendar_context,
)


@pytest.fixture(scope="module")
def metadata() -> ModuleType:
    """Load the isolated metadata module without importing the formal tree copy."""

    repository_root = Path(__file__).resolve().parents[3]
    module_path = (
        repository_root
        / "apps"
        / "terminal"
        / "infrastructure"
        / "tui_metadata_runtime_injection_institutional_calendar.py"
    )
    spec = importlib.util.spec_from_file_location(
        "private_tui_institutional_calendar_metadata", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_action_is_an_authenticated_read_with_required_clock_and_range(
    metadata: ModuleType,
) -> None:
    action = metadata.RUNTIME_INSTITUTIONAL_CALENDAR_ACTION

    assert action["endpoint"] == "/api/data-center/institutional-calendar/"
    assert action["method"] == "GET"
    assert action["risk"] == "read"
    assert action["effect"] == "read"
    assert action["audience"] == "authenticated"
    assert action["session_auth_required"] is True
    assert action["raw_debug"] is False

    fields = {field["key"]: field for field in action["fields"]}
    assert set(fields) == {"date_from", "date_to", "known_at", "mode", "event_type", "lifecycle"}
    for key in ("date_from", "date_to", "known_at", "mode"):
        assert fields[key]["required"] is True
        assert "default" not in fields[key]
    assert fields["date_from"]["value_type"] == "date"
    assert fields["date_to"]["value_type"] == "date"
    assert fields["date_from"]["binding"] == "query"
    assert fields["date_to"]["binding"] == "query"
    assert fields["known_at"]["input_type"] == "text"
    assert "UTC" in fields["known_at"]["label"]
    assert "时区" in fields["known_at"]["label"]
    assert fields["mode"]["options"] == [
        {"value": "system_known", "label": "系统当时已知"},
        {"value": "market_available", "label": "市场当时可得"},
    ]
    assert fields["event_type"]["required"] is False
    assert fields["lifecycle"]["required"] is False


def test_grid_displays_the_single_generic_rows_projection(metadata: ModuleType) -> None:
    action = metadata.RUNTIME_INSTITUTIONAL_CALENDAR_ACTION
    panel = metadata.RUNTIME_INSTITUTIONAL_CALENDAR_PANEL
    columns = [column["key"] for column in action["view_model"]["columns"]]

    assert action["view_model"]["kind"] == "datagrid"
    assert action["view_model"]["rows_path"] == "rows"
    assert panel["action_key"] == action["key"]
    assert panel["user_priority"] == "p0"
    assert panel["columns"] == action["view_model"]["columns"]
    assert {
        "row_kind",
        "event_on",
        "end_date",
        "title",
        "evidence_label",
        "lifecycle_label",
        "source_status",
        "source_url",
        "attribution",
        "known_at",
        "knowledge_mode",
        "revision",
        "research_status",
    } <= set(columns)


def test_boundary_copy_is_always_visible_and_does_not_trigger_a_query(
    metadata: ModuleType,
) -> None:
    screen = metadata.RUNTIME_INSTITUTIONAL_CALENDAR_SCREEN_FRAGMENT
    panels = {panel["key"]: panel for panel in screen["dashboard_panels"]}
    boundary = panels["institutional-calendar-boundary"]

    assert screen["key"] == "research.institutional-calendar"
    assert screen["chrome_mode"] == "immersive"
    assert screen["dashboard_layout"] == "task_flow"
    assert set(panels) == {
        "institutional-calendar-boundary",
        "institutional-calendar-rows",
    }
    assert (
        panels["institutional-calendar-rows"]["action_key"]
        == metadata.RUNTIME_INSTITUTIONAL_CALENDAR_ACTION["key"]
    )
    assert panels["institutional-calendar-rows"]["user_priority"] == "p0"
    assert boundary["user_priority"] == "p0"
    assert "暂定" in boundary["empty_message"]
    assert "原件" in boundary["empty_message"]
    assert "尚未完成" in boundary["empty_message"]
    assert "仅供参考" in boundary["empty_message"]
    assert "不用于投资或交易决策" in boundary["empty_message"]
    assert "未覆盖类别" in boundary["empty_message"]
    assert "action_key" not in boundary


def test_result_header_keeps_knowledge_clock_source_gaps_and_research_limit() -> None:
    projected = project_institutional_calendar_context(
        {
            "status": {
                "known_at": "2026-11-15T01:00:00+00:00",
                "knowledge_mode": "系统已知重放",
                "gaps": "对应原文缺失",
                "research_status": "研究未完成，不可用于决策",
                "must_not_use_for_decision": True,
            }
        }
    )
    assert projected["outcome"] == "partial"
    assert "2026-11-15T01:00:00+00:00" in projected["business_summary"]
    assert "系统已知重放" in projected["business_summary"]
    assert "原文缺失" in projected["business_summary"]
    assert projected["blocking_reason"] == "研究未完成，不可用于决策"
    assert project_institutional_calendar_context({})["outcome"] == "blocked"
    assert (
        project_institutional_calendar_context({"status": {"known_at": "unknown"}})["outcome"]
        == "blocked"
    )
