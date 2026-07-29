"""T5 boundary contracts for the extended account MCP tools."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from agomtradepro_mcp.tools import account_tools

Tool = Callable[..., Any]


class _CapturingServer:
    """Minimal FastMCP-compatible registrar used to invoke nested tools directly."""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def tool(self) -> Callable[[Tool], Tool]:
        """Capture a registered function without applying transport wrappers."""

        def decorator(function: Tool) -> Tool:
            self.tools[function.__name__] = function
            return function

        return decorator


@pytest.fixture
def account_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[dict[str, Tool], MagicMock]]:
    """Register account tools against a deterministic SDK client double."""
    client = MagicMock()
    server = _CapturingServer()
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    account_tools.register_account_tools(server)  # type: ignore[arg-type]
    yield server.tools, client


def test_account_input_helpers_cover_valid_and_invalid_boundaries() -> None:
    """Normalization helpers must reject malformed user imports precisely."""
    assert account_tools._extract_results({"results": [{"id": 1}]}) == [{"id": 1}]
    assert account_tools._extract_results([{"id": 2}]) == [{"id": 2}]
    assert account_tools._extract_results({"results": "wrong"}) == []
    assert account_tools._extract_results("wrong") == []

    assert account_tools._parse_bool(None, default=True) is True
    assert account_tools._parse_bool(False) is False
    assert account_tools._parse_bool(" YES ") is True
    assert account_tools._parse_bool("no") is False

    with pytest.raises(ValueError, match="不能为空"):
        account_tools._to_float("", "amount")
    with pytest.raises(ValueError, match="必须是数字"):
        account_tools._to_float("bad", "amount")
    assert account_tools._to_float("1.25", "amount") == 1.25

    normalized = account_tools._normalize_position_input(
        {
            "asset_code": " 000001.SZ ",
            "shares": "100",
            "avg_cost": "10",
            "current_price": "11",
            "category": "stock",
            "currency": "CNY",
            "source_id": "7",
            "is_closed": "true",
        }
    )
    assert normalized["asset_code"] == "000001.SZ"
    assert normalized["source_id"] == 7
    assert normalized["is_closed"] is True
    assert normalized["asset_class"] == "equity"

    invalid_positions = [
        {"shares": 1, "avg_cost": 1},
        {"asset_code": "A", "shares": "", "avg_cost": 1},
        {"asset_code": "A", "shares": 0, "avg_cost": 1},
        {"asset_code": "A", "shares": 1, "avg_cost": 0},
        {"asset_code": "A", "shares": 1, "avg_cost": 1, "current_price": 0},
        {"asset_code": "A", "shares": 1, "avg_cost": 1, "source_id": "bad"},
    ]
    for row in invalid_positions:
        with pytest.raises(ValueError):
            account_tools._normalize_position_input(row)

    transaction = account_tools._normalize_transaction_input(
        {
            "action": " BUY ",
            "asset_code": "A",
            "shares": 2,
            "price": 3,
            "commission": "0.1",
        }
    )
    assert transaction["action"] == "buy"
    assert transaction["commission"] == 0.1
    assert transaction["traded_at"]
    for row in [
        {"action": "hold", "asset_code": "A", "shares": 1, "price": 1},
        {"action": "buy", "shares": 1, "price": 1},
        {"action": "buy", "asset_code": "A", "shares": 0, "price": 1},
        {"action": "buy", "asset_code": "A", "shares": 1, "price": 0},
    ]:
        with pytest.raises(ValueError):
            account_tools._normalize_transaction_input(row)

    flow = account_tools._normalize_capital_flow_input({"flow_type": "deposit", "amount": 100})
    assert flow["flow_date"]
    assert flow["notes"] == ""
    for row in [
        {"amount": 1},
        {"flow_type": "deposit", "amount": 0},
    ]:
        with pytest.raises(ValueError):
            account_tools._normalize_capital_flow_input(row)


def test_account_read_create_and_export_tools(
    account_contract: tuple[dict[str, Tool], MagicMock],
) -> None:
    """Read, create, and export wrappers must preserve the public payload shape."""
    tools, client = account_contract
    client.account.list_portfolio_records.return_value = [
        {
            "id": 1,
            "name": "main",
            "total_value": 100,
            "cash": 20,
            "base_currency": "CNY",
            "is_active": True,
        }
    ]
    client.account.get_portfolio_record.return_value = {
        "id": 1,
        "name": "main",
        "total_value": 100,
        "cash": 20,
        "base_currency": "CNY",
        "is_active": True,
    }
    position = {
        "id": 10,
        "portfolio": 1,
        "asset_code": "000001.SZ",
        "shares": 10,
        "avg_cost": 9,
        "current_price": 10,
        "market_value": 100,
        "unrealized_pnl": 10,
        "is_closed": False,
    }
    transaction = {
        "id": 20,
        "portfolio": 1,
        "action": "buy",
        "asset_code": "000001.SZ",
    }
    flow = {"id": 30, "portfolio": 1, "flow_type": "deposit", "amount": 100}
    client.account.list_position_records.return_value = [position]
    client.account.list_transaction_records.return_value = [transaction]
    client.account.list_capital_flow_records.return_value = [flow]
    client.post.return_value = position
    client.get.side_effect = [
        {"portfolio": "statistics"},
        {"id": 1, "name": "main"},
        {"portfolio": "statistics"},
    ]

    assert tools["list_portfolios"](limit=1)[0]["name"] == "main"
    assert tools["get_portfolio"](portfolio_id=1)["positions"][0]["id"] == 10
    assert tools["get_positions"](portfolio_id=1)[0]["asset_code"] == "000001.SZ"
    assert tools["create_position"](1, "000001.SZ", 10, 9)["id"] == 10
    assert tools["export_positions_json"](1)["count"] == 1
    assert "asset_code" in tools["export_positions_csv"](1)["csv"]
    assert tools["export_transactions_json"](1)["count"] == 1
    assert "action" in tools["export_transactions_csv"](1)["csv"]
    assert tools["export_capital_flows_json"](1)["count"] == 1
    assert "flow_type" in tools["export_capital_flows_csv"](1)["csv"]
    assert tools["get_portfolio_statistics"](1) == {"portfolio": "statistics"}

    bundle = tools["export_account_bundle_json"](portfolio_id=1)
    assert bundle["counts"] == {
        "positions": 1,
        "transactions": 1,
        "capital_flows": 1,
    }


def test_position_import_covers_dry_run_replace_and_runtime_failures(
    account_contract: tuple[dict[str, Tool], MagicMock],
) -> None:
    """Position imports must distinguish validation, create, update, and close errors."""
    tools, client = account_contract
    client.account.list_position_records.return_value = [
        {"id": 1, "asset_code": "UPDATE"},
        {"id": 2, "asset_code": "CLOSE"},
    ]
    client.post.side_effect = RuntimeError("post failed")
    client.patch.side_effect = RuntimeError("patch failed")
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

    assert tools["import_positions_json"](1, positions, mode="invalid")["success"] is False
    preview = tools["import_positions_json"](
        1,
        positions,
        mode="replace",
        dry_run=True,
    )
    assert preview["summary"]["create_count"] == 1
    assert preview["summary"]["update_count"] == 1
    assert preview["summary"]["close_count"] == 1
    result = tools["import_positions_json"](
        1,
        positions,
        mode="replace",
        dry_run=False,
    )
    assert result["success"] is False
    assert {item["operation"] for item in result["errors"] if "operation" in item} == {
        "create",
        "update",
        "close",
    }

    csv_result = tools["import_positions_csv"](
        1,
        "asset_code,shares,avg_cost\nCSV,1,2\n",
    )
    assert csv_result["summary"]["valid_rows"] == 1


def test_transaction_import_covers_replace_validation_and_runtime_failures(
    account_contract: tuple[dict[str, Tool], MagicMock],
) -> None:
    """Transaction imports must report delete and create failures independently."""
    tools, client = account_contract
    client.account.list_transaction_records.return_value = [{"id": 7}]
    client.delete.side_effect = RuntimeError("delete failed")
    client.post.side_effect = RuntimeError("create failed")
    transactions = [
        {
            "action": "buy",
            "asset_code": "A",
            "shares": 2,
            "price": 3,
            "traded_at": "2026-07-25T00:00:00+00:00",
            "commission": 0.1,
        },
        {"action": "hold", "asset_code": "A", "shares": 1, "price": 1},
    ]

    assert tools["import_transactions_json"](1, [], mode="invalid")["success"] is False
    result = tools["import_transactions_json"](
        1,
        transactions,
        mode="replace",
        dry_run=False,
    )
    assert result["success"] is False
    assert result["summary"]["delete_count"] == 1
    assert {item["operation"] for item in result["errors"] if "operation" in item} == {
        "delete",
        "create",
    }
    csv_result = tools["import_transactions_csv"](
        1,
        "action,asset_code,shares,price\nsell,A,1,2\n",
    )
    assert csv_result["summary"]["valid_rows"] == 1


def test_capital_flow_import_covers_replace_validation_and_runtime_failures(
    account_contract: tuple[dict[str, Tool], MagicMock],
) -> None:
    """Capital-flow imports must report delete and create failures independently."""
    tools, client = account_contract
    client.account.list_capital_flow_records.return_value = [{"id": 9}]
    client.delete.side_effect = RuntimeError("delete failed")
    client.post.side_effect = RuntimeError("create failed")
    flows = [
        {
            "flow_type": "deposit",
            "amount": 100,
            "flow_date": "2026-07-25",
            "notes": "seed",
        },
        {"flow_type": "", "amount": 1},
    ]

    assert tools["import_capital_flows_json"](1, [], mode="invalid")["success"] is False
    result = tools["import_capital_flows_json"](
        1,
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
    csv_result = tools["import_capital_flows_csv"](
        1,
        "flow_type,amount\ndeposit,100\n",
    )
    assert csv_result["summary"]["valid_rows"] == 1


def test_broker_json_and_trading_cost_wrappers(
    account_contract: tuple[dict[str, Tool], MagicMock],
) -> None:
    """JSON broker conversion and trading-cost wrappers must delegate canonically."""
    tools, client = account_contract
    client.account.preview_broker_trades_csv.return_value = {"preview": True}
    client.account.import_broker_trades_csv.return_value = {"imported": 1}
    trade = {
        "traded_at": "2026-07-25T00:00:00+00:00",
        "action": "buy",
        "asset_code": "A",
        "shares": 1,
        "price": 2,
    }
    assert tools["preview_broker_trades_json"](1, [trade]) == {"preview": True}
    assert tools["import_broker_trades_json"](1, [trade]) == {"imported": 1}
    csv_text = client.account.preview_broker_trades_csv.call_args.kwargs["csv_text"]
    assert next(csv.DictReader(io.StringIO(csv_text)))["asset_code"] == "A"

    client.post.side_effect = [
        {"id": 4},
        {"data": {"total": 5}},
        {"total": 6},
    ]
    assert tools["create_trading_cost_config"](1, min_commission=5.0)["id"] == 4
    assert client.post.call_args.kwargs["json"]["min_commission"] == 5.0
    client.patch.return_value = {"id": 4, "is_active": False}
    updated = tools["update_trading_cost_config"](
        4,
        commission_rate=0.1,
        min_commission=1,
        stamp_duty_rate=0.2,
        transfer_fee_rate=0.3,
        is_active=False,
    )
    assert updated["is_active"] is False
    assert tools["calculate_trading_cost"](4, "sell", 100)["total"] == 5
    assert tools["calculate_trading_cost"](4, "buy", 100)["total"] == 6
