"""Transport contracts for actual transaction fees in SDK and MCP flows."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

import agomtradepro
from agomtradepro_mcp.registry.runtime_handlers.owners import account as owner_account
from agomtradepro_mcp.tools import account_tools

Tool = Callable[..., Any]


class _CapturingServer:
    """Capture registered MCP functions without wrapping their arguments."""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def tool(self) -> Callable[[Tool], Tool]:
        """Return the decorator used by account tool registration."""

        def decorator(function: Tool) -> Tool:
            self.tools[function.__name__] = function
            return function

        return decorator


def _base_transaction(**values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "action": "buy",
        "asset_code": "000001.SZ",
        "shares": 2,
        "price": 3,
        "traded_at": "2026-10-17T00:00:00+00:00",
        **values,
    }
    return row


def _captured_payloads(client: MagicMock) -> list[dict[str, Any]]:
    return [call.kwargs["json"] for call in client.post_once.call_args_list]


def test_transaction_json_imports_send_only_explicit_actual_fee_amounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both create paths keep absent fees absent and transport explicit zero."""
    transactions = [
        _base_transaction(
            commission=None,
            slippage="",
            stamp_duty="   ",
            transfer_fee=None,
            commission_known=True,
            slippage_known=True,
            estimated_cost=999,
        ),
        _base_transaction(
            commission=0,
            slippage="0",
            stamp_duty=0.0,
            transfer_fee=" 0 ",
            commission_known=False,
            slippage_known=False,
            stamp_duty_known=True,
            transfer_fee_known=False,
            estimated_cost=999,
        ),
        _base_transaction(
            commission_known=True,
            slippage_known=True,
            stamp_duty_known=True,
            transfer_fee_known=True,
            estimated_cost=999,
        ),
        _base_transaction(
            commission="0.100000000000000001",
            slippage="99999999.99000000001",
            stamp_duty="0",
            transfer_fee="0.000000000000000001",
        ),
    ]
    base_payload = {
        "portfolio": 7,
        "action": "buy",
        "asset_code": "000001.SZ",
        "shares": 2.0,
        "price": 3.0,
        "traded_at": "2026-10-17T00:00:00+00:00",
        "notes": "",
    }
    expected = [
        base_payload,
        {
            **base_payload,
            "commission": "0",
            "slippage": "0",
            "stamp_duty": "0.0",
            "transfer_fee": "0",
        },
        base_payload,
        {
            **base_payload,
            "commission": "0.100000000000000001",
            "slippage": "99999999.99000000001",
            "stamp_duty": "0",
            "transfer_fee": "1E-18",
        },
    ]

    legacy_client = MagicMock()
    legacy_client.account.list_transaction_records.return_value = []
    server = _CapturingServer()
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: legacy_client)
    account_tools.register_account_tools(server)  # type: ignore[arg-type]
    result = server.tools["import_transactions_json"](7, transactions, mode="append", dry_run=False)
    assert result["summary"]["valid_rows"] == 4
    legacy_payloads = _captured_payloads(legacy_client)
    legacy_client.post.assert_not_called()
    assert legacy_payloads == expected
    assert not {
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "estimated_cost",
    }.intersection(legacy_payloads[2])

    owner_client = MagicMock()
    owner_client.get.return_value = {"results": []}
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: owner_client)
    owner_result = owner_account._fallback_import_transactions_json(
        7, transactions, mode="append", dry_run=False
    )
    assert owner_result["summary"]["valid_rows"] == 4
    owner_payloads = _captured_payloads(owner_client)
    owner_client.post.assert_not_called()
    assert owner_payloads == expected
    assert not {
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "estimated_cost",
    }.intersection(owner_payloads[2])


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("shares", True),
        ("price", float("nan")),
        ("commission", float("inf")),
        ("slippage", -0.01),
        ("stamp_duty", 10**400),
        ("transfer_fee", "not-a-number"),
        ("transfer_fee", False),
    ],
)
def test_transaction_import_rejects_non_finite_boolean_and_negative_numbers(
    monkeypatch: pytest.MonkeyPatch, field_name: str, value: Any
) -> None:
    """Invalid transaction numerics cannot become valid dry-run rows."""
    client = MagicMock()
    client.account.list_transaction_records.return_value = []
    server = _CapturingServer()
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    account_tools.register_account_tools(server)  # type: ignore[arg-type]

    row = _base_transaction()
    row[field_name] = value
    result = server.tools["import_transactions_json"](7, [row], mode="append", dry_run=True)

    assert result["success"] is False
    assert result["summary"]["valid_rows"] == 0
    assert result["summary"]["error_count"] == 1
    client.post_once.assert_not_called()
    client.post.assert_not_called()


def test_transaction_csv_export_gates_fee_values_on_exact_known_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSV preserves known zero, blank unknowns, and exact boolean flags."""
    row = {
        "id": 1,
        "portfolio": 7,
        "action": "buy",
        "asset_code": "000001.SZ",
        "commission": 0.0,
        "commission_known": True,
        "slippage": 9.5,
        "slippage_known": None,
        "stamp_duty": 1.25,
        "stamp_duty_known": False,
        "transfer_fee": 0.0,
        "transfer_fee_known": True,
    }
    second_row = {
        "id": 2,
        "portfolio": 7,
        "action": "sell",
        "asset_code": "600000.SH",
        "commission": 0.0,
        "slippage": 0.0,
        "stamp_duty": 0.0,
        "transfer_fee": 0.0,
    }
    client = MagicMock()
    client.account.list_transaction_records.return_value = [row, second_row]
    server = _CapturingServer()
    monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
    account_tools.register_account_tools(server)  # type: ignore[arg-type]

    json_export = server.tools["export_transactions_json"](7)
    assert json_export["transactions"] == [row, second_row]
    csv_export = server.tools["export_transactions_csv"](7)
    records = list(csv.DictReader(io.StringIO(csv_export["csv"])))

    assert list(records[0]) == [
        "id",
        "portfolio",
        "position",
        "action",
        "asset_code",
        "shares",
        "price",
        "notional",
        "commission",
        "traded_at",
        "notes",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
    ]
    assert records[0]["commission"] == "0.0"
    assert records[0]["commission_known"] == "True"
    assert records[0]["slippage"] == ""
    assert records[0]["slippage_known"] == ""
    assert records[0]["stamp_duty"] == ""
    assert records[0]["stamp_duty_known"] == "False"
    assert records[0]["transfer_fee"] == "0.0"
    assert records[0]["transfer_fee_known"] == "True"
    assert all(
        records[1][name] == ""
        for name in (
            "commission",
            "slippage",
            "stamp_duty",
            "transfer_fee",
            "commission_known",
            "slippage_known",
            "stamp_duty_known",
            "transfer_fee_known",
        )
    )


@pytest.mark.parametrize(
    ("fee_value", "expected_valid"),
    [
        ("-1e-500", False),
        (Decimal("-1e-500"), False),
        ("1e-500", False),
        ("-0.0", True),
    ],
)
@pytest.mark.parametrize("use_owner_fallback", [False, True], ids=["legacy", "owner"])
def test_transaction_import_preserves_fee_sign_before_float_underflow(
    monkeypatch: pytest.MonkeyPatch,
    fee_value: Any,
    expected_valid: bool,
    use_owner_fallback: bool,
) -> None:
    """Both import paths reject nonzero fees lost by float conversion."""
    row = _base_transaction(commission=fee_value)
    client = MagicMock()
    if use_owner_fallback:
        client.get.return_value = {"results": []}
        monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: client)
        result = owner_account._fallback_import_transactions_json(
            7, [row], mode="append", dry_run=True
        )
    else:
        client.account.list_transaction_records.return_value = []
        server = _CapturingServer()
        monkeypatch.setattr(account_tools, "AgomTradeProClient", lambda: client)
        account_tools.register_account_tools(server)  # type: ignore[arg-type]
        result = server.tools["import_transactions_json"](7, [row], mode="append", dry_run=True)

    assert result["success"] is expected_valid
    assert result["summary"]["valid_rows"] == int(expected_valid)
    assert result["summary"]["error_count"] == int(not expected_valid)
    client.post_once.assert_not_called()
    client.post.assert_not_called()
    if not expected_valid:
        assert result["errors"][0]["row"] == 1
        assert "commission" in result["errors"][0]["error"]
