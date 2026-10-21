"""TUI projection contracts for the retained signal-status endpoint."""

from __future__ import annotations

from typing import Any

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_runtime_injection_signal import (
    RUNTIME_SIGNAL_ACTIONS,
)


class _SignalMetadataRepository:
    def load_published(self, registry_key: str = "default") -> dict[str, Any]:
        return {}


class _SignalProjectionService(TuiWorkbenchService):
    def _resolve_asset_names(self, codes: list[str]) -> dict[str, str]:
        return {}


def _signal_action(key: str) -> dict[str, Any]:
    return next(action for action in RUNTIME_SIGNAL_ACTIONS if action["key"] == key)


def test_signal_status_actions_keep_read_only_user_scope_and_explicit_rows() -> None:
    actions = {
        action["key"]: action
        for action in RUNTIME_SIGNAL_ACTIONS
        if action["key"]
        in {
            "dashboard.signal-status-distribution",
            "dashboard.signal-status-recent",
        }
    }

    assert set(actions) == {
        "dashboard.signal-status-distribution",
        "dashboard.signal-status-recent",
    }
    for action in actions.values():
        assert action["endpoint"] == "/api/dashboard/v1/signal-status/"
        assert action["method"] == "GET"
        assert action["risk"] == "read"
        assert action["audience"] == "authenticated"
        assert action["effect"] == "read"
        assert action["screen_key"] == "research.signals"
        assert action.get("confirmation_required", False) is False
        assert action["fields"] == [
            {
                "key": "limit",
                "label": "返回数量",
                "input_type": "hidden",
                "required": False,
                "default": "5",
                "binding": "query",
                "value_type": "integer",
            }
        ]

    distribution = actions["dashboard.signal-status-distribution"]
    assert distribution["view_model"] == {
        "kind": "chart",
        "chart_type": "bar",
        "rows_path": "stats_series",
        "columns": [
            {"key": "status", "label": "信号状态"},
            {"key": "count", "label": "信号数量"},
        ],
        "empty_message": "暂无投资信号统计。",
    }
    assert actions["dashboard.signal-status-recent"]["view_model"] == {
        "kind": "datagrid",
        "rows_path": "signals",
        "columns": [
            {"key": "asset_code", "label": "标的代码"},
            {"key": "asset_name", "label": "标的名称"},
            {"key": "direction", "label": "方向"},
            {"key": "status", "label": "状态"},
            {"key": "logic_desc", "label": "投资逻辑"},
            {"key": "created_at", "label": "创建日期"},
        ],
        "empty_message": "当前没有已批准信号。",
    }

    existing_mutation = _signal_action("signal.approve")
    assert existing_mutation["risk"] == "admin"
    assert existing_mutation["confirmation_required"] is True


def test_signal_status_payload_projects_stats_series_and_recent_rows() -> None:
    projector = _SignalProjectionService(metadata_repository=_SignalMetadataRepository())
    payload = {
        "stats": {"total": 4, "approved": 2, "pending": 1, "rejected": 1},
        "stats_series": [
            {"status": "全部", "count": 4},
            {"status": "已批准", "count": 2},
            {"status": "待审核", "count": 1},
            {"status": "已拒绝", "count": 1},
        ],
        "signals": [
            {
                "asset_code": "600000.SH",
                "asset_name": "浦发银行",
                "direction": "LONG",
                "status": "approved",
                "logic_desc": "合成回归样本",
                "created_at": "2026-10-21",
            }
        ],
        "limit": 5,
    }

    chart = projector._to_view_model(
        action=_signal_action("dashboard.signal-status-distribution"),
        payload=payload,
        status_code=200,
    )
    assert chart["kind"] == "chart"
    assert chart["chart_type"] == "bar"
    assert chart["source_row_count"] == 4
    assert chart["point_count"] == 4
    assert chart["series"] == [
        {
            "key": "count",
            "label": "信号数量",
            "points": [
                {"label": "全部", "value": 4.0},
                {"label": "已批准", "value": 2.0},
                {"label": "待审核", "value": 1.0},
                {"label": "已拒绝", "value": 1.0},
            ],
        }
    ]

    grid = projector._to_view_model(
        action=_signal_action("dashboard.signal-status-recent"),
        payload=payload,
        status_code=200,
        request_params={"limit": 5},
    )
    assert grid["kind"] == "datagrid"
    assert grid["pager"]["total_rows"] == 1
    assert grid["rows"][0]["asset_code"].startswith("600000.SH")
    assert grid["rows"][0]["asset_name"] == "浦发银行"
    assert grid["rows"][0]["logic_desc"] == "合成回归样本"
