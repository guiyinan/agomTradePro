"""Metadata and portable chart contracts for the two-portfolio comparison screen."""

from copy import deepcopy
from typing import Any, cast

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.infrastructure.tui_metadata_runtime_injection_portfolio_comparison import (
    RUNTIME_PORTFOLIO_COMPARISON_ACTIONS,
    RUNTIME_PORTFOLIO_COMPARISON_SCREEN,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_registry import (
    RUNTIME_METADATA_INJECTIONS,
)
from tests.unit.test_tui_workbench import _metadata_payload


def _metadata() -> dict[str, Any]:
    screen = deepcopy(RUNTIME_PORTFOLIO_COMPARISON_SCREEN)
    screen.update(
        {
            "label": "双组合对比",
            "module_key": "daily-decisions",
            "group": "daily",
            "audience": "authenticated",
            "summary": "对比两个组合的绩效与持仓。",
            "view_type": "table_chart",
            "status": "online",
            "default_action_key": "portfolio-comparison.metrics",
            "user_experience": {
                "journey": "dashboard",
                "primary_task": "选择两个组合并完成对比。",
                "primary_outcome": "得到绩效、曲线、持仓和行业差异。",
                "empty_state_hint": "先选择两个组合。",
                "next_step_hint": "核对未知数据和当前持仓口径。",
            },
        }
    )
    payload = _metadata_payload(
        screens=[screen],
        actions=list(deepcopy(RUNTIME_PORTFOLIO_COMPARISON_ACTIONS)),
    )
    return cast(dict[str, Any], validate_tui_metadata(payload))


def test_comparison_screen_has_one_task_and_portable_chart() -> None:
    metadata = _metadata()
    screen = metadata["screens"][0]
    assert screen["default_action_key"] == "portfolio-comparison.metrics"
    assert screen["user_experience"]["primary_task"]
    assert {panel["key"] for panel in screen["dashboard_panels"]} == {
        "portfolio-comparison-accounts",
        "portfolio-comparison-performance",
        "portfolio-comparison-holdings",
        "portfolio-comparison-industries",
    }

    actions = {action["key"]: action for action in metadata["actions"]}
    performance = actions["portfolio-comparison.metrics"]
    assert performance["risk"] == "read"
    assert performance["view_model"]["kind"] == "table_chart"
    assert performance["view_model"]["chart_rows_path"] == "curve"
    assert performance["view_model"]["table_rows_path"] == "metrics"
    assert [field["key"] for field in performance["fields"]] == [
        "left_account_id",
        "right_account_id",
        "start_date",
        "end_date",
    ]
    holdings = actions["portfolio-comparison.holdings"]["view_model"]
    assert holdings["table_rows_path"] == "holdings.rows"
    assert holdings["chart_rows_path"] == "holdings.overlap_rows"
    assert holdings["chart_columns"][1]["key"] == "overlap_percentage"
    assert actions["portfolio-comparison.industries"]["view_model"]["rows_path"] == (
        "holdings.industry_rows"
    )


def test_comparison_runtime_bundle_is_registered_once() -> None:
    bundles = [
        bundle
        for bundle in RUNTIME_METADATA_INJECTIONS
        if bundle.coverage_key == "runtime_injected_portfolio_comparison_metadata"
    ]
    assert len(bundles) == 1
    assert bundles[0].screens[0]["key"] == "task.portfolio-comparison"
    assert len(bundles[0].actions) == 4
    assert all(action["risk"] == "read" for action in bundles[0].actions)
