"""T5 runtime-owner contracts for account bulk imports."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

import agomtradepro
from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro_mcp.registry.runtime_handlers.owners import account
from agomtradepro_mcp.tools.account_tools import _list_endpoint_rows


@pytest.fixture
def sdk_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MagicMock]:
    """Install one deterministic SDK client for lazy owner imports."""
    client = MagicMock()
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: client)
    yield client


def test_paginated_account_rows_are_normalized() -> None:
    """The owner-facing helper must support DRF pages, raw lists, and invalid data."""
    client = MagicMock()
    client.get.side_effect = [
        {"results": [{"id": 1}]},
        [{"id": 2}],
        {"results": "invalid"},
    ]
    assert _list_endpoint_rows(client, "positions", limit=10) == [{"id": 1}]
    assert _list_endpoint_rows(client, "positions", limit=10) == [{"id": 2}]
    assert _list_endpoint_rows(client, "positions", limit=10) == []


def test_position_owner_import_reports_validation_and_all_runtime_failures(
    sdk_client: MagicMock,
) -> None:
    """Position replacement must isolate create, update, and close failures."""
    sdk_client.get.return_value = {
        "results": [
            {"id": 1, "portfolio": 7, "asset_code": "UPDATE", "is_closed": False},
            {"id": 2, "portfolio": 7, "asset_code": "CLOSE", "is_closed": False},
            {"id": 3, "portfolio": 8, "asset_code": "OTHER", "is_closed": False},
            {"id": 4, "portfolio": 7, "asset_code": "CLOSED", "is_closed": True},
        ]
    }
    sdk_client.post.side_effect = RuntimeError("post failed")
    sdk_client.patch.side_effect = RuntimeError("patch failed")
    positions = [
        {
            "asset_code": "CREATE",
            "shares": 10,
            "avg_cost": 5,
            "current_price": 6,
            "category": "stock",
            "currency": "CNY",
            "source_id": 8,
        },
        {
            "asset_code": "UPDATE",
            "shares": 20,
            "avg_cost": 4,
            "current_price": 5,
            "is_closed": False,
        },
        {"asset_code": "", "shares": 1, "avg_cost": 1},
    ]

    assert account._fallback_import_positions_json(7, [], mode="bad")["success"] is False
    preview = account._fallback_import_positions_json(7, positions, mode="replace", dry_run=True)
    assert preview["summary"]["create_count"] == 1
    assert preview["summary"]["update_count"] == 1
    assert preview["summary"]["close_count"] == 1

    result = account._fallback_import_positions_json(7, positions, mode="replace", dry_run=False)
    assert result["success"] is False
    assert {item["operation"] for item in result["errors"] if "operation" in item} == {
        "create",
        "update",
        "close",
    }


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("replace", "transaction_import_append_only"),
        ("bad", "transaction_import_mode_unsupported"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_transaction_owner_import_non_append_modes_fail_before_client_or_http(
    sdk_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_code: str,
    dry_run: bool,
) -> None:
    """The owner fallback must reject replacement before constructing its client."""
    client_factory = MagicMock(side_effect=AssertionError("client must not be created"))
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", client_factory)

    with pytest.raises(AgomTradeProAPIError) as caught:
        account._fallback_import_transactions_json(
            7,
            [],
            mode=mode,
            dry_run=dry_run,
        )

    assert caught.value.status_code is None
    assert caught.value.response is not None
    assert caught.value.response["code"] == expected_code
    assert caught.value.response["origin"] == "client_validation"
    client_factory.assert_not_called()
    sdk_client.get.assert_not_called()
    sdk_client.delete.assert_not_called()
    sdk_client.post.assert_not_called()


def test_transaction_owner_append_still_reports_server_create_failure(
    sdk_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Append imports must preserve the existing create-failure details."""
    client_factory = MagicMock(return_value=sdk_client)
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", client_factory)
    sdk_client.post.side_effect = RuntimeError("create failed")
    result = account._fallback_import_transactions_json(
        7,
        [
            {
                "action": "buy",
                "asset_code": "A",
                "shares": 2,
                "price": 3,
                "commission": 0.1,
            }
        ],
        mode="append",
        dry_run=False,
    )

    assert result["success"] is False
    assert result["summary"]["delete_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["errors"] == [
        {"operation": "create", "asset_code": "A", "error": "create failed"}
    ]
    client_factory.assert_called_once_with()
    sdk_client.get.assert_not_called()
    sdk_client.delete.assert_not_called()
    sdk_client.post.assert_called_once()


def test_capital_flow_owner_import_reports_delete_and_create_failures(
    sdk_client: MagicMock,
) -> None:
    """Capital-flow replacement must preserve validation and runtime error details."""
    sdk_client.get.return_value = {
        "results": [
            {"id": 1, "portfolio": 7},
            {"id": 2, "portfolio": 8},
        ]
    }
    sdk_client.delete.side_effect = RuntimeError("delete failed")
    sdk_client.post.side_effect = RuntimeError("create failed")
    flows = [
        {"flow_type": "deposit", "amount": 100, "notes": "seed"},
        {"flow_type": "", "amount": 1},
    ]

    assert account._fallback_import_capital_flows_json(7, [], mode="bad")["success"] is False
    result = account._fallback_import_capital_flows_json(
        7,
        flows,
        mode="replace",
        dry_run=False,
    )
    assert result["success"] is False
    assert result["summary"]["delete_count"] == 1
    assert {item["operation"] for item in result["errors"] if "operation" in item} == {
        "delete",
        "create",
    }


def test_trading_cost_owner_mutations_delegate_all_fields(
    sdk_client: MagicMock,
) -> None:
    """Trading-cost create/update fallbacks must retain explicit false and zero values."""
    sdk_client.account.create_trading_cost_config.return_value = {"id": 1}
    sdk_client.account.update_trading_cost_config.return_value = {
        "id": 1,
        "is_active": False,
    }
    assert (
        account._fallback_create_trading_cost_config(
            7,
            commission_rate=0.0,
            min_commission=0.0,
            stamp_duty_rate=0.0,
            transfer_fee_rate=0.0,
        )["id"]
        == 1
    )
    assert (
        account._fallback_update_trading_cost_config(
            1,
            commission_rate=0.0,
            min_commission=0.0,
            stamp_duty_rate=0.0,
            transfer_fee_rate=0.0,
            is_active=False,
        )["is_active"]
        is False
    )
