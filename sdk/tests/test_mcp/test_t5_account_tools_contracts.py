"""T5 boundary contracts for the extended account MCP tools."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from agomtradepro.exceptions import AgomTradeProAPIError
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
    assert transaction["commission"] == "0.1"
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


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("replace", "transaction_import_append_only"),
        ("invalid", "transaction_import_mode_unsupported"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_transaction_import_non_append_modes_fail_before_client_or_http(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_code: str,
    dry_run: bool,
) -> None:
    """Transaction import must reject unsupported modes before any SDK request."""
    tools, client = account_contract
    client_factory = MagicMock(side_effect=AssertionError("client must not be created"))
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)

    with pytest.raises(AgomTradeProAPIError) as caught:
        tools["import_transactions_json"](
            1,
            [],
            mode=mode,
            dry_run=dry_run,
        )

    assert caught.value.status_code is None
    assert caught.value.response is not None
    assert caught.value.response["code"] == expected_code
    assert caught.value.response["origin"] == "client_validation"
    client_factory.assert_not_called()
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.post.assert_not_called()
    client.post_once.assert_not_called()
    client.account.list_transaction_records.assert_not_called()


def test_transaction_csv_replace_propagates_append_only_error_before_client(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CSV wrapper must delegate to the same fail-closed mode guard."""
    tools, client = account_contract
    client_factory = MagicMock(side_effect=AssertionError("client must not be created"))
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)

    with pytest.raises(AgomTradeProAPIError) as caught:
        tools["import_transactions_csv"](
            1,
            "action,asset_code,shares,price\nsell,A,1,2\n",
            mode="replace",
            dry_run=False,
        )

    assert caught.value.response is not None
    assert caught.value.response["code"] == "transaction_import_append_only"
    client_factory.assert_not_called()
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.post.assert_not_called()
    client.post_once.assert_not_called()
    client.account.list_transaction_records.assert_not_called()


def test_transaction_append_still_reports_server_create_failure(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unclassified post error is unknown and cannot permit a later POST."""
    tools, client = account_contract
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)
    client.post_once.side_effect = RuntimeError("create failed")
    result = tools["import_transactions_json"](
        1,
        [
            {
                "action": "buy",
                "asset_code": "A",
                "shares": 2,
                "price": 3,
                "traded_at": "2026-07-25T00:00:00+00:00",
                "commission": 0.1,
            }
        ],
        mode="append",
        dry_run=False,
        idempotency_key="c3b-transaction-signature",
    )

    assert result["success"] is False
    assert result["outcome"] == "unknown"
    assert result["summary"]["delete_count"] == 0
    assert result["summary"]["error_count"] == 1
    assert result["summary"]["attempted_count"] == 1
    assert result["summary"]["unknown_count"] == 1
    assert result["summary"]["stored_count"] is None
    assert result["summary"]["create_count"] == 0
    assert result["errors"][0]["row"] == 1
    assert result["errors"][0]["operation"] == "create"
    assert result["errors"][0]["outcome"] == "unknown"
    client_factory.assert_called_once_with()
    client.get.assert_not_called()
    client.account.list_transaction_records.assert_not_called()
    client.delete.assert_not_called()
    client.post_once.assert_called_once()
    client.post.assert_not_called()


def test_transaction_append_counts_only_a_matching_create_receipt(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid create receipt, not a submitted payload, increments create_count."""
    tools, client = account_contract
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    client.post_once.return_value = {
        "portfolio": 1,
        "action": "buy",
        "asset_code": "A",
        "shares": "2",
        "price": "3",
        "commission": "0.00000001",
        "commission_known": True,
        "traded_at": "2026-07-25T00:00:00+00:00",
    }

    result = tools["import_transactions_json"](
        1,
        [
            {
                "action": "buy",
                "asset_code": "A",
                "shares": 2,
                "price": 3,
                "traded_at": "2026-07-25T00:00:00+00:00",
                "commission": "0.00000001",
            }
        ],
        mode="append",
        dry_run=False,
    )

    assert result["outcome"] == "success"
    assert result["summary"]["attempted_count"] == 1
    assert result["summary"]["succeeded_count"] == 1
    assert result["summary"]["stored_count"] == 1
    assert result["summary"]["create_count"] == 1
    assert result["summary"]["planned_create_count"] is None
    client.post_once.assert_called_once()
    csv_preview = tools["import_transactions_csv"](
        1,
        "action,asset_code,shares,price,traded_at\nbuy,B,1,2,2026-07-25T00:00:00+00:00\n",
        mode="append",
        dry_run=True,
    )
    assert csv_preview["summary"]["planned_create_count"] == 1
    assert csv_preview["summary"]["create_count"] == 0
    assert client.post_once.call_count == 1
    client.delete.assert_not_called()
    client.post_once.assert_called_once()
    client.post.assert_not_called()


def test_transaction_registered_fee_receipt_mismatch_is_unknown_and_stops_remaining_rows(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sent fee missing from the create receipt cannot count a successful write."""
    tools, client = account_contract
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    client.post_once.return_value = {
        "portfolio": 1,
        "action": "buy",
        "asset_code": "A",
        "shares": "2",
        "price": "3",
        "traded_at": "2026-07-25T00:00:00+00:00",
        "commission_known": True,
    }

    result = tools["import_transactions_json"](
        1,
        [
            {
                "action": "buy",
                "asset_code": "A",
                "shares": 2,
                "price": 3,
                "traded_at": "2026-07-25T00:00:00+00:00",
                "commission": "0",
            },
            {
                "action": "buy",
                "asset_code": "B",
                "shares": 1,
                "price": 2,
                "traded_at": "2026-07-25T00:00:00+00:00",
            },
        ],
        mode="append",
        dry_run=False,
    )

    assert result["outcome"] == "unknown"
    assert result["summary"]["attempted_count"] == 1
    assert result["summary"]["succeeded_count"] == 0
    assert result["summary"]["unknown_count"] == 1
    assert result["summary"]["unattempted_count"] == 1
    assert result["summary"]["stored_count"] is None
    assert client.post_once.call_count == 1


def test_capital_flow_non_append_modes_fail_before_factory_and_csv_delegates_guard(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both registered wrappers reject replace before client construction or I/O."""
    tools, client = account_contract
    client_factory = MagicMock(side_effect=AssertionError("client must not be created"))
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)
    flow = [{"flow_type": "deposit", "amount": "100.00", "flow_date": "2026-07-25"}]

    for mode, expected_code in (
        ("replace", "capital_flow_import_append_only"),
        ("unsupported", "capital_flow_import_append_only"),
    ):
        for dry_run in (True, False):
            for tool_name, arguments in (
                ("import_capital_flows_json", (1, flow)),
                (
                    "import_capital_flows_csv",
                    (1, "flow_type,amount,flow_date\ndeposit,100.00,2026-07-25\n"),
                ),
            ):
                with pytest.raises(AgomTradeProAPIError) as caught:
                    tools[tool_name](
                        *arguments,
                        mode=mode,
                        dry_run=dry_run,
                    )
                assert caught.value.status_code is None
                assert caught.value.response is not None
                assert caught.value.response["code"] == expected_code
                assert caught.value.response["origin"] == "client_validation"

    client_factory.assert_not_called()
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.post.assert_not_called()
    client.post_once.assert_not_called()
    client.account.list_capital_flow_records.assert_not_called()


def test_capital_flow_append_preview_and_all_invalid_skip_client_factory(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dry-run and a wholly rejected batch do not pre-read or construct a client."""
    tools, client = account_contract
    client_factory = MagicMock(side_effect=AssertionError("client must not be created"))
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)

    preview = tools["import_capital_flows_json"](
        1,
        [{"flow_type": "deposit", "amount": "10.00", "flow_date": "2026-07-25"}],
        mode="append",
        dry_run=True,
        idempotency_key="c3b-capital-flow-preview",
    )
    rejected = tools["import_capital_flows_json"](
        1,
        [{"flow_type": "", "amount": "10.00", "flow_date": "2026-07-25"}],
        mode="append",
        dry_run=False,
    )
    with pytest.raises(AgomTradeProAPIError) as caught:
        tools["import_capital_flows_json"](1, [], mode="unsupported")

    assert preview["success"] is True
    assert preview["summary"]["valid_rows"] == 1
    assert preview["summary"]["create_count"] == 0
    assert preview["summary"]["planned_create_count"] == 1
    assert preview["summary"]["attempted_count"] == 0
    assert rejected["success"] is False
    assert rejected["summary"]["valid_rows"] == 0
    assert rejected["outcome"] == "failed"
    assert caught.value.status_code is None
    assert caught.value.response is not None
    assert caught.value.response["code"] == "capital_flow_import_append_only"
    assert caught.value.response["origin"] == "client_validation"
    client_factory.assert_not_called()
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.post.assert_not_called()
    client.post_once.assert_not_called()
    client.account.list_capital_flow_records.assert_not_called()


def test_capital_flow_append_reports_validation_and_post_failures(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Append still collects a local row rejection and a failed create request."""
    tools, client = account_contract
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(account_tools, "AgomTradeProClient", client_factory)
    client.post_once.side_effect = RuntimeError("create failed")
    result = tools["import_capital_flows_json"](
        1,
        [
            {"flow_type": "deposit", "amount": "100.00", "flow_date": "2026-07-25"},
            {"flow_type": "", "amount": "1.00", "flow_date": "2026-07-25"},
        ],
        mode="append",
        dry_run=False,
        idempotency_key="c3b-capital-flow-append",
    )

    assert result["success"] is False
    assert result["outcome"] == "unknown"
    assert result["summary"]["delete_count"] == 0
    assert result["summary"]["valid_rows"] == 1
    assert result["summary"]["error_count"] == 2
    assert result["summary"]["failed_count"] == 1
    assert result["summary"]["unknown_count"] == 1
    assert result["summary"]["stored_count"] is None
    assert result["errors"][0]["row"] == 2
    assert result["errors"][1]["row"] == 1
    assert {item["operation"] for item in result["errors"] if "operation" in item} == {
        "validate",
        "create",
    }
    client_factory.assert_called_once_with()
    client.get.assert_not_called()
    client.delete.assert_not_called()
    client.post.assert_not_called()
    client.post_once.assert_called_once()
    client.account.list_capital_flow_records.assert_not_called()


def test_capital_flow_append_counts_a_matching_serializer_receipt(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capital-flow response checks match its create serializer without requiring id."""
    tools, client = account_contract
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    client.post_once.return_value = {
        "flow_type": "deposit",
        "amount": "100.00",
        "flow_date": "2026-07-25",
        "notes": "seed",
    }

    result = tools["import_capital_flows_json"](
        1,
        [{"flow_type": "deposit", "amount": "100.00", "flow_date": "2026-07-25", "notes": "seed"}],
        mode="append",
        dry_run=False,
    )

    assert result["outcome"] == "success"
    assert result["summary"]["create_count"] == 1
    assert result["summary"]["succeeded_count"] == 1
    assert result["summary"]["stored_count"] == 1
    assert result["summary"]["planned_create_count"] is None
    client.post_once.assert_called_once()
    csv_preview = tools["import_capital_flows_csv"](
        1,
        "flow_type,amount,flow_date,notes\ndeposit,10.00,2026-07-25,preview\n",
        mode="append",
        dry_run=True,
    )
    assert csv_preview["summary"]["planned_create_count"] == 1
    assert csv_preview["summary"]["create_count"] == 0
    assert client.post_once.call_count == 1


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


def test_registered_transaction_accepts_equivalent_traded_at_offsets(
    account_contract: tuple[dict[str, Tool], MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registered transaction imports compare aware receipt timestamps by instant."""
    tools, client = account_contract
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    client.post_once.return_value = {
        "portfolio": 1,
        "action": "buy",
        "asset_code": "A",
        "shares": "2",
        "price": "3",
        "traded_at": "2026-07-25T08:00:00+08:00",
    }

    result = tools["import_transactions_json"](
        1,
        [
            {
                "action": "buy",
                "asset_code": "A",
                "shares": 2,
                "price": 3,
                "traded_at": "2026-07-25T00:00:00Z",
            }
        ],
        mode="append",
        dry_run=False,
    )

    assert result["outcome"] == "success"
    assert result["summary"]["attempted_count"] == 1
    assert result["summary"]["succeeded_count"] == 1
    assert result["summary"]["unknown_count"] == 0
    assert result["summary"]["stored_count"] == 1
    assert result["summary"]["create_count"] == 1
    client.post_once.assert_called_once()
