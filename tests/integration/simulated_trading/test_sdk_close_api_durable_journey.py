"""Exercise an SDK close through the real API and committed settlement UoW."""

from __future__ import annotations

import json as json_module
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import pytest
import requests
from django.contrib.auth.models import AbstractBaseUser
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model
from rest_framework.test import APIClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = REPO_ROOT / "sdk"
sdk_path = str(SDK_ROOT)
if sdk_path in sys.path:
    sys.path.remove(sdk_path)
sys.path.insert(0, sdk_path)

from agomtradepro import AgomTradeProClient  # noqa: E402
from agomtradepro.exceptions import ExecutionOutcomeUnknownError  # noqa: E402
from agomtradepro.transport import use_request_transport  # noqa: E402
from apps.simulated_trading.infrastructure.models import (  # noqa: E402
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderFillReceiptModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from tests.api import conftest as api_fixtures  # noqa: E402
from tests.api.test_manual_trade_current_reference import (  # noqa: E402
    _CLOSE_RECEIPT_FIELDS,
    _close_body,
    _close_financial_snapshot,
    _install_close_manual_service,
    _position,
    _seed_fee,
)
from tests.support.account_authority_generation_flush import (  # noqa: E402
    preserve_account_authority_generation as preserve_account_authority_generation,
)

active_decision_runtime = api_fixtures.active_decision_runtime
api_client = api_fixtures.api_client
auth_user = api_fixtures.auth_user
authenticated_client = api_fixtures.authenticated_client
owned_account = api_fixtures.owned_account

CloseResponseFault = Literal["connection_lost", "malformed_json", "missing_receipt", "read_timeout"]
TableRows = tuple[tuple[Any, ...], ...]
FinancialRows = tuple[TableRows, TableRows, TableRows, TableRows, TableRows]

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def _query_rows(
    database: BaseDatabaseWrapper,
    model: type[Model],
    *,
    where: str,
    parameters: tuple[object, ...],
) -> TableRows:
    """Read all persisted columns for one scoped table through a supplied connection."""

    fields = tuple(model._meta.concrete_fields)
    quote = database.ops.quote_name
    columns = ", ".join(quote(field.column) for field in fields)
    primary_key_column = quote(model._meta.pk.column)
    statement = (
        f"SELECT {columns} FROM {quote(model._meta.db_table)} "
        f"WHERE {where} ORDER BY {primary_key_column}"
    )
    with database.cursor() as cursor:
        cursor.execute(statement, parameters)
        return tuple(tuple(row) for row in cursor.fetchall())


def _independent_financial_rows(account_id: int) -> FinancialRows:
    """Read the five financial tables from a fresh DB connection after the API returns."""

    source = connections["default"]
    source.ensure_connection()
    source_handle = source.connection
    probe = source.copy(alias="durable_close_readback")
    try:
        probe.ensure_connection()
        assert probe is not source
        assert probe.connection is not source_handle
        assert probe.get_autocommit()
        assert not probe.in_atomic_block
        quote = probe.ops.quote_name

        account_rows = _query_rows(
            probe,
            SimulatedAccountModel,
            where=f"{quote(SimulatedAccountModel._meta.pk.column)} = %s",
            parameters=(account_id,),
        )
        position_account_column = quote(PositionModel._meta.get_field("account").column)
        position_rows = _query_rows(
            probe,
            PositionModel,
            where=f"{position_account_column} = %s",
            parameters=(account_id,),
        )
        trade_account_column = quote(SimulatedTradeModel._meta.get_field("account").column)
        trade_rows = _query_rows(
            probe,
            SimulatedTradeModel,
            where=f"{trade_account_column} = %s",
            parameters=(account_id,),
        )
        reservation_account_column = quote(
            SimulatedOrderReservationModel._meta.get_field("account").column
        )
        reservation_rows = _query_rows(
            probe,
            SimulatedOrderReservationModel,
            where=f"{reservation_account_column} = %s",
            parameters=(account_id,),
        )

        receipt_reservation_column = quote(
            SimulatedOrderFillReceiptModel._meta.get_field("reservation").column
        )
        receipt_trade_column = quote(SimulatedOrderFillReceiptModel._meta.get_field("trade").column)
        reservation_table = quote(SimulatedOrderReservationModel._meta.db_table)
        reservation_pk = quote(SimulatedOrderReservationModel._meta.pk.column)
        reservation_owner = quote(SimulatedOrderReservationModel._meta.get_field("account").column)
        trade_table = quote(SimulatedTradeModel._meta.db_table)
        trade_pk = quote(SimulatedTradeModel._meta.pk.column)
        trade_owner = quote(SimulatedTradeModel._meta.get_field("account").column)
        receipt_scope = (
            f"({receipt_reservation_column} IN (SELECT {reservation_pk} "
            f"FROM {reservation_table} WHERE {reservation_owner} = %s) OR "
            f"{receipt_trade_column} IN (SELECT {trade_pk} FROM {trade_table} "
            f"WHERE {trade_owner} = %s))"
        )
        receipt_rows = _query_rows(
            probe,
            SimulatedOrderFillReceiptModel,
            where=receipt_scope,
            parameters=(account_id, account_id),
        )
        return (
            account_rows,
            position_rows,
            trade_rows,
            reservation_rows,
            receipt_rows,
        )
    finally:
        probe.close()


def _assert_close_is_visible_after_commit(rows: FinancialRows) -> None:
    """Check an independent observer sees the committed full-close ledger rows."""

    account_rows, position_rows, trade_rows, reservation_rows, receipt_rows = rows
    assert len(account_rows) == 1
    assert position_rows == ()
    assert len(trade_rows) == 1
    # The manual-close UoW stores replay identity on the trade row.
    # Order reservations and source fill receipts belong to a separate order-fill flow.
    assert reservation_rows == ()
    assert receipt_rows == ()

    account_fields = tuple(field.attname for field in SimulatedAccountModel._meta.concrete_fields)
    cash_index = account_fields.index("current_cash")
    assert Decimal(str(account_rows[0][cash_index])) == Decimal("111972.16")
    market_value_index = account_fields.index("current_market_value")
    assert Decimal(str(account_rows[0][market_value_index])) == Decimal("0.00")
    total_value_index = account_fields.index("total_value")
    assert Decimal(str(account_rows[0][total_value_index])) == Decimal("111972.16")
    total_trades_index = account_fields.index("total_trades")
    assert account_rows[0][total_trades_index] == 1

    trade_fields = tuple(field.attname for field in SimulatedTradeModel._meta.concrete_fields)
    trade = trade_rows[0]
    assert trade[trade_fields.index("action")] == "sell"
    assert trade[trade_fields.index("status")] == "executed"
    assert str(trade[trade_fields.index("order_date")]) == "2026-10-16"
    assert str(trade[trade_fields.index("execution_date")]) == "2026-10-16"
    assert Decimal(str(trade[trade_fields.index("quantity")])) == Decimal("1000")
    assert Decimal(str(trade[trade_fields.index("price")])) == Decimal("12.0000")
    assert Decimal(str(trade[trade_fields.index("amount")])) == Decimal("12000.00")
    assert Decimal(str(trade[trade_fields.index("commission")])) == Decimal("3.60")
    assert Decimal(str(trade[trade_fields.index("transfer_fee")])) == Decimal("0.24")
    assert Decimal(str(trade[trade_fields.index("stamp_duty")])) == Decimal("12.00")
    assert Decimal(str(trade[trade_fields.index("slippage")])) == Decimal("12.00")
    assert Decimal(str(trade[trade_fields.index("total_cost")])) == Decimal("27.84")
    assert trade[trade_fields.index("idempotency_key")] == "sdk-close-durable-journey-001"
    assert len(trade[trade_fields.index("request_payload_hash")]) == 64


class _RealCloseApiTransport:
    """Route SDK requests into DRF and fault only the returned transport response."""

    def __init__(
        self,
        *,
        client: APIClient,
        account_id: int,
        fault: CloseResponseFault,
    ) -> None:
        self.client = client
        self.account_id = account_id
        self.fault = fault
        self.calls: list[tuple[str, str, dict[str, str], dict[str, Any]]] = []
        self.persisted_receipts: list[dict[str, Any]] = []
        self.persisted_trades: list[dict[str, Any]] = []
        self.committed_rows: FinancialRows | None = None
        self.rows_after_retry: FinancialRows | None = None

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        json: dict[str, Any] | None,
        files: dict[str, Any] | None,
        timeout: int,
    ) -> Any:
        del params, data, files, timeout
        assert method == "POST"
        assert json is not None
        path = urlsplit(url).path
        assert path == (f"/api/simulated-trading/accounts/{self.account_id}/positions/close/")
        idempotency_key = headers["Idempotency-Key"]
        self.calls.append((method, url, dict(headers), dict(json)))

        response = self.client.post(
            path,
            data=json,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert response.status_code == 200, response.content.decode("utf-8")
        payload = json_module.loads(response.content.decode("utf-8"))
        assert isinstance(payload, dict)
        assert payload.get("success") is True
        trade = payload.get("trade")
        assert isinstance(trade, dict)
        self.persisted_trades.append(dict(trade))
        receipt = payload.get("receipt")
        assert isinstance(receipt, dict)
        self.persisted_receipts.append(dict(receipt))

        if len(self.calls) == 1:
            default_connection = connections["default"]
            assert default_connection.get_autocommit()
            assert not default_connection.in_atomic_block
            self.committed_rows = _independent_financial_rows(self.account_id)

            if self.fault == "connection_lost":
                raise requests.exceptions.ChunkedEncodingError(
                    "the committed close response was lost"
                )
            if self.fault == "read_timeout":
                raise requests.exceptions.ReadTimeout(
                    "the committed close response timed out while reading"
                )
            if self.fault == "malformed_json":
                response.content = b"{malformed"
            elif self.fault == "missing_receipt":
                missing_receipt_payload = dict(payload)
                missing_receipt_payload.pop("receipt")
                response.content = json_module.dumps(missing_receipt_payload).encode("utf-8")
        elif len(self.calls) == 2:
            self.rows_after_retry = _independent_financial_rows(self.account_id)
        return response


@pytest.mark.parametrize(
    "fault",
    ["connection_lost", "malformed_json", "missing_receipt", "read_timeout"],
)
def test_sdk_close_unknown_outcome_reads_back_committed_real_api_receipt(
    *,
    authenticated_client: APIClient,
    owned_account: SimulatedAccountModel,
    auth_user: AbstractBaseUser,
    api_client: APIClient,
    active_decision_runtime: None,
    monkeypatch: pytest.MonkeyPatch,
    fault: CloseResponseFault,
) -> None:
    """Commit through DRF, lose or corrupt the response, then replay with the same key."""

    assert api_client is authenticated_client
    assert owned_account.user_id == auth_user.pk
    assert active_decision_runtime is None

    _seed_fee(owned_account)
    _position(owned_account)
    state = _install_close_manual_service(monkeypatch, account=owned_account)
    body = _close_body(shares=1000, price="12.0000")
    key = "sdk-close-durable-journey-001"
    snapshot_before = _close_financial_snapshot(owned_account.pk)
    transport = _RealCloseApiTransport(
        client=authenticated_client,
        account_id=owned_account.pk,
        fault=fault,
    )

    with use_request_transport(transport):
        with AgomTradeProClient(
            base_url="https://fixture.example.test",
            api_token="fixture-only",
        ) as first_client:
            with pytest.raises(ExecutionOutcomeUnknownError) as first_unknown:
                first_client.simulated_trading.close_position(
                    account_id=owned_account.pk,
                    asset_code="600000.SH",
                    close_shares=1000,
                    close_price="12.0000",
                    idempotency_key=key,
                )
        assert first_unknown.value.code == "execution_outcome_unknown"
        assert first_unknown.value.effects_indeterminate is True

        assert transport.committed_rows is not None
        assert len(_CLOSE_RECEIPT_FIELDS) == 17
        _assert_close_is_visible_after_commit(transport.committed_rows)
        assert len(transport.persisted_receipts) == 1
        assert set(transport.persisted_receipts[0]) == _CLOSE_RECEIPT_FIELDS
        assert transport.persisted_receipts[0]["replayed"] is False

        snapshot_after_unknown = _independent_financial_rows(owned_account.pk)
        assert snapshot_after_unknown == transport.committed_rows
        _assert_close_is_visible_after_commit(snapshot_after_unknown)
        trade_fields = tuple(field.attname for field in SimulatedTradeModel._meta.concrete_fields)
        committed_trade = snapshot_after_unknown[2][0]
        assert committed_trade[trade_fields.index("request_payload_hash")] == (
            transport.persisted_receipts[0]["request_payload_hash"]
        )

        snapshot_after_commit = _close_financial_snapshot(owned_account.pk)
        assert snapshot_after_commit != snapshot_before

        source_reads_before_retry = (
            state.identity_reader.resolve_calls,
            state.identity_reader.read_calls,
        )
        monkeypatch.setattr(
            state.clock,
            "now",
            lambda: pytest.fail("idempotent API retry read the current clock"),
        )
        monkeypatch.setattr(
            state.identity_reader,
            "resolve_current_reference_identity",
            lambda **_kwargs: pytest.fail("idempotent API retry reread current identity"),
        )
        monkeypatch.setattr(
            state.identity_reader,
            "get_execution_instrument_identity",
            lambda **_kwargs: pytest.fail("idempotent API retry reread execution identity"),
        )
        monkeypatch.setattr(
            state.calendar_reader,
            "get_effective_execution_calendar",
            lambda **_kwargs: pytest.fail("idempotent API retry reread the calendar"),
        )

        with AgomTradeProClient(
            base_url="https://fixture.example.test",
            api_token="fixture-only",
        ) as retry_client:
            replayed = retry_client.simulated_trading.close_position(
                account_id=owned_account.pk,
                asset_code="600000.SH",
                close_shares=1000,
                close_price="12.0000",
                idempotency_key=key,
            )

    assert len(transport.calls) == 2
    assert [call[0] for call in transport.calls] == ["POST", "POST"]
    assert [call[3] for call in transport.calls] == [body, body]
    assert [call[3]["close_price"] for call in transport.calls] == ["12.0000"] * 2
    assert [call[2]["Idempotency-Key"] for call in transport.calls] == [key, key]
    assert transport.rows_after_retry == snapshot_after_unknown
    assert [trade["status"] for trade in transport.persisted_trades] == [
        "executed",
        "executed",
    ]
    assert [trade["order_date"] for trade in transport.persisted_trades] == [
        "2026-10-16",
        "2026-10-16",
    ]
    assert [trade["execution_date"] for trade in transport.persisted_trades] == [
        "2026-10-16",
        "2026-10-16",
    ]
    for trade, receipt in zip(
        transport.persisted_trades,
        transport.persisted_receipts,
        strict=True,
    ):
        assert receipt["idempotency_key"] == key
        assert len(receipt["request_payload_hash"]) == 64
        assert trade["trade_id"] == receipt["trade_id"]
        assert trade["account_id"] == receipt["account_id"] == owned_account.pk
        assert trade["action"] == receipt["side"] == "sell"
        assert trade["asset_code"] == receipt["asset_code"] == "600000.SH"
        assert Decimal(str(trade["quantity"])) == Decimal(str(receipt["quantity"])) == 1000
        assert Decimal(trade["price"]) == Decimal(receipt["price"]) == Decimal("12.0000")
        assert Decimal(trade["amount"]) == Decimal(receipt["amount"]) == Decimal("12000.00")
        assert Decimal(trade["commission"]) == Decimal(receipt["commission"]) == Decimal("3.60")
        assert Decimal(receipt["transfer_fee"]) == Decimal("0.24")
        assert Decimal(receipt["stamp_duty"]) == Decimal("12.00")
        assert Decimal(trade["slippage"]) == Decimal(receipt["slippage"]) == Decimal("12.00")
        assert Decimal(trade["total_cost"]) == Decimal(receipt["total_cost"]) == Decimal("27.84")
        assert receipt["settlement_status"] is None
        assert receipt["settlement_release_date"] is None
    assert set(transport.persisted_receipts[1]) == _CLOSE_RECEIPT_FIELDS
    assert transport.persisted_receipts[1]["replayed"] is True
    assert transport.persisted_receipts[1]["request_payload_hash"] == (
        transport.persisted_receipts[0]["request_payload_hash"]
    )
    assert replayed["replayed"] is True
    assert replayed["receipt"] == transport.persisted_receipts[1]
    assert replayed["trade"]["trade_id"] == replayed["receipt"]["trade_id"]
    assert state.execution.intents and len(state.execution.intents) == 1
    assert (
        state.identity_reader.resolve_calls,
        state.identity_reader.read_calls,
    ) == source_reads_before_retry
    assert _close_financial_snapshot(owned_account.pk) == snapshot_after_commit
