"""Failure-first consumer tests for published equity-pool partial responses.

The TUI assertions target the existing application view-model seam and do not
claim browser verification. Network responses are explicit consumer fixtures.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


def _partial_pool_payload() -> dict[str, Any]:
    """Return a two-row partial envelope with a valuation-only local block."""

    blocked_row: dict[str, Any] = {
        "code": "000001.SZ",
        "name": "平安银行",
        "sector": "银行",
        "roe": 12.5,
        "pe": None,
        "pb": None,
        "revenue_growth": 8.0,
        "profit_growth": 6.0,
        "score": None,
        "status": "partial",
        "status_label": "估值资料受限",
        "must_not_use_for_decision": True,
        "blocked_datasets": ["equity.valuation.fact"],
        "blocked_reason": "valuation_source_data_unavailable",
        "restriction_message": "该股票估值资料受限，仍保留在列表中；请仅作观察。",
        "publication_gates": {
            "valuation": {
                "dataset_key": "equity.valuation.fact",
                "publication_id": "valuation-current-1",
                "scope_block": {
                    "asset_code": "000001.SZ",
                    "publication_id": "valuation-current-1",
                    "reason_code": "valuation_source_data_unavailable",
                },
            }
        },
        "source_times": {
            "financial": {"roe": {"available_at": None, "fetched_at": "2026-10-18T08:00:05+00:00"}},
            "valuation": {"observed_at": None, "available_at": None, "fetched_at": None},
        },
    }
    healthy_row: dict[str, Any] = {
        "code": "000002.SZ",
        "name": "万科A",
        "sector": "房地产",
        "roe": 10.0,
        "pe": 10.0,
        "pb": 1.0,
        "revenue_growth": 4.0,
        "profit_growth": 3.0,
        "score": None,
        "status": "published",
        "status_label": "资料已发布",
        "must_not_use_for_decision": False,
        "blocked_datasets": [],
        "blocked_reason": None,
        "restriction_message": None,
        "publication_gates": {
            "valuation": {
                "dataset_key": "equity.valuation.fact",
                "publication_id": "valuation-current-1",
                "scope_block": None,
            }
        },
        "source_times": {
            "financial": {"roe": {"available_at": "2026-10-18T08:00:00+00:00"}},
            "valuation": {"observed_at": "2026-10-18T08:00:00+00:00"},
        },
    }
    return {
        "success": True,
        "status": "partial",
        "outcome": "partial",
        "mode": "published",
        "publication_key": "current",
        "regime": "Recovery",
        "update_time": "2026-10-18T08:01:00+00:00",
        "count": 2,
        "requested_count": 2,
        "blocked_count": 1,
        "must_not_use_for_decision": True,
        "restriction_message": "估值资料有 1/2 只股票受限；股票池仅供观察，不能直接用于决策。",
        "avg_roe": 11.25,
        "avg_pe": None,
        "aggregate_coverage": {
            "avg_roe": {"known_count": 2, "requested_count": 2},
            "avg_pe": {"known_count": 1, "requested_count": 2},
        },
        "stocks": [blocked_row, healthy_row],
        "sector_distribution": [
            {"sector": "房地产", "count": 1},
            {"sector": "银行", "count": 1},
        ],
        "publication_gates": {
            "equity.financial.fact": {"publication_id": "financial-current-1"},
            "equity.valuation.fact": {"publication_id": "valuation-current-1"},
        },
        "blocked_reason": None,
    }


def test_sdk_pool_preserves_partial_envelope_and_requested_scope() -> None:
    """The SDK must not turn a partial pool into an unqualified success envelope."""

    from agomtradepro import AgomTradeProClient

    payload = _partial_pool_payload()
    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    with patch.object(client, "get", return_value=deepcopy(payload)) as get:
        result = client.equity.get_stock_pool(mode="published", publication_key="current", limit=10)

    assert result["success"] is True
    assert result["outcome"] == "partial"
    assert result["status"] == "partial"
    assert result["must_not_use_for_decision"] is True
    assert result["requested_count"] == 2
    assert result["blocked_count"] == 1
    assert result["aggregate_coverage"] == payload["aggregate_coverage"]
    assert result["restriction_message"] == payload["restriction_message"]
    assert result["total_count"] == 2  # SDK-selected count remains separate.
    assert result["stocks"] == payload["stocks"]
    assert [row["code"] for row in result["stocks"]] == ["000001.SZ", "000002.SZ"]
    assert result["stocks"][0]["pe"] is None
    assert result["stocks"][0]["status_label"] == "估值资料受限"
    assert result["stocks"][0]["restriction_message"]
    get.assert_called_once_with(
        "/api/equity/pool/",
        params={"mode": "published", "publication_key": "current"},
    )


def test_sdk_legacy_list_rejects_partial_pool_and_directs_to_complete_payload() -> None:
    """A bare list cannot represent a restricted pool even if it retains row flags."""
    from agomtradepro import AgomTradeProClient
    from agomtradepro.exceptions import AgomTradeProAPIError

    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    payload = _partial_pool_payload()
    with patch.object(client.equity, "get_stock_pool", return_value=payload):
        with pytest.raises(AgomTradeProAPIError, match="get_stock_pool_payload") as error:
            client.equity.list_stocks(limit=10)

    assert error.value.code == "equity_pool_not_decision_usable"
    assert error.value.status_code is None
    assert error.value.response == payload


def test_mcp_pool_schema_declares_optional_partial_envelope_fields() -> None:
    """MCP clients need a documented shape without breaking old full responses."""

    from agomtradepro_mcp.registry.modules.owners.equity_read_capabilities import MANIFESTS

    manifest = next(item for item in MANIFESTS if item.capability_key == "equity.read.pool_catalog")
    schema = manifest.output_schema
    properties = schema["properties"]
    new_partial_fields = {
        "outcome",
        "requested_count",
        "blocked_count",
        "aggregate_coverage",
        "restriction_message",
    }

    assert new_partial_fields <= properties.keys()
    assert not new_partial_fields.intersection(schema.get("required", []))


def test_mcp_equity_pool_fallback_returns_sdk_envelope_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The owner fallback must not rebuild or drop SDK pool evidence."""

    import agomtradepro
    from agomtradepro_mcp.server import INTERNAL_LEGACY_TOOL_FALLBACKS

    payload = _partial_pool_payload()
    equity = SimpleNamespace(get_stock_pool_payload=lambda **_kwargs: payload)
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: SimpleNamespace(equity=equity))

    result = INTERNAL_LEGACY_TOOL_FALLBACKS["equity_read_pool_catalog"](
        limit=20,
        mode="published",
        publication_key="current",
    )

    assert result is payload
    assert result["outcome"] == "partial"
    assert result["requested_count"] == 2
    assert result["blocked_count"] == 1
    assert result["stocks"][0]["restriction_message"]


def test_tui_pool_summary_keeps_warning_and_counts_in_initial_view_fields() -> None:
    """The summary view should surface the observation warning before overflow."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_equity_analytics import (
        RUNTIME_EQUITY_ANALYTICS_ACTIONS,
    )

    service = TuiWorkbenchService(metadata_repository=SimpleNamespace())
    payload = _partial_pool_payload()
    action = next(
        item for item in RUNTIME_EQUITY_ANALYTICS_ACTIONS if item["key"] == "equity.pool-summary"
    )

    model = service._to_view_model(action=action, payload=payload, status_code=200)
    first_screen_fields = model["fields"][:8]
    first_screen = "；".join(field["value"] for field in first_screen_fields)

    assert model["status"] == "不可用于决策"
    assert "1/2" in first_screen
    assert "仅供观察" in first_screen
    assert "valuation_source_data_unavailable" not in first_screen
    assert "outcome" not in {field["key"] for field in first_screen_fields}
    assert {"requested_count", "blocked_count"} <= {field["key"] for field in first_screen_fields}


def test_tui_pool_rows_keep_status_and_readable_restriction_without_raw_reason_column() -> None:
    """The visible grid must retain both rows and show the local restriction plainly."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_equity_analytics import (
        RUNTIME_EQUITY_ANALYTICS_ACTIONS,
    )

    service = TuiWorkbenchService(metadata_repository=SimpleNamespace())
    payload = _partial_pool_payload()
    action = next(
        item for item in RUNTIME_EQUITY_ANALYTICS_ACTIONS if item["key"] == "equity.pool-list"
    )

    model = service._to_view_model(action=action, payload=payload, status_code=200)

    assert model["status"] == "不可用于决策"
    assert model["pager"]["total_rows"] == 2
    assert [row["code"] for row in model["rows"]] == ["000001.SZ 平安银行", "000002.SZ 万科A"]
    assert model["rows"][0]["status_label"] == "估值资料受限"
    assert model["rows"][0]["restriction_message"] == payload["stocks"][0]["restriction_message"]
    assert model["rows"][0]["pe"] == "-"
    assert "blocked_reason" not in {column["key"] for column in model["columns"]}
    assert "valuation_source_data_unavailable" not in repr(model["rows"][0])


def test_tui_pool_metadata_exposes_readable_restriction_columns() -> None:
    """The real pool-list metadata must select the user-facing row fields."""

    from apps.terminal.infrastructure.tui_metadata_runtime_injection_equity_analytics import (
        RUNTIME_EQUITY_ANALYTICS_ACTIONS,
    )

    action = next(
        item for item in RUNTIME_EQUITY_ANALYTICS_ACTIONS if item["key"] == "equity.pool-list"
    )
    columns = action["view_model"]["columns"]
    column_keys = {column["key"] for column in columns}

    assert {"status_label", "restriction_message"} <= column_keys
    assert "blocked_reason" not in column_keys


def test_tui_full_success_and_global_block_keep_distinct_user_outcomes() -> None:
    """A full pool stays ordinary success; a global failure is never a partial list."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    service = TuiWorkbenchService(metadata_repository=SimpleNamespace())
    detail_action = {
        "key": "equity.pool-summary",
        "label": "股票池摘要",
        "view_type": "detail",
        "view_model": {"kind": "detail"},
    }
    full = _partial_pool_payload()
    full.update(
        {
            "outcome": "success",
            "status": "published",
            "must_not_use_for_decision": False,
            "blocked_count": 0,
            "restriction_message": None,
            "avg_pe": 8.5,
            "aggregate_coverage": {
                "avg_roe": {"known_count": 2, "requested_count": 2},
                "avg_pe": {"known_count": 2, "requested_count": 2},
            },
        }
    )
    full["stocks"] = [
        dict(
            row,
            status="published",
            status_label="资料已发布",
            must_not_use_for_decision=False,
            blocked_datasets=[],
            blocked_reason=None,
            restriction_message=None,
            pe=8.5,
            pb=1.0,
        )
        for row in full["stocks"]
    ]
    full_model = service._to_view_model(action=detail_action, payload=full, status_code=200)

    blocked = {
        "success": False,
        "status": "blocked",
        "outcome": "blocked",
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
        "stocks": [],
        "count": 0,
        "requested_count": 2,
        "blocked_count": 2,
        "restriction_message": "当前股票池资料不可用，请稍后重试。",
    }
    blocked_model = service._to_view_model(
        action={
            **detail_action,
            "view_type": "datagrid",
            "view_model": {
                "kind": "datagrid",
                "rows_path": "stocks",
                "columns": [{"key": "code", "label": "股票代码"}],
            },
        },
        payload=blocked,
        status_code=200,
    )

    assert full_model["status"] == "已读取"
    assert "资料已发布" in full_model["business_summary"]
    assert "2 只股票" in full_model["business_summary"]
    assert "published" not in full_model["business_summary"]
    assert "outcome" not in full_model["business_summary"]
    assert "仅供观察" not in "；".join(field["value"] for field in full_model["fields"])
    assert blocked_model["status"] in {"已阻断", "不可用于决策"}
    assert blocked_model["rows"] == []


@pytest.mark.parametrize("selection", [{"sector": "房地产"}, {"limit": 1}])
def test_sdk_selection_keeps_server_scope_coverage(selection: dict[str, Any]) -> None:
    """Selecting fewer rows cannot rebase the source pool's coverage denominator."""

    from agomtradepro import AgomTradeProClient

    payload = _partial_pool_payload()
    original = deepcopy(payload)
    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    with patch.object(client, "get", return_value=payload):
        result = client.equity.get_stock_pool(**selection)
    assert result["total_count"] == 1
    assert result["requested_count"] == 2
    assert result["blocked_count"] == 1
    assert result["aggregate_coverage"]["avg_pe"] == {"known_count": 1, "requested_count": 2}
    assert result["outcome"] == "partial"
    assert result["must_not_use_for_decision"] is True
    assert result["avg_pe"] is None
    assert payload == original


@pytest.mark.parametrize("count", [None, True, -1, "2"])
def test_tui_unknown_count_is_not_displayed_as_zero(count: object) -> None:
    """Unavailable or invalid counters stay visibly unknown."""

    from apps.terminal.application.tui_equity_pool_result import project_equity_pool_view_model

    payload = _partial_pool_payload()
    payload.update(requested_count=count, blocked_count=count)
    original = deepcopy(payload)
    model = project_equity_pool_view_model(
        action_key="equity.pool-summary",
        payload=payload,
        view_model={"kind": "detail", "fields": []},
        http_status=200,
    )
    fields = {field["key"]: field["value"] for field in model["fields"]}
    assert fields["requested_count"] == fields["blocked_count"] == "未提供"
    assert payload == original


def test_tui_known_zero_remains_zero() -> None:
    """A known empty count must remain distinguishable from absent evidence."""

    from apps.terminal.application.tui_equity_pool_result import project_equity_pool_view_model

    payload = _partial_pool_payload()
    payload.update(requested_count=0, blocked_count=0)
    model = project_equity_pool_view_model(
        action_key="equity.pool-summary",
        payload=payload,
        view_model={"kind": "detail", "fields": []},
        http_status=200,
    )
    fields = {field["key"]: field["value"] for field in model["fields"]}
    assert fields["requested_count"] == fields["blocked_count"] == "0"


@pytest.mark.parametrize(
    ("action_key", "mode", "http_status"),
    [
        ("equity.screen-stocks", "published", 200),
        ("equity.pool-summary", "historical", 200),
        ("equity.pool-summary", "published", 503),
    ],
)
def test_pool_projection_preserves_other_result_paths(
    action_key: str,
    mode: str,
    http_status: int,
) -> None:
    """Other actions, historical reads and transport failures keep their models."""

    from apps.terminal.application.tui_equity_pool_result import project_equity_pool_view_model

    payload = _partial_pool_payload()
    payload["mode"] = mode
    model = {"status": "既有状态", "fields": [{"key": "kept", "value": "保留"}]}
    original = deepcopy(model)
    result = project_equity_pool_view_model(
        action_key=action_key,
        payload=payload,
        view_model=model,
        http_status=http_status,
    )
    assert result == original
    assert model == original


@pytest.mark.parametrize("outcome", [None, "unknown", "success"])
def test_tui_uncertain_restricted_pool_uses_generic_safe_copy(outcome: str | None) -> None:
    """Incomplete or contradictory status evidence cannot expose raw owner metadata."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    payload = _partial_pool_payload()
    payload.update(outcome=outcome, restriction_message=None)
    service = TuiWorkbenchService(metadata_repository=SimpleNamespace())
    action = {
        "key": "equity.pool-summary",
        "label": "股票池摘要",
        "view_type": "detail",
        "view_model": {"kind": "detail"},
    }
    model = service._to_view_model(action=action, payload=payload, status_code=200)
    assert model["status"] == "不可用于决策"
    assert model["must_not_use_for_decision"] is True
    assert "状态无法确认" in model["business_summary"]
    assert "valuation_source_data_unavailable" not in repr(model["fields"])
    assert "publication_gates" not in repr(model["fields"])
    assert "部分估值资料不可用" not in model["business_summary"]
