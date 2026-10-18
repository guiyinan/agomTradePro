"""Shared accounting for append-only account import POST requests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol

from agomtradepro.exceptions import AgomTradeProAPIError
from agomtradepro_mcp.tools.transaction_fee_transport import _TRANSACTION_FEE_FIELDS

AppendImportOutcome = Literal["success", "partial", "failed", "unknown", "noop"]
AppendImportLedger = Literal["transaction", "capital_flow"]


class AppendImportClient(Protocol):
    """The single-request SDK surface used by append importers."""

    def post_once(self, endpoint: str, /, *, json: dict[str, Any]) -> dict[str, Any]:
        """Send one create request without the SDK's normal retry path."""
        ...


@dataclass(frozen=True)
class AppendImportWrite:
    """One normalized row and the minimum create-response contract for it."""

    row_number: int
    label: str
    payload: dict[str, Any]
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    decimal_fields: tuple[str, ...]


@dataclass(frozen=True)
class AppendImportResult:
    """Normalized outcome and JSON-compatible counts for one importer call."""

    outcome: AppendImportOutcome
    success: bool
    summary: dict[str, int | None]
    errors: list[dict[str, Any]]


def _decimal_value(value: object) -> Decimal | None:
    """Parse a finite JSON numeric value without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _parse_aware_iso8601(value: object) -> datetime | None:
    """Parse a timestamp only when it names an explicit timezone-aware instant."""
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def _transaction_fee_receipt_error(
    write: AppendImportWrite,
    response: dict[str, Any],
) -> str | None:
    """Validate fee facts against fields explicitly supplied in the create request."""
    for fee_field in _TRANSACTION_FEE_FIELDS:
        known_field = f"{fee_field}_known"
        fee_present = fee_field in response
        fee_value = response.get(fee_field)
        known_value = response.get(known_field)

        if (
            known_field in response
            and known_value is not None
            and not isinstance(known_value, bool)
        ):
            return f"create response has invalid {known_field} type"

        if fee_present and fee_value is not None:
            actual_fee = _decimal_value(fee_value)
            if actual_fee is None:
                return f"create response has invalid {fee_field}"
            if actual_fee < 0:
                return f"create response has negative {fee_field}"

        if fee_field in write.payload:
            expected_fee = _decimal_value(write.payload[fee_field])
            if expected_fee is None or expected_fee < 0:
                return f"request has invalid {fee_field}"
            if not fee_present or fee_value is None:
                return f"create response is missing {fee_field}"
            actual_fee = _decimal_value(fee_value)
            if actual_fee is None or actual_fee != expected_fee:
                return f"create response has mismatched {fee_field}"
            if known_value is not True:
                return f"create response does not confirm {known_field}"
            continue

        if fee_value is not None:
            return f"create response includes unsent {fee_field}"
        if known_value is True:
            return f"create response marks unsent {known_field} as known"

    return None


def _receipt_error(
    write: AppendImportWrite,
    response: object,
    *,
    ledger: AppendImportLedger,
) -> str | None:
    """Return why a decoded create body cannot confirm this row was stored."""
    if not isinstance(response, dict):
        return "create response is not a JSON object"

    for field in write.required_fields:
        if field not in response:
            return f"create response is missing {field}"
        actual = response[field]
        expected = write.payload.get(field)
        if actual is None:
            return f"create response has null {field}"

        if field in write.decimal_fields:
            expected_decimal = _decimal_value(expected)
            actual_decimal = _decimal_value(actual)
            if (
                expected_decimal is None
                or actual_decimal is None
                or expected_decimal != actual_decimal
            ):
                return f"create response has mismatched {field}"
            continue

        if field == "traded_at":
            expected_instant = _parse_aware_iso8601(expected)
            actual_instant = _parse_aware_iso8601(actual)
            if expected_instant is None or actual_instant is None:
                return "create response has invalid or timezone-naive traded_at"
            if expected_instant != actual_instant:
                return "create response has mismatched traded_at"
            continue

        if isinstance(expected, str):
            if not isinstance(actual, str):
                return f"create response has invalid {field} type"
            if field not in write.identity_fields and not actual.strip():
                return f"create response has empty {field}"
        elif isinstance(expected, int):
            if isinstance(actual, bool) or not isinstance(actual, int):
                return f"create response has invalid {field} type"
        elif expected is not None and not isinstance(actual, type(expected)):
            return f"create response has invalid {field} type"

        if field in write.identity_fields and actual != expected:
            return f"create response has mismatched {field}"

    if ledger == "transaction":
        return _transaction_fee_receipt_error(write, response)
    return None


def _is_confirmed_pre_save_rejection(
    ledger: AppendImportLedger,
    error: Exception,
) -> bool:
    """Recognize only current API envelopes that prove create stopped before save."""
    if not isinstance(error, AgomTradeProAPIError):
        return False
    response = error.response
    if not isinstance(response, dict):
        return False
    code = response.get("code")
    if not isinstance(code, str):
        return False

    if error.status_code == 400 and code == "VALIDATION_ERROR":
        return True
    if error.status_code in (401, 403) and code == "API_ERROR":
        return True
    return ledger == "capital_flow" and error.status_code == 404 and code == "API_ERROR"


def _error_entry(
    write: AppendImportWrite,
    error: Exception,
    outcome: Literal["failed", "unknown"],
) -> dict[str, Any]:
    """Describe one attempted row without implying more than its known result."""
    entry: dict[str, Any] = {
        "row": write.row_number,
        "operation": "create",
        "label": write.label,
        "outcome": outcome,
        "error": str(error),
    }
    if isinstance(error, AgomTradeProAPIError):
        if error.status_code is not None:
            entry["upstream_status_code"] = error.status_code
        if isinstance(error.response, dict):
            code = error.response.get("code")
            if isinstance(code, str):
                entry["response_code"] = code
    return entry


def _outcome(
    *,
    dry_run: bool,
    requested_count: int,
    failed_count: int,
    succeeded_count: int,
    unknown_count: int,
    unattempted_count: int,
) -> AppendImportOutcome:
    """Apply the outcome precedence shared by registered and fallback imports."""
    if unknown_count:
        return "unknown"
    if failed_count:
        return "partial" if succeeded_count else "failed"
    if dry_run or requested_count == 0:
        return "noop"
    if unattempted_count:
        return "partial" if succeeded_count else "failed"
    if succeeded_count == requested_count:
        return "success"
    return "failed"


def run_append_import(
    *,
    client_factory: Callable[[], AppendImportClient],
    endpoint: str,
    ledger: AppendImportLedger,
    writes: Sequence[AppendImportWrite],
    validation_errors: Sequence[dict[str, Any]],
    requested_count: int,
    dry_run: bool,
) -> AppendImportResult:
    """Run validated rows once each and account for confirmed or ambiguous results."""
    errors: list[dict[str, Any]] = []
    for validation_error in validation_errors:
        entry = dict(validation_error)
        entry.setdefault("operation", "validate")
        entry["outcome"] = "failed"
        errors.append(entry)

    failed_count = len(validation_errors)
    attempted_count = 0
    succeeded_count = 0
    unknown_count = 0
    unattempted_count = 0

    if not dry_run and writes:
        try:
            client = client_factory()
        except Exception as exc:  # noqa: BLE001 - a factory error precedes any POST
            errors.append(
                {
                    "operation": "client_setup",
                    "outcome": "failed",
                    "error": str(exc),
                }
            )
            unattempted_count = len(writes)
        else:
            for index, write in enumerate(writes):
                attempted_count += 1
                try:
                    response = client.post_once(endpoint, json=write.payload)
                except Exception as exc:  # noqa: BLE001 - transport errors can follow a commit
                    if _is_confirmed_pre_save_rejection(ledger, exc):
                        failed_count += 1
                        errors.append(_error_entry(write, exc, "failed"))
                        continue
                    unknown_count += 1
                    errors.append(_error_entry(write, exc, "unknown"))
                    unattempted_count = len(writes) - index - 1
                    break

                receipt_problem = _receipt_error(write, response, ledger=ledger)
                if receipt_problem is not None:
                    receipt_error = RuntimeError(receipt_problem)
                    unknown_count += 1
                    errors.append(_error_entry(write, receipt_error, "unknown"))
                    unattempted_count = len(writes) - index - 1
                    break
                succeeded_count += 1

    validated_count = len(writes)
    outcome = _outcome(
        dry_run=dry_run,
        requested_count=requested_count,
        failed_count=failed_count,
        succeeded_count=succeeded_count,
        unknown_count=unknown_count,
        unattempted_count=unattempted_count,
    )
    stored_count: int | None = None if unknown_count else succeeded_count
    summary: dict[str, int | None] = {
        "requested_count": requested_count,
        "validated_count": validated_count,
        "attempted_count": attempted_count,
        "succeeded_count": succeeded_count,
        "failed_count": failed_count,
        "unknown_count": unknown_count,
        "unattempted_count": unattempted_count,
        "stored_count": stored_count,
        "create_count": succeeded_count,
        "planned_create_count": validated_count if dry_run else None,
        "delete_count": 0,
        "input_rows": requested_count,
        "valid_rows": validated_count,
        "error_count": len(errors),
    }
    return AppendImportResult(
        outcome=outcome,
        success=outcome in ("success", "noop"),
        summary=summary,
        errors=errors,
    )
