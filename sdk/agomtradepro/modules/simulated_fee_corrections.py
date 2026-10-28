"""Typed owner-facing SDK operations for simulated fee corrections."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

import requests

from ..exceptions import AgomTradeProAPIError, ValidationError
from .base import BaseModule

_ASSURANCE_CLASS = "operator_attested_upload"
_MAX_CSV_BYTES = 1_048_576
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_RECOVERY_STATES = frozenset(("completed", "unresolved", "fenced", "unknown"))
_RECOVERY_ITEM_FIELDS = frozenset(
    (
        "source_locator",
        "content_sha256",
        "payload_sha256",
        "stored_at",
        "expected_revision",
        "expected_predecessor_id",
        "binding_policy_version",
        "current_policy_version",
        "state",
        "reason_code",
    )
)
_RECOVERY_RECEIPT_FIELDS = frozenset(
    ("event_id", "account_id", "trade_id", "revision", "payload_hash", "replayed")
)
_FeeCorrectionOperation = Literal["policy", "upload", "apply"]
FeeCorrectionRecoveryState = Literal["completed", "unresolved", "fenced", "unknown"]
_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class FeeCorrectionPolicy:
    """Owner policy state returned by the fee-correction API."""

    account_id: int
    version: int
    enabled: bool
    allow_operator_attested_upload: bool
    ledger_currency: str
    valid_from: datetime | None
    valid_until: datetime | None
    updated_by_id: int | None
    assurance_class: str
    assurance_notice: str


@dataclass(frozen=True, slots=True)
class FeeCorrectionReceipt:
    """Exact persisted correction identity or idempotent replay receipt."""

    event_id: int
    account_id: int
    trade_id: int
    revision: int
    payload_hash: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class FeeCorrectionHead:
    """Validated current correction revision and optional exact-key readback."""

    account_id: int
    trade_id: int
    revision: int
    expected_predecessor_id: int | None
    as_of: datetime
    request_receipt: FeeCorrectionReceipt | None


@dataclass(frozen=True, slots=True)
class FeeCorrectionRecoveryItem:
    """One immutable material's owner-visible recovery classification."""

    source_locator: str
    content_sha256: str
    payload_sha256: str
    stored_at: datetime
    expected_revision: int
    expected_predecessor_id: int | None
    binding_policy_version: int
    current_policy_version: int | None
    state: FeeCorrectionRecoveryState
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class FeeCorrectionRecoveryPage:
    """One bounded page of owner-scoped material states without ledger keys."""

    account_id: int
    trade_id: int
    items: tuple[FeeCorrectionRecoveryItem, ...]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class FeeEvidenceReceipt:
    """Stored operator-attested evidence receipt, not source authentication."""

    source_locator: str
    content_sha256: str
    payload_sha256: str
    assurance_class: str
    stored_at: datetime


@dataclass(frozen=True, slots=True)
class FeeEvidenceUploadResult:
    """Upload receipt and its explicit assurance limitation."""

    evidence: FeeEvidenceReceipt
    assurance_notice: str


class FeeCorrectionOutcomeUnknownError(AgomTradeProAPIError):
    """A write may have committed, but its response did not prove the outcome."""

    effects_indeterminate = True
    recovery_required = True

    _MESSAGES: dict[_FeeCorrectionOperation, str] = {
        "policy": "费用策略更新结果暂无法确认；请调用 get_policy(account_id) 核对状态后再决定下一步。",
        "upload": "费用材料保存结果暂无法确认；策略仍有效时，请使用同一请求键和完全相同的原文重试。",
        "apply": "费用更正结果暂无法确认；请调用 get_head(account_id, trade_id, idempotency_key=...) 读取回执，不要另建请求。",
    }

    def __init__(self, operation: _FeeCorrectionOperation) -> None:
        """Create a non-disclosing error with action-specific recovery guidance."""

        self.operation = operation
        super().__init__(self._MESSAGES[operation], status_code=None, response=None)
        self.code = "fee_correction_outcome_unknown"


class _MalformedFeeCorrectionResponseError(ValueError):
    """Internal marker for a response that fails the published JSON contract."""


def _require_object(value: object) -> Mapping[str, object]:
    """Accept only a JSON object with string keys."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _MalformedFeeCorrectionResponseError
    return cast(Mapping[str, object], value)


def _require_exact_fields(
    payload: Mapping[str, object],
    expected_fields: frozenset[str],
) -> Mapping[str, object]:
    """Reject incomplete response objects and undeclared private fields."""

    if set(payload) != expected_fields:
        raise _MalformedFeeCorrectionResponseError
    return payload


def _required_field(payload: Mapping[str, object], name: str) -> object:
    """Read a required response field without silently defaulting missing data."""

    if name not in payload:
        raise _MalformedFeeCorrectionResponseError
    return payload[name]


def _response_text(payload: Mapping[str, object], name: str, *, nonempty: bool = True) -> str:
    """Read one exact string field from the JSON boundary."""

    value = _required_field(payload, name)
    if type(value) is not str or (nonempty and not value):
        raise _MalformedFeeCorrectionResponseError
    return value


def _response_int(payload: Mapping[str, object], name: str, *, minimum: int = 0) -> int:
    """Read one exact integer, rejecting bool and coercible strings."""

    value = _required_field(payload, name)
    if type(value) is not int or value < minimum:
        raise _MalformedFeeCorrectionResponseError
    return value


def _response_bool(payload: Mapping[str, object], name: str) -> bool:
    """Read one exact JSON boolean."""

    value = _required_field(payload, name)
    if type(value) is not bool:
        raise _MalformedFeeCorrectionResponseError
    return value


def _response_datetime(payload: Mapping[str, object], name: str) -> datetime:
    """Read an explicit-offset ISO timestamp and normalize it to UTC."""

    value = _response_text(payload, name)
    if len(value) > 64 or value != value.strip():
        raise _MalformedFeeCorrectionResponseError
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise _MalformedFeeCorrectionResponseError from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _MalformedFeeCorrectionResponseError
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise _MalformedFeeCorrectionResponseError from None


def _response_optional_datetime(payload: Mapping[str, object], name: str) -> datetime | None:
    """Read a nullable explicit-offset ISO timestamp."""

    value = _required_field(payload, name)
    if value is None:
        return None
    return _response_datetime(payload, name)


def _input_datetime(value: str | None, field_name: str) -> datetime | None:
    """Validate one caller-provided timestamp while preserving its wire string."""

    if value is None:
        return None
    if type(value) is not str or not value or len(value) > 64 or value != value.strip():
        raise ValidationError(f"{field_name} must be an ISO timestamp with an explicit timezone.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ValidationError(
            f"{field_name} must be an ISO timestamp with an explicit timezone."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field_name} must include an explicit timezone.")
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise ValidationError(f"{field_name} must be representable as a UTC timestamp.") from None


def _validate_id(value: int, name: str) -> None:
    """Require a positive exact integer identity."""

    if type(value) is not int or value <= 0:
        raise ValidationError(f"{name} must be a positive integer.")


def _validate_recovery_limit(value: int) -> None:
    """Require the server's supported bounded recovery page size."""

    if type(value) is not int or not 1 <= value <= 100:
        raise ValidationError("limit must be an integer from 1 through 100.")


def _validate_revision(value: int) -> None:
    """Require a nonnegative exact integer revision."""

    if type(value) is not int or value < 0:
        raise ValidationError("expected_revision must be a nonnegative integer.")


def _validate_key(value: str) -> None:
    """Require a caller-owned opaque key matching the HTTP contract."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 128
        or any(character.isspace() for character in value)
    ):
        raise ValidationError("A nonempty idempotency key of at most 128 characters is required.")


def _validate_source_locator(value: str) -> str:
    """Require the canonical UUID returned by the upload endpoint."""

    if type(value) is not str or len(value) != 36:
        raise ValidationError("source_locator must be a canonical UUID.")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValidationError("source_locator must be a canonical UUID.") from error
    if str(parsed) != value:
        raise ValidationError("source_locator must be a canonical UUID.")
    return value


def _validate_recovery_cursor(value: str | None) -> str | None:
    """Require an optional canonical UUID page cursor before sending a GET."""

    if value is None:
        return None
    if type(value) is not str:
        raise ValidationError("cursor must be a canonical UUID.")
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValidationError("cursor must be a canonical UUID.") from error
    if str(parsed) != value:
        raise ValidationError("cursor must be a canonical UUID.")
    return value


def _validate_revision_predecessor(revision: int, predecessor_id: int | None) -> None:
    """Keep revision zero and its nullable predecessor identity consistent."""

    _validate_revision(revision)
    if predecessor_id is not None and (type(predecessor_id) is not int or predecessor_id <= 0):
        raise ValidationError("expected_predecessor_id must be null or a positive integer.")
    if (revision == 0) != (predecessor_id is None):
        raise ValidationError("expected_predecessor_id must match expected_revision.")


def _success_object(value: object) -> Mapping[str, object]:
    """Require the exact success marker before exposing any write result."""

    payload = _require_object(value)
    if _required_field(payload, "success") is not True:
        raise _MalformedFeeCorrectionResponseError
    return payload


def _read_response_error() -> AgomTradeProAPIError:
    """Return a safe SDK error for a malformed successful read response."""

    error = AgomTradeProAPIError(
        "The fee-correction read response did not match its published contract.",
        status_code=502,
    )
    error.code = "fee_correction_response_invalid"
    return error


def _safe_api_error(error: AgomTradeProAPIError, message: str) -> AgomTradeProAPIError:
    """Keep rejection identity while dropping any server-echoed request contents."""

    error.message = message
    error.args = (message,)
    error.response = None
    if isinstance(error, ValidationError):
        error.errors = {}
    return error


def _parse_policy_response(value: object, account_id: int) -> FeeCorrectionPolicy:
    """Validate the explicit owner policy response and parse aware timestamps."""

    envelope = _success_object(value)
    policy = _require_object(_required_field(envelope, "policy"))
    returned_account_id = _response_int(policy, "account_id", minimum=1)
    version = _response_int(policy, "version")
    enabled = _response_bool(policy, "enabled")
    allows_upload = _response_bool(policy, "allow_operator_attested_upload")
    currency = _response_text(policy, "ledger_currency", nonempty=False)
    valid_from = _response_optional_datetime(policy, "valid_from")
    valid_until = _response_optional_datetime(policy, "valid_until")
    updated_by_value = _required_field(policy, "updated_by_id")
    if updated_by_value is not None and (
        type(updated_by_value) is not int or updated_by_value <= 0
    ):
        raise _MalformedFeeCorrectionResponseError
    if (
        returned_account_id != account_id
        or (currency and _CURRENCY_PATTERN.fullmatch(currency) is None)
        or ((enabled or allows_upload) and _CURRENCY_PATTERN.fullmatch(currency) is None)
        or (valid_from is not None and valid_until is not None and valid_from >= valid_until)
        or (
            version == 0
            and (
                enabled
                or allows_upload
                or currency
                or valid_from is not None
                or valid_until is not None
                or updated_by_value is not None
            )
        )
    ):
        raise _MalformedFeeCorrectionResponseError
    assurance_class = _response_text(policy, "assurance_class")
    assurance_notice = _response_text(policy, "assurance_notice")
    if assurance_class != _ASSURANCE_CLASS:
        raise _MalformedFeeCorrectionResponseError
    return FeeCorrectionPolicy(
        account_id=returned_account_id,
        version=version,
        enabled=enabled,
        allow_operator_attested_upload=allows_upload,
        ledger_currency=currency,
        valid_from=valid_from,
        valid_until=valid_until,
        updated_by_id=updated_by_value,
        assurance_class=assurance_class,
        assurance_notice=assurance_notice,
    )


def _parse_receipt(
    value: object,
    *,
    account_id: int,
    trade_id: int,
    minimum_revision: int,
    maximum_revision: int | None = None,
    require_replayed: bool | None = None,
) -> FeeCorrectionReceipt:
    """Validate a receipt identity against the exact requested trade scope."""

    receipt = _require_object(value)
    event_id = _response_int(receipt, "event_id", minimum=1)
    returned_account_id = _response_int(receipt, "account_id", minimum=1)
    returned_trade_id = _response_int(receipt, "trade_id", minimum=1)
    revision = _response_int(receipt, "revision", minimum=1)
    payload_hash = _response_text(receipt, "payload_hash")
    replayed = _response_bool(receipt, "replayed")
    if (
        _SHA256_PATTERN.fullmatch(payload_hash) is None
        or returned_account_id != account_id
        or returned_trade_id != trade_id
        or revision < minimum_revision
        or (maximum_revision is not None and revision > maximum_revision)
        or (require_replayed is not None and replayed is not require_replayed)
    ):
        raise _MalformedFeeCorrectionResponseError
    return FeeCorrectionReceipt(
        event_id=event_id,
        account_id=returned_account_id,
        trade_id=returned_trade_id,
        revision=revision,
        payload_hash=payload_hash,
        replayed=replayed,
    )


def _parse_head_response(
    value: object,
    account_id: int,
    trade_id: int,
    *,
    key_supplied: bool,
    receipt_allowed: bool = False,
) -> FeeCorrectionHead:
    """Validate a current head and nullable exact-key readback receipt."""

    envelope = _success_object(value)
    head = _require_object(_required_field(envelope, "head"))
    returned_account_id = _response_int(head, "account_id", minimum=1)
    returned_trade_id = _response_int(head, "trade_id", minimum=1)
    revision = _response_int(head, "revision")
    predecessor_value = _required_field(head, "expected_predecessor_id")
    if predecessor_value is not None and (
        type(predecessor_value) is not int or predecessor_value <= 0
    ):
        raise _MalformedFeeCorrectionResponseError
    predecessor_id = predecessor_value
    as_of = _response_datetime(head, "as_of")
    receipt_value = _required_field(head, "request_receipt")
    if (
        returned_account_id != account_id
        or returned_trade_id != trade_id
        or (revision == 0 and predecessor_id is not None)
        or (revision > 0 and predecessor_id is None)
        or (not key_supplied and not receipt_allowed and receipt_value is not None)
    ):
        raise _MalformedFeeCorrectionResponseError
    receipt = (
        None
        if receipt_value is None
        else _parse_receipt(
            receipt_value,
            account_id=account_id,
            trade_id=trade_id,
            minimum_revision=1,
            maximum_revision=revision,
            require_replayed=True,
        )
    )
    if receipt is not None and receipt.revision == revision and receipt.event_id != predecessor_id:
        raise _MalformedFeeCorrectionResponseError
    return FeeCorrectionHead(
        account_id=returned_account_id,
        trade_id=returned_trade_id,
        revision=revision,
        expected_predecessor_id=predecessor_id,
        as_of=as_of,
        request_receipt=receipt,
    )


def _parse_recovery_item(value: object) -> FeeCorrectionRecoveryItem:
    """Validate one exact public recovery item and preserve its server reason."""

    item = _require_exact_fields(_require_object(value), _RECOVERY_ITEM_FIELDS)
    source_locator = _response_text(item, "source_locator")
    try:
        parsed_locator = UUID(source_locator)
    except (AttributeError, TypeError, ValueError) as error:
        raise _MalformedFeeCorrectionResponseError from error
    content_hash = _response_text(item, "content_sha256")
    payload_hash = _response_text(item, "payload_sha256")
    stored_at = _response_datetime(item, "stored_at")
    expected_revision = _response_int(item, "expected_revision")
    predecessor_value = _required_field(item, "expected_predecessor_id")
    if predecessor_value is not None and (
        type(predecessor_value) is not int or predecessor_value <= 0
    ):
        raise _MalformedFeeCorrectionResponseError
    binding_policy_version = _response_int(item, "binding_policy_version", minimum=1)
    current_version_value = _required_field(item, "current_policy_version")
    if current_version_value is not None and (
        type(current_version_value) is not int or current_version_value <= 0
    ):
        raise _MalformedFeeCorrectionResponseError
    current_policy_version = current_version_value
    state_value = _response_text(item, "state")
    if state_value not in _RECOVERY_STATES:
        raise _MalformedFeeCorrectionResponseError
    state = cast(FeeCorrectionRecoveryState, state_value)
    reason_value = _required_field(item, "reason_code")
    if reason_value is not None and type(reason_value) is not str:
        raise _MalformedFeeCorrectionResponseError
    reason_code = None if reason_value is None else _response_text(item, "reason_code")
    if (
        str(parsed_locator) != source_locator
        or _SHA256_PATTERN.fullmatch(content_hash) is None
        or _SHA256_PATTERN.fullmatch(payload_hash) is None
        or (expected_revision == 0) != (predecessor_value is None)
        or (state == "unresolved" and current_policy_version != binding_policy_version)
        or (
            state == "fenced"
            and (current_policy_version is None or current_policy_version <= binding_policy_version)
        )
    ):
        raise _MalformedFeeCorrectionResponseError
    return FeeCorrectionRecoveryItem(
        source_locator=source_locator,
        content_sha256=content_hash,
        payload_sha256=payload_hash,
        stored_at=stored_at,
        expected_revision=expected_revision,
        expected_predecessor_id=predecessor_value,
        binding_policy_version=binding_policy_version,
        current_policy_version=current_policy_version,
        state=state,
        reason_code=reason_code,
    )


def _parse_recovery_page_response(
    value: object,
    *,
    account_id: int,
    trade_id: int,
    limit: int,
    cursor: str | None,
) -> FeeCorrectionRecoveryPage:
    """Validate one bounded page without interpreting its item states as writes."""

    envelope = _require_exact_fields(
        _success_object(value),
        frozenset(("success", "outcome", "recovery")),
    )
    if _response_text(envelope, "outcome") != "success":
        raise _MalformedFeeCorrectionResponseError
    recovery = _require_exact_fields(
        _require_object(_required_field(envelope, "recovery")),
        frozenset(("account_id", "trade_id", "items", "has_more", "next_cursor")),
    )
    returned_account_id = _response_int(recovery, "account_id", minimum=1)
    returned_trade_id = _response_int(recovery, "trade_id", minimum=1)
    raw_items = _required_field(recovery, "items")
    if type(raw_items) is not list or len(raw_items) > limit:
        raise _MalformedFeeCorrectionResponseError
    items = tuple(_parse_recovery_item(item) for item in raw_items)
    locator_numbers = [UUID(item.source_locator).int for item in items]
    if locator_numbers != sorted(set(locator_numbers)):
        raise _MalformedFeeCorrectionResponseError
    cursor_number = UUID(cursor).int if cursor is not None else None
    if cursor_number is not None and any(locator <= cursor_number for locator in locator_numbers):
        raise _MalformedFeeCorrectionResponseError
    has_more = _response_bool(recovery, "has_more")
    next_value = _required_field(recovery, "next_cursor")
    if next_value is None:
        next_cursor = None
    else:
        if type(next_value) is not str:
            raise _MalformedFeeCorrectionResponseError
        try:
            parsed_cursor = UUID(next_value)
        except (AttributeError, TypeError, ValueError) as error:
            raise _MalformedFeeCorrectionResponseError from error
        if str(parsed_cursor) != next_value:
            raise _MalformedFeeCorrectionResponseError
        next_cursor = next_value
    if returned_account_id != account_id or returned_trade_id != trade_id:
        raise _MalformedFeeCorrectionResponseError
    if has_more:
        if len(items) != limit or next_cursor is None or next_cursor != items[-1].source_locator:
            raise _MalformedFeeCorrectionResponseError
        if cursor_number is not None and UUID(next_cursor).int <= cursor_number:
            raise _MalformedFeeCorrectionResponseError
    elif next_cursor is not None:
        raise _MalformedFeeCorrectionResponseError
    return FeeCorrectionRecoveryPage(
        account_id=returned_account_id,
        trade_id=returned_trade_id,
        items=items,
        has_more=has_more,
        next_cursor=next_cursor,
    )


def _parse_recovery_head_response(
    value: object,
    *,
    account_id: int,
    trade_id: int,
) -> FeeCorrectionHead:
    """Validate locator-bound head state and require outcome/receipt consistency."""

    envelope = _require_exact_fields(
        _success_object(value),
        frozenset(("success", "outcome", "message", "head")),
    )
    outcome = _response_text(envelope, "outcome")
    if outcome not in ("success", "partial"):
        raise _MalformedFeeCorrectionResponseError
    _response_text(envelope, "message")
    head_payload = _require_exact_fields(
        _require_object(_required_field(envelope, "head")),
        frozenset(
            (
                "account_id",
                "trade_id",
                "revision",
                "expected_predecessor_id",
                "as_of",
                "request_receipt",
            )
        ),
    )
    receipt_value = _required_field(head_payload, "request_receipt")
    if receipt_value is not None:
        _require_exact_fields(_require_object(receipt_value), _RECOVERY_RECEIPT_FIELDS)
    head = _parse_head_response(
        envelope,
        account_id,
        trade_id,
        key_supplied=False,
        receipt_allowed=True,
    )
    if (outcome == "success") != (head.request_receipt is not None):
        raise _MalformedFeeCorrectionResponseError
    return head


def _parse_upload_response(value: object, expected_content_hash: str) -> FeeEvidenceUploadResult:
    """Validate the upload's real receipt fields and preserve its assurance notice."""

    envelope = _success_object(value)
    evidence = _require_object(_required_field(envelope, "evidence"))
    source_locator = _response_text(evidence, "source_locator")
    try:
        parsed_locator = UUID(source_locator)
    except (AttributeError, TypeError, ValueError) as error:
        raise _MalformedFeeCorrectionResponseError from error
    content_hash = _response_text(evidence, "content_sha256")
    payload_hash = _response_text(evidence, "payload_sha256")
    assurance_class = _response_text(evidence, "assurance_class")
    stored_at = _response_datetime(evidence, "stored_at")
    assurance_notice = _response_text(envelope, "assurance_notice")
    if (
        str(parsed_locator) != source_locator
        or content_hash != expected_content_hash
        or _SHA256_PATTERN.fullmatch(payload_hash) is None
        or assurance_class != _ASSURANCE_CLASS
    ):
        raise _MalformedFeeCorrectionResponseError
    return FeeEvidenceUploadResult(
        evidence=FeeEvidenceReceipt(
            source_locator=source_locator,
            content_sha256=content_hash,
            payload_sha256=payload_hash,
            assurance_class=assurance_class,
            stored_at=stored_at,
        ),
        assurance_notice=assurance_notice,
    )


def _explicit_indeterminate(error: AgomTradeProAPIError) -> bool:
    """Honor an explicit server indeterminate marker before status classification."""

    if getattr(error, "effects_indeterminate", False) is True:
        return True
    response = error.response
    if error.code.lower() == "fee_correction_result_indeterminate":
        return True
    return type(response) is dict and (
        response.get("effects_indeterminate") is True or response.get("recovery_required") is True
    )


def _is_read_unavailable(error: AgomTradeProAPIError) -> bool:
    """Recognize the server's definite preflight/read failure code."""

    if error.code.lower() == "fee_correction_read_unavailable":
        return True
    response = error.response
    if type(response) is not dict:
        return False
    code = response.get("code")
    return type(code) is str and code.lower() == "fee_correction_read_unavailable"


def _perform_write(
    action: Callable[[], dict[str, Any]],
    *,
    operation: _FeeCorrectionOperation,
    parser: Callable[[object], _ResultT],
) -> _ResultT:
    """Run one SDK write attempt and reject unverified success as indeterminate."""

    try:
        response = action()
    except AgomTradeProAPIError as error:
        if _explicit_indeterminate(error):
            raise FeeCorrectionOutcomeUnknownError(operation) from None
        if _is_read_unavailable(error):
            raise _safe_api_error(
                error, "The fee-correction preflight read was unavailable."
            ) from None
        if error.status_code in {400, 401, 403, 404, 409, 422, 429}:
            raise _safe_api_error(error, "The fee-correction request was rejected.") from None
        raise FeeCorrectionOutcomeUnknownError(operation) from None
    except requests.exceptions.RequestException:
        raise FeeCorrectionOutcomeUnknownError(operation) from None
    try:
        return parser(response)
    except _MalformedFeeCorrectionResponseError:
        raise FeeCorrectionOutcomeUnknownError(operation) from None


def _parse_policy_write(
    value: object,
    *,
    account_id: int,
    expected_version: int,
    enabled: bool,
    allow_operator_attested_upload: bool,
    ledger_currency: str,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> FeeCorrectionPolicy:
    """Require the successful policy state to match the requested CAS result."""

    policy = _parse_policy_response(value, account_id)
    expected_versions = (
        {expected_version + 1}
        if expected_version == 0
        else {expected_version, expected_version + 1}
    )
    if (
        policy.version not in expected_versions
        or policy.enabled is not enabled
        or policy.allow_operator_attested_upload is not allow_operator_attested_upload
        or policy.ledger_currency != ledger_currency
        or policy.valid_from != valid_from
        or policy.valid_until != valid_until
        or policy.updated_by_id is None
    ):
        raise _MalformedFeeCorrectionResponseError
    return policy


class SimulatedFeeCorrectionsModule(BaseModule):
    """Owner-scoped policy, evidence, correction, and recovery read operations."""

    def __init__(self, client: Any) -> None:
        """Bind this module to canonical simulated-trading endpoints."""

        super().__init__(client, "/api/simulated-trading")

    def get_policy(self, account_id: int) -> FeeCorrectionPolicy:
        """Read one account policy without creating a default server-side row."""

        _validate_id(account_id, "account_id")
        try:
            return _parse_policy_response(
                self._get(f"accounts/{account_id}/fee-correction-policy/"), account_id
            )
        except AgomTradeProAPIError as error:
            raise _safe_api_error(error, "The fee-correction policy read failed.") from None
        except _MalformedFeeCorrectionResponseError:
            raise _read_response_error() from None

    def set_policy(
        self,
        account_id: int,
        *,
        expected_version: int,
        enabled: bool,
        allow_operator_attested_upload: bool,
        ledger_currency: str,
        valid_from: str | None,
        valid_until: str | None,
        attestation_acknowledged: bool,
    ) -> FeeCorrectionPolicy:
        """Explicitly replace the owner policy using a single versioned PUT."""

        _validate_id(account_id, "account_id")
        if type(expected_version) is not int or expected_version < 0:
            raise ValidationError("expected_version must be a nonnegative integer.")
        if type(enabled) is not bool or type(allow_operator_attested_upload) is not bool:
            raise ValidationError("Policy flags must be exact booleans.")
        if type(attestation_acknowledged) is not bool:
            raise ValidationError("attestation_acknowledged must be an exact boolean.")
        if (
            type(ledger_currency) is not str
            or len(ledger_currency) > 3
            or (ledger_currency and _CURRENCY_PATTERN.fullmatch(ledger_currency) is None)
            or (
                (enabled or allow_operator_attested_upload)
                and _CURRENCY_PATTERN.fullmatch(ledger_currency) is None
            )
            or (allow_operator_attested_upload and attestation_acknowledged is not True)
        ):
            raise ValidationError("ledger_currency and attestation settings are invalid.")
        parsed_valid_from = _input_datetime(valid_from, "valid_from")
        parsed_valid_until = _input_datetime(valid_until, "valid_until")
        if (
            parsed_valid_from is not None
            and parsed_valid_until is not None
            and parsed_valid_from >= parsed_valid_until
        ):
            raise ValidationError("The policy validity interval must be nonempty.")
        payload: dict[str, object] = {
            "expected_version": expected_version,
            "enabled": enabled,
            "allow_operator_attested_upload": allow_operator_attested_upload,
            "ledger_currency": ledger_currency,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "attestation_acknowledged": attestation_acknowledged,
        }
        return _perform_write(
            lambda: self._client.put_once(
                f"{self._prefix}/accounts/{account_id}/fee-correction-policy/", json=payload
            ),
            operation="policy",
            parser=lambda response: _parse_policy_write(
                response,
                account_id=account_id,
                expected_version=expected_version,
                enabled=enabled,
                allow_operator_attested_upload=allow_operator_attested_upload,
                ledger_currency=ledger_currency,
                valid_from=parsed_valid_from,
                valid_until=parsed_valid_until,
            ),
        )

    def get_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        idempotency_key: str | None = None,
    ) -> FeeCorrectionHead:
        """Read a validated trade revision and optional original-key receipt."""

        _validate_id(account_id, "account_id")
        _validate_id(trade_id, "trade_id")
        if idempotency_key is not None:
            _validate_key(idempotency_key)
        try:
            response = self._client.get(
                f"{self._prefix}/accounts/{account_id}/trades/{trade_id}/fee-corrections/head/",
                idempotency_key=idempotency_key,
            )
            return _parse_head_response(
                response,
                account_id,
                trade_id,
                key_supplied=idempotency_key is not None,
            )
        except AgomTradeProAPIError as error:
            raise _safe_api_error(error, "The fee-correction head read failed.") from None
        except _MalformedFeeCorrectionResponseError:
            raise _read_response_error() from None

    def discover_recovery(
        self,
        account_id: int,
        trade_id: int,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> FeeCorrectionRecoveryPage:
        """Read one bounded page of exact-trade evidence recovery states."""

        _validate_id(account_id, "account_id")
        _validate_id(trade_id, "trade_id")
        _validate_recovery_limit(limit)
        checked_cursor = _validate_recovery_cursor(cursor)
        params: dict[str, Any] = {"limit": limit}
        if checked_cursor is not None:
            params["cursor"] = checked_cursor
        try:
            response = self._get(
                f"accounts/{account_id}/trades/{trade_id}/fee-corrections/recovery/",
                params=params,
            )
            return _parse_recovery_page_response(
                response,
                account_id=account_id,
                trade_id=trade_id,
                limit=limit,
                cursor=checked_cursor,
            )
        except AgomTradeProAPIError as error:
            raise _safe_api_error(error, "The fee-correction recovery read failed.") from None
        except _MalformedFeeCorrectionResponseError:
            raise _read_response_error() from None

    def get_recovery_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        source_locator: str,
    ) -> FeeCorrectionHead:
        """Read one locator-bound head without accepting an operation key."""

        _validate_id(account_id, "account_id")
        _validate_id(trade_id, "trade_id")
        locator = _validate_source_locator(source_locator)
        try:
            response = self._get(
                f"accounts/{account_id}/trades/{trade_id}/fee-corrections/"
                f"recovery/{locator}/head/"
            )
            return _parse_recovery_head_response(
                response,
                account_id=account_id,
                trade_id=trade_id,
            )
        except AgomTradeProAPIError as error:
            raise _safe_api_error(error, "The fee-correction recovery head read failed.") from None
        except _MalformedFeeCorrectionResponseError:
            raise _read_response_error() from None

    def upload_evidence(
        self,
        account_id: int,
        trade_id: int,
        *,
        idempotency_key: str,
        expected_revision: int,
        expected_predecessor_id: int | None,
        original_filename: str,
        csv_text: str,
        attestation_acknowledged: bool,
    ) -> FeeEvidenceUploadResult:
        """Store exact owner-attested UTF-8 CSV without enabling policy or applying it."""

        _validate_id(account_id, "account_id")
        _validate_id(trade_id, "trade_id")
        _validate_key(idempotency_key)
        _validate_revision_predecessor(expected_revision, expected_predecessor_id)
        if (
            type(original_filename) is not str
            or not original_filename
            or original_filename.strip() != original_filename
            or len(original_filename) > 255
            or any(separator in original_filename for separator in ("/", "\\"))
            or not original_filename.lower().endswith(".csv")
        ):
            raise ValidationError(
                "original_filename must be a single CSV filename of at most 255 characters."
            )
        if type(csv_text) is not str:
            raise ValidationError("csv_text must be the exact original UTF-8 text.")
        if len(csv_text) > _MAX_CSV_BYTES:
            raise ValidationError("csv_text must contain at most 1 MiB of UTF-8 content.")
        if type(attestation_acknowledged) is not bool or not attestation_acknowledged:
            raise ValidationError(
                "The operator-attested assurance must be explicitly acknowledged."
            )
        try:
            raw_content = csv_text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValidationError("csv_text must be losslessly encodable as UTF-8.") from error
        if not raw_content or len(raw_content) > _MAX_CSV_BYTES:
            raise ValidationError("csv_text must contain at most 1 MiB of UTF-8 content.")
        content_hash = sha256(raw_content).hexdigest()
        payload: dict[str, object] = {
            "expected_revision": expected_revision,
            "expected_predecessor_id": expected_predecessor_id,
            "original_filename": original_filename,
            "csv_text": csv_text,
            "attestation_acknowledged": attestation_acknowledged,
        }
        return _perform_write(
            lambda: self._client.post_once(
                f"{self._prefix}/accounts/{account_id}/trades/{trade_id}/fee-correction-evidence/",
                json=payload,
                idempotency_key=idempotency_key,
            ),
            operation="upload",
            parser=lambda response: _parse_upload_response(response, content_hash),
        )

    def apply(
        self,
        account_id: int,
        trade_id: int,
        *,
        idempotency_key: str,
        source_locator: str,
        expected_revision: int,
    ) -> FeeCorrectionReceipt:
        """Apply only a stored locator and exact revision using the caller's key."""

        _validate_id(account_id, "account_id")
        _validate_id(trade_id, "trade_id")
        _validate_key(idempotency_key)
        locator = _validate_source_locator(source_locator)
        _validate_revision(expected_revision)
        payload: dict[str, object] = {
            "source_locator": locator,
            "expected_revision": expected_revision,
        }
        return _perform_write(
            lambda: self._client.post_once(
                f"{self._prefix}/accounts/{account_id}/trades/{trade_id}/fee-corrections/",
                json=payload,
                idempotency_key=idempotency_key,
            ),
            operation="apply",
            parser=lambda response: _parse_receipt(
                _required_field(_success_object(response), "receipt"),
                account_id=account_id,
                trade_id=trade_id,
                minimum_revision=expected_revision + 1,
                maximum_revision=expected_revision + 1,
            ),
        )


__all__ = [
    "FeeCorrectionHead",
    "FeeCorrectionOutcomeUnknownError",
    "FeeCorrectionPolicy",
    "FeeCorrectionReceipt",
    "FeeCorrectionRecoveryItem",
    "FeeCorrectionRecoveryPage",
    "FeeCorrectionRecoveryState",
    "FeeEvidenceReceipt",
    "FeeEvidenceUploadResult",
    "SimulatedFeeCorrectionsModule",
]
