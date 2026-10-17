"""Shared exact settlement validation, canonicalization, and error primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum


class SimulatedSettlementContractError(ValueError):
    """Raised when a simulated-settlement contract is malformed or incomplete."""


class CalendarEvidenceValidationError(SimulatedSettlementContractError):
    """Raised when exact calendar or publication evidence is invalid or unavailable."""


class SimulatedTradeIntentValidationError(SimulatedSettlementContractError):
    """Raised when an exact simulated order intent cannot be represented safely."""


class SimulatedTradeSide(StrEnum):
    """Supported sides for a simulated-ledger order."""

    BUY = "buy"
    SELL = "sell"


class FeeRateStoragePrecision(StrEnum):
    """Explicit precision basis for existing FeeConfig FloatField values."""

    DATABASE_BINARY64 = "database_binary64"


class FeeCalculationPurpose(StrEnum):
    """Name the simulated estimate path so it cannot be mistaken for a fill."""

    NORMAL_SIM_ESTIMATED = "normal_sim_estimated"


class FeeRoundingPolicy(StrEnum):
    """Version the explicit cent-rounding operation used by this calculation."""

    COMPONENT_HALF_EVEN_CENTS_V1 = "component_half_even_cents_v1"


_HASH_LENGTH = 64
_MAX_TOKEN_LENGTH = 192
_MAX_IDEMPOTENCY_LENGTH = 128
_SHARE_QUANTUM = Decimal("0.000001")
_PRICE_QUANTUM = Decimal("0.0001")
_MONEY_QUANTUM = Decimal("0.01")
_MAX_SHARE_VALUE = Decimal("100000000000000")
_MAX_PRICE_VALUE = Decimal("1000000")
_MAX_MONEY_VALUE = Decimal("10000000000000")


def _require_token(value: object, field_name: str, *, max_length: int = _MAX_TOKEN_LENGTH) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(character.isspace() for character in value)
    ):
        raise SimulatedSettlementContractError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SimulatedSettlementContractError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_calendar_hash(value: object, field_name: str) -> None:
    """Require the data-center calendar's explicitly prefixed SHA-256 form."""

    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CalendarEvidenceValidationError(
            f"{field_name} must be a prefixed lowercase SHA-256 digest"
        )


def _require_calendar_fact_hash(value: object, field_name: str) -> None:
    """Require a Data Center canonical row, publication, or policy digest."""

    try:
        _require_hash(value, field_name)
    except SimulatedSettlementContractError as error:
        raise CalendarEvidenceValidationError(str(error)) from error


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedSettlementContractError(f"{field_name} must be a timezone-aware datetime")
    try:
        if value.utcoffset() is None:
            raise SimulatedSettlementContractError(
                f"{field_name} must be a timezone-aware datetime"
            )
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a timezone-aware datetime"
        ) from error


def _utc_text(value: datetime) -> str:
    """Return the canonical UTC text for one validated aware datetime."""

    _require_aware(value, "datetime")
    try:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("datetime cannot be represented in UTC") from error


def _hash_payload(payload: dict[str, object]) -> str:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SimulatedSettlementContractError("payload is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _hash_calendar_payload(payload: dict[str, object]) -> str:
    """Match the exact ASCII canonical hash used by the data-center snapshot DTO."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise CalendarEvidenceValidationError(
            "calendar payload is not canonical ASCII JSON"
        ) from error
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_utc(value: object, field_name: str) -> None:
    """Require a timezone-aware UTC instant matching the data-center contract."""

    _require_aware(value, field_name)
    assert isinstance(value, datetime)
    try:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise CalendarEvidenceValidationError(f"{field_name} must be timezone-aware UTC")
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarEvidenceValidationError(f"{field_name} must be timezone-aware UTC") from error


def _seal_hash(payload: dict[str, object], supplied: object, field_name: str) -> str:
    if type(supplied) is not str:
        raise SimulatedSettlementContractError(f"{field_name} must be a string")
    calculated = _hash_payload(payload)
    if supplied and supplied != calculated:
        raise SimulatedSettlementContractError(f"{field_name} does not match its payload")
    return calculated


def _require_decimal_storage(
    value: object,
    field_name: str,
    *,
    quantum: Decimal,
    exclusive_maximum: Decimal,
    allow_zero: bool = False,
) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedTradeIntentValidationError(f"{field_name} must be an exact finite Decimal")
    decimal_parts = value.as_tuple()
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedTradeIntentValidationError(f"{field_name} must be finite")
    if len(decimal_parts.digits) > 64 or abs(exponent) > 64:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} exceeds the bounded database representation"
        )
    if value < 0 or (value == 0 and not allow_zero):
        raise SimulatedTradeIntentValidationError(f"{field_name} must be positive")
    try:
        with localcontext() as context:
            context.prec = 80
            quantized = value.quantize(quantum)
    except InvalidOperation as error:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} cannot be represented by the ledger column"
        ) from error
    if quantized != value or value >= exclusive_maximum:
        raise SimulatedTradeIntentValidationError(
            f"{field_name} is outside the exact ledger representation"
        )
    return quantized


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    decimal_parts = value.as_tuple()
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    if len(decimal_parts.digits) > 128 or abs(exponent) > 128:
        raise SimulatedSettlementContractError("canonical decimal exceeds its length bound")
    return format(value, "f")


def _decimal_numeric_text(value: Decimal) -> str:
    """Return a bounded decimal spelling that ignores insignificant scale."""

    if type(value) is not Decimal or not value.is_finite():
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    decimal_parts = value.as_tuple()
    digits = list(decimal_parts.digits)
    exponent = decimal_parts.exponent
    if not isinstance(exponent, int):
        raise SimulatedSettlementContractError("canonical decimal must be finite")
    if len(digits) > 64 or abs(exponent) > 64:
        raise SimulatedSettlementContractError("canonical decimal exceeds its length bound")
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    normalized = Decimal((decimal_parts.sign, tuple(digits), exponent))
    return format(normalized, "f")


def _decimal_from_text(value: object, field_name: str) -> Decimal:
    """Parse one bounded canonical decimal without accepting alternate wire spellings."""

    if type(value) is not str or not value or len(value) > 257:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a bounded canonical decimal string"
        )
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise SimulatedSettlementContractError(
            f"{field_name} must be a canonical decimal string"
        ) from error
    if not parsed.is_finite() or _decimal_text(parsed) != value:
        raise SimulatedSettlementContractError(
            f"{field_name} must use its canonical finite decimal spelling"
        )
    return parsed


def validate_ledger_money(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    """Validate one value against the ledger's exact cent/money column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_MONEY_QUANTUM,
        exclusive_maximum=_MAX_MONEY_VALUE,
        allow_zero=allow_zero,
    )


def validate_ledger_quantity(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    """Validate one value against the ledger's six-decimal share column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_SHARE_QUANTUM,
        exclusive_maximum=_MAX_SHARE_VALUE,
        allow_zero=allow_zero,
    )


def validate_ledger_price(value: object, field_name: str, *, allow_zero: bool = True) -> Decimal:
    """Validate one value against the ledger's four-decimal price column range."""

    return _require_decimal_storage(
        value,
        field_name,
        quantum=_PRICE_QUANTUM,
        exclusive_maximum=_MAX_PRICE_VALUE,
        allow_zero=allow_zero,
    )
