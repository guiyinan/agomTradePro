"""Focused contracts for append-import write accounting."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro_mcp.tools.import_outcomes import AppendImportWrite, run_append_import
from agomtradepro_mcp.tools.transaction_fee_transport import _TRANSACTION_FEE_FIELDS


def _transaction_write(
    row_number: int,
    asset_code: str,
    traded_at: str = "2026-07-25T00:00:00+00:00",
) -> AppendImportWrite:
    """Return one stable-dated transaction payload and its create receipt contract."""
    payload: dict[str, Any] = {
        "portfolio": 7,
        "action": "buy",
        "asset_code": asset_code,
        "shares": 2,
        "price": 3,
        "traded_at": traded_at,
    }
    return AppendImportWrite(
        row_number=row_number,
        label=asset_code,
        payload=payload,
        required_fields=("portfolio", "action", "asset_code", "shares", "price", "traded_at"),
        identity_fields=("portfolio", "action", "asset_code"),
        decimal_fields=("shares", "price"),
    )


def _transaction_receipt(write: AppendImportWrite) -> dict[str, Any]:
    """Build the minimum TransactionCreatedSerializer response for one write."""
    receipt = dict(write.payload)
    for fee_field in _TRANSACTION_FEE_FIELDS:
        if fee_field in write.payload:
            receipt[fee_field] = write.payload[fee_field]
            receipt[f"{fee_field}_known"] = True
        else:
            receipt[fee_field] = None
            receipt[f"{fee_field}_known"] = False
    return receipt


def _capital_flow_write(row_number: int, notes: str = "seed") -> AppendImportWrite:
    """Return one stable-dated capital-flow payload and id-free receipt contract."""
    return AppendImportWrite(
        row_number=row_number,
        label="deposit",
        payload={
            "portfolio": 7,
            "flow_type": "deposit",
            "amount": 10.0,
            "flow_date": "2026-07-25",
            "notes": notes,
        },
        required_fields=("flow_type", "amount", "flow_date", "notes"),
        identity_fields=("flow_type", "flow_date", "notes"),
        decimal_fields=("amount",),
    )


def test_preview_counts_candidates_without_constructing_client() -> None:
    """Preview puts valid rows in planned count and never attempts a write."""
    factory = MagicMock(side_effect=AssertionError("preview must not build a client"))
    result = run_append_import(
        client_factory=factory,
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[_transaction_write(1, "A")],
        validation_errors=[],
        requested_count=1,
        dry_run=True,
    )

    assert result.outcome == "noop"
    assert result.success is True
    assert result.summary["validated_count"] == 1
    assert result.summary["planned_create_count"] == 1
    assert result.summary["attempted_count"] == 0
    assert result.summary["create_count"] == 0
    assert result.summary["stored_count"] == 0
    factory.assert_not_called()


def test_confirmed_validation_rejection_is_counted_and_next_row_is_sent() -> None:
    """Only an endpoint's known pre-save validation envelope is safe to continue."""
    first = _transaction_write(1, "A")
    second = _transaction_write(2, "B")
    client = MagicMock()
    client.post_once.side_effect = [
        AgomTradeProAPIError(
            "invalid row",
            status_code=400,
            response={"code": "VALIDATION_ERROR"},
        ),
        _transaction_receipt(second),
    ]
    factory = MagicMock(return_value=client)
    result = run_append_import(
        client_factory=factory,
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[first, second],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "partial"
    assert result.success is False
    assert result.summary["attempted_count"] == 2
    assert result.summary["failed_count"] == 1
    assert result.summary["succeeded_count"] == 1
    assert result.summary["stored_count"] == 1
    assert result.summary["create_count"] == 1
    assert result.errors[0]["row"] == 1
    assert result.errors[0]["outcome"] == "failed"
    assert client.post_once.call_count == 2


@pytest.mark.parametrize("status_code", [401, 403])
def test_confirmed_auth_rejection_is_counted_and_next_row_is_sent(
    status_code: int,
) -> None:
    """Authentication and permission envelopes are rejected before endpoint writes."""
    client = MagicMock()
    second = _transaction_write(2, "B")
    client.post_once.side_effect = [
        AgomTradeProAPIError(
            "access rejected",
            status_code=status_code,
            response={"code": "API_ERROR"},
        ),
        _transaction_receipt(second),
    ]
    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[_transaction_write(1, "A"), second],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "partial"
    assert result.summary["failed_count"] == 1
    assert result.summary["succeeded_count"] == 1
    assert client.post_once.call_count == 2


@pytest.mark.parametrize(
    "first_result",
    [
        RuntimeError("connection dropped"),
        AgomTradeProAPIError(
            "server error",
            status_code=503,
            response={"code": "SERVER_ERROR"},
        ),
        AgomTradeProAPIError(
            "not a recognized validation envelope",
            status_code=400,
            response={"code": "API_ERROR"},
        ),
        {},
        {
            "portfolio": 7,
            "action": "buy",
            "asset_code": "wrong",
            "shares": 2,
            "price": 3,
            "traded_at": "2026-07-25T00:00:00+00:00",
        },
    ],
)
def test_ambiguous_post_or_receipt_stops_remaining_rows(
    first_result: BaseException | dict[str, Any],
) -> None:
    """A possibly committed write is unknown and prevents later POSTs."""
    client = MagicMock()
    if isinstance(first_result, BaseException):
        client.post_once.side_effect = first_result
    else:
        client.post_once.return_value = first_result
    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[_transaction_write(1, "A"), _transaction_write(2, "B")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.success is False
    assert result.summary["attempted_count"] == 1
    assert result.summary["unknown_count"] == 1
    assert result.summary["unattempted_count"] == 1
    assert result.summary["stored_count"] is None
    assert result.summary["create_count"] == 0
    assert client.post_once.call_count == 1


def test_client_setup_failure_does_not_mark_a_post_unknown() -> None:
    """A factory failure precedes the request boundary and leaves rows unattempted."""
    factory = MagicMock(side_effect=RuntimeError("missing API configuration"))
    result = run_append_import(
        client_factory=factory,
        endpoint="api/account/capital-flows/",
        ledger="capital_flow",
        writes=[_capital_flow_write(1, "")],
        validation_errors=[],
        requested_count=1,
        dry_run=False,
    )

    assert result.outcome == "failed"
    assert result.summary["attempted_count"] == 0
    assert result.summary["failed_count"] == 0
    assert result.summary["unknown_count"] == 0
    assert result.summary["unattempted_count"] == 1
    assert result.summary["stored_count"] == 0
    factory.assert_called_once_with()


def test_unknown_after_confirmed_write_keeps_count_but_nulls_batch_storage() -> None:
    """A prior receipt stays counted while aggregate storage remains uncertain."""
    first = _transaction_write(1, "A")
    client = MagicMock()
    client.post_once.side_effect = [
        _transaction_receipt(first),
        RuntimeError("connection dropped"),
    ]
    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[first, _transaction_write(2, "B"), _transaction_write(3, "C")],
        validation_errors=[],
        requested_count=3,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["attempted_count"] == 2
    assert result.summary["succeeded_count"] == 1
    assert result.summary["create_count"] == 1
    assert result.summary["stored_count"] is None
    assert result.summary["unattempted_count"] == 1
    assert client.post_once.call_count == 2


def test_capital_flow_owner_not_found_is_safe_but_transaction_not_found_is_unknown() -> None:
    """Only the flow create endpoint's verified pre-save owner 404 can continue."""
    safe_rejection = AgomTradeProAPIError(
        "portfolio not found",
        status_code=404,
        response={"code": "API_ERROR"},
    )
    flow_client = MagicMock()
    flow_client.post_once.side_effect = [
        safe_rejection,
        {"flow_type": "deposit", "amount": "10.00", "flow_date": "2026-07-25", "notes": "second"},
    ]
    flow_result = run_append_import(
        client_factory=MagicMock(return_value=flow_client),
        endpoint="api/account/capital-flows/",
        ledger="capital_flow",
        writes=[_capital_flow_write(1), _capital_flow_write(2, "second")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )
    transaction_client = MagicMock()
    transaction_client.post_once.side_effect = safe_rejection
    transaction_result = run_append_import(
        client_factory=MagicMock(return_value=transaction_client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[_transaction_write(1, "A"), _transaction_write(2, "B")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert flow_result.outcome == "partial"
    assert flow_result.summary["failed_count"] == 1
    assert flow_result.summary["succeeded_count"] == 1
    assert flow_client.post_once.call_count == 2
    assert transaction_result.outcome == "unknown"
    assert transaction_result.summary["unknown_count"] == 1
    assert transaction_result.summary["unattempted_count"] == 1
    assert transaction_client.post_once.call_count == 1


@pytest.mark.parametrize(
    ("request_time", "receipt_time"),
    [
        ("2026-07-25T00:00:00Z", "2026-07-25T00:00:00+00:00"),
        ("2026-07-25T00:00:00+00:00", "2026-07-25T08:00:00+08:00"),
    ],
)
def test_equivalent_aware_traded_at_offsets_confirm_and_continue(
    request_time: str,
    receipt_time: str,
) -> None:
    """Equivalent aware ISO-8601 representations confirm the same instant."""
    first = _transaction_write(1, "A", request_time)
    second = _transaction_write(2, "B")
    first_receipt = _transaction_receipt(first)
    first_receipt["traded_at"] = receipt_time
    client = MagicMock()
    client.post_once.side_effect = [first_receipt, _transaction_receipt(second)]

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[first, second],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "success"
    assert result.summary["attempted_count"] == 2
    assert result.summary["succeeded_count"] == 2
    assert result.summary["unknown_count"] == 0
    assert result.summary["unattempted_count"] == 0
    assert result.summary["stored_count"] == 2
    assert result.summary["create_count"] == 2
    assert client.post_once.call_count == 2


@pytest.mark.parametrize(
    ("request_time", "receipt_time"),
    [
        ("not-an-iso-timestamp", "2026-07-25T00:00:00Z"),
        ("2026-07-25T00:00:00+00:00", "not-an-iso-timestamp"),
        ("2026-07-25T08:00:00", "2026-07-25T08:00:00+08:00"),
        ("2026-07-25T00:00:00+00:00", "2026-07-25T00:00:00"),
        ("2026-07-25T00:00:00+00:00", "2026-07-25T00:01:00+00:00"),
        ("2026-07-25T00:00:00+00:00", "0001-01-01T00:00:00+23:59"),
        ("2026-07-25T00:00:00+00:00", "9999-12-31T23:59:59-23:59"),
    ],
)
def test_unverifiable_traded_at_is_unknown_and_stops_remaining_rows(
    request_time: str,
    receipt_time: str,
) -> None:
    """Invalid, naive, or nonmatching timestamps cannot confirm a POST receipt."""
    first = _transaction_write(1, "A", request_time)
    second = _transaction_write(2, "B")
    first_receipt = _transaction_receipt(first)
    first_receipt["traded_at"] = receipt_time
    client = MagicMock()
    client.post_once.side_effect = [first_receipt, _transaction_receipt(second)]

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[first, second],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["attempted_count"] == 1
    assert result.summary["succeeded_count"] == 0
    assert result.summary["unknown_count"] == 1
    assert result.summary["unattempted_count"] == 1
    assert result.summary["stored_count"] is None
    assert result.summary["create_count"] == 0
    assert client.post_once.call_count == 1


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
def test_each_explicit_zero_fee_requires_and_accepts_matching_known_receipt(
    fee_field: str,
) -> None:
    """Every explicit zero fee is confirmed by a Decimal-equal known receipt."""
    write = _transaction_write(1, "A")
    write.payload[fee_field] = "0"
    receipt = _transaction_receipt(write)
    receipt[fee_field] = "0.00"
    second = _transaction_write(2, "B")
    client = MagicMock()
    client.post_once.side_effect = [receipt, _transaction_receipt(second)]

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write, second],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "success"
    assert result.summary["attempted_count"] == 2
    assert result.summary["succeeded_count"] == 2
    assert result.summary["stored_count"] == 2
    assert client.post_once.call_count == 2


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
@pytest.mark.parametrize(
    "receipt_problem",
    [
        "missing_value",
        "null_value",
        "mismatched_value",
        "missing_known",
        "false_known",
        "null_known",
    ],
)
def test_sent_fee_receipt_must_include_matching_value_and_exact_true_flag(
    fee_field: str,
    receipt_problem: str,
) -> None:
    """Any unverifiable sent fee makes the POST result unknown and stops the batch."""
    write = _transaction_write(1, "A")
    write.payload[fee_field] = "0"
    receipt = _transaction_receipt(write)
    if receipt_problem == "missing_value":
        receipt.pop(fee_field)
    elif receipt_problem == "null_value":
        receipt[fee_field] = None
    elif receipt_problem == "mismatched_value":
        receipt[fee_field] = "0.01"
    elif receipt_problem == "missing_known":
        receipt.pop(f"{fee_field}_known")
    elif receipt_problem == "false_known":
        receipt[f"{fee_field}_known"] = False
    else:
        receipt[f"{fee_field}_known"] = None

    client = MagicMock()
    client.post_once.return_value = receipt
    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write, _transaction_write(2, "B")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["attempted_count"] == 1
    assert result.summary["succeeded_count"] == 0
    assert result.summary["unknown_count"] == 1
    assert result.summary["unattempted_count"] == 1
    assert result.summary["stored_count"] is None
    assert client.post_once.call_count == 1


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
@pytest.mark.parametrize("known_value", [1, "true"])
def test_fee_known_receipt_rejects_non_boolean_values(
    fee_field: str,
    known_value: Any,
) -> None:
    """The nullable boolean serializer contract does not accept truthy substitutes."""
    write = _transaction_write(1, "A")
    receipt = _transaction_receipt(write)
    receipt[f"{fee_field}_known"] = known_value
    client = MagicMock()
    client.post_once.return_value = receipt

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write, _transaction_write(2, "B")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["unknown_count"] == 1
    assert result.summary["unattempted_count"] == 1
    assert client.post_once.call_count == 1


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
@pytest.mark.parametrize("fee_value", [True, "NaN", "Infinity", "-0.01", "0.01"])
def test_unsent_fee_receipt_cannot_claim_a_fee_fact(
    fee_field: str,
    fee_value: Any,
) -> None:
    """An unsent fee cannot become a receipt fact, even if its known flag is false."""
    write = _transaction_write(1, "A")
    receipt = _transaction_receipt(write)
    receipt[fee_field] = fee_value
    receipt[f"{fee_field}_known"] = False
    client = MagicMock()
    client.post_once.return_value = receipt

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write, _transaction_write(2, "B")],
        validation_errors=[],
        requested_count=2,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["attempted_count"] == 1
    assert result.summary["unknown_count"] == 1
    assert result.summary["unattempted_count"] == 1
    assert client.post_once.call_count == 1


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
@pytest.mark.parametrize(
    ("fee_state", "known_state"),
    [
        ("missing", "missing"),
        ("null", "missing"),
        ("null", "false"),
        ("null", "null"),
    ],
)
def test_unrequested_fee_accepts_missing_nullable_unknown_receipt_fields(
    fee_field: str,
    fee_state: str,
    known_state: str,
) -> None:
    """An unsent fee remains unknown when its receipt is missing or explicitly nullable."""
    write = _transaction_write(1, "A")
    receipt = _transaction_receipt(write)
    if fee_state == "missing":
        receipt.pop(fee_field)
    else:
        receipt[fee_field] = None
    if known_state == "missing":
        receipt.pop(f"{fee_field}_known")
    elif known_state == "false":
        receipt[f"{fee_field}_known"] = False
    else:
        receipt[f"{fee_field}_known"] = None
    client = MagicMock()
    client.post_once.return_value = receipt

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write],
        validation_errors=[],
        requested_count=1,
        dry_run=False,
    )

    assert result.outcome == "success"
    assert result.summary["succeeded_count"] == 1


@pytest.mark.parametrize("fee_field", _TRANSACTION_FEE_FIELDS)
def test_unrequested_fee_with_known_true_receipt_is_unknown(fee_field: str) -> None:
    """A server-known fee omitted by the request is not credited to this importer."""
    write = _transaction_write(1, "A")
    receipt = _transaction_receipt(write)
    receipt[fee_field] = None
    receipt[f"{fee_field}_known"] = True
    client = MagicMock()
    client.post_once.return_value = receipt

    result = run_append_import(
        client_factory=MagicMock(return_value=client),
        endpoint="api/account/transactions/",
        ledger="transaction",
        writes=[write],
        validation_errors=[],
        requested_count=1,
        dry_run=False,
    )

    assert result.outcome == "unknown"
    assert result.summary["succeeded_count"] == 0
    assert result.summary["unknown_count"] == 1
