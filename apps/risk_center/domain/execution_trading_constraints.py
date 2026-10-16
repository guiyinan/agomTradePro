"""Typed, content-addressed A-share execution rules and evidence decisions.

Sellable-balance odd-lot handling can only clear a complete, fresh balance that
the evidence marks as currently available to sell with no restricted quantity.
It does not claim that all economic holdings, unsettled holdings, or positions
outside that evidence source have been cleared.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EXECUTION_CONSTRAINTS_SCHEMA: str = "a-share-execution-constraints.v1"
_MAX_CANONICAL_DECIMAL_CHARS: int = 257


class ExecutionContractValidationError(ValueError):
    """Raised when a typed execution contract is malformed or noncanonical."""


class ExecutionSide(StrEnum):
    """Supported sides for a constrained limit order."""

    BUY = "BUY"
    SELL = "SELL"


class SellOddLotMode(StrEnum):
    """Explicit rule for selling shares outside the regular quantity step."""

    FORBID = "FORBID"
    SELLABLE_BALANCE_TO_ZERO = "SELLABLE_BALANCE_TO_ZERO"
    SELL_ODD_REMAINDER_ONCE = "SELL_ODD_REMAINDER_ONCE"


class PriceBoundaryMode(StrEnum):
    """Explicit state of the current security price boundaries."""

    LIMITED = "LIMITED"
    UNRESTRICTED = "UNRESTRICTED"
    UNKNOWN = "UNKNOWN"


class SessionState(StrEnum):
    """Calendar/provider state for the identified trading session."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class SecurityTradingState(StrEnum):
    """Explicit current state of the exact security."""

    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"
    UNKNOWN = "UNKNOWN"


class SellPositionCompleteness(StrEnum):
    """Completeness of the source's available and restricted balance evidence."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class ExecutionDecisionStatus(StrEnum):
    """Rule tradability result, not authorization, account funding, or signature."""

    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class ExecutionDenyCode(StrEnum):
    """Stable machine-readable reasons an order cannot use this rule evidence."""

    RULE_MARKET_SECURITY_MISMATCH = "RULE_MARKET_SECURITY_MISMATCH"
    ORDER_SECURITY_MISMATCH = "ORDER_SECURITY_MISMATCH"
    RULE_SOURCE_NOT_YET_AVAILABLE = "RULE_SOURCE_NOT_YET_AVAILABLE"
    RULE_NOT_YET_EFFECTIVE = "RULE_NOT_YET_EFFECTIVE"
    RULE_SOURCE_EXPIRED = "RULE_SOURCE_EXPIRED"
    RULE_MARKET_MISMATCH = "RULE_MARKET_MISMATCH"
    RULE_BOARD_MISMATCH = "RULE_BOARD_MISMATCH"
    CALENDAR_EVIDENCE_NOT_YET_AVAILABLE = "CALENDAR_EVIDENCE_NOT_YET_AVAILABLE"
    CALENDAR_EVIDENCE_EXPIRED = "CALENDAR_EVIDENCE_EXPIRED"
    MARKET_EVIDENCE_NOT_YET_AVAILABLE = "MARKET_EVIDENCE_NOT_YET_AVAILABLE"
    MARKET_EVIDENCE_EXPIRED = "MARKET_EVIDENCE_EXPIRED"
    SESSION_STATE_UNKNOWN = "SESSION_STATE_UNKNOWN"
    SESSION_CLOSED = "SESSION_CLOSED"
    OUTSIDE_TRADING_DATE = "OUTSIDE_TRADING_DATE"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    SECURITY_STATE_UNKNOWN = "SECURITY_STATE_UNKNOWN"
    SECURITY_SUSPENDED = "SECURITY_SUSPENDED"
    SECURITY_DELISTED = "SECURITY_DELISTED"
    PRICE_BOUNDARY_UNKNOWN = "PRICE_BOUNDARY_UNKNOWN"
    REFERENCE_PRICE_NOT_ON_TICK = "REFERENCE_PRICE_NOT_ON_TICK"
    LIMIT_PRICE_NOT_ON_TICK = "LIMIT_PRICE_NOT_ON_TICK"
    REFERENCE_PRICE_OUTSIDE_BOUNDARY = "REFERENCE_PRICE_OUTSIDE_BOUNDARY"
    LIMIT_PRICE_OUTSIDE_BOUNDARY = "LIMIT_PRICE_OUTSIDE_BOUNDARY"
    QUANTITY_BELOW_MINIMUM = "QUANTITY_BELOW_MINIMUM"
    QUANTITY_NOT_ON_STEP = "QUANTITY_NOT_ON_STEP"
    QUANTITY_ABOVE_MAXIMUM = "QUANTITY_ABOVE_MAXIMUM"
    POSITION_EVIDENCE_MISSING = "POSITION_EVIDENCE_MISSING"
    POSITION_EVIDENCE_INCOMPLETE = "POSITION_EVIDENCE_INCOMPLETE"
    POSITION_ACCOUNT_MISMATCH = "POSITION_ACCOUNT_MISMATCH"
    POSITION_SECURITY_MISMATCH = "POSITION_SECURITY_MISMATCH"
    POSITION_EVIDENCE_NOT_YET_AVAILABLE = "POSITION_EVIDENCE_NOT_YET_AVAILABLE"
    POSITION_EVIDENCE_EXPIRED = "POSITION_EVIDENCE_EXPIRED"
    SELLABLE_BALANCE_INSUFFICIENT = "SELLABLE_BALANCE_INSUFFICIENT"
    ODD_LOT_HAS_RESTRICTED_BALANCE = "ODD_LOT_HAS_RESTRICTED_BALANCE"
    ODD_LOT_NOT_FULL_SELLABLE_BALANCE = "ODD_LOT_NOT_FULL_SELLABLE_BALANCE"


def _token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ExecutionContractValidationError(f"{field_name} must be a bounded canonical token")
    return value


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ExecutionContractValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionContractValidationError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: object, field_name: str, *, allow_zero: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise ExecutionContractValidationError(f"{field_name} must be an exact finite Decimal")
    _canonical_decimal_components(value)
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ExecutionContractValidationError(f"{field_name} must be {qualifier}")
    return value


def _share_quantity(value: object, field_name: str, *, allow_zero: bool = False) -> Decimal:
    quantity = _decimal(value, field_name, allow_zero=allow_zero)
    coefficient, exponent = _decimal_coefficient_and_exponent(quantity)
    if exponent < 0 and coefficient % (10**-exponent) != 0:
        raise ExecutionContractValidationError(f"{field_name} must be a whole share quantity")
    return quantity


def _decimal_coefficient_and_exponent(value: Decimal) -> tuple[int, int]:
    if value.is_zero():
        return 0, 0
    parts = value.as_tuple()
    exponent = parts.exponent
    if type(exponent) is not int:
        raise ExecutionContractValidationError("Decimal exponent must be finite")
    end = len(parts.digits)
    while end > 1 and parts.digits[end - 1] == 0:
        end -= 1
    exponent += len(parts.digits) - end
    coefficient = 0
    for digit in parts.digits[:end]:
        coefficient = coefficient * 10 + digit
    return (-coefficient if parts.sign else coefficient), exponent


def _is_decimal_multiple(value: Decimal, step: Decimal) -> bool:
    value_coefficient, value_exponent = _decimal_coefficient_and_exponent(value)
    step_coefficient, step_exponent = _decimal_coefficient_and_exponent(step)
    scale: int = max(0, -value_exponent, -step_exponent)
    value_power: int = value_exponent + scale
    step_power: int = step_exponent + scale
    value_factor: int = 10**value_power
    step_factor: int = 10**step_power
    scaled_value: int = value_coefficient * value_factor
    scaled_step: int = step_coefficient * step_factor
    remainder: int = scaled_value % scaled_step
    return remainder == 0


def _is_decimal_difference_multiple(left: Decimal, right: Decimal, step: Decimal) -> bool:
    """Check an exact Decimal difference using bounded integer-scaled values."""

    left_coefficient, left_exponent = _decimal_coefficient_and_exponent(left)
    right_coefficient, right_exponent = _decimal_coefficient_and_exponent(right)
    step_coefficient, step_exponent = _decimal_coefficient_and_exponent(step)
    scale: int = max(0, -left_exponent, -right_exponent, -step_exponent)
    left_power: int = left_exponent + scale
    right_power: int = right_exponent + scale
    step_power: int = step_exponent + scale
    scaled_left: int = left_coefficient * (10**left_power)
    scaled_right: int = right_coefficient * (10**right_power)
    scaled_step: int = step_coefficient * (10**step_power)
    difference: int = scaled_left - scaled_right
    remainder: int = difference % scaled_step
    return remainder == 0


def _canonical_decimal_components(value: Decimal) -> tuple[str, int]:
    """Return bounded significant digits and exponent for plain wire rendering."""

    parts = value.as_tuple()
    if type(parts.exponent) is not int:
        raise ExecutionContractValidationError("Decimal exponent must be finite")
    digits = parts.digits
    end = len(digits)
    while end > 1 and digits[end - 1] == 0:
        end -= 1
    if end == 1 and digits[0] == 0:
        return "0", 0

    exponent = parts.exponent + len(digits) - end
    digit_count = end
    decimal_position = digit_count + exponent
    if exponent >= 0:
        rendered_length = digit_count + exponent
    elif decimal_position > 0:
        rendered_length = digit_count + 1
    else:
        rendered_length = 2 - decimal_position + digit_count
    if rendered_length > _MAX_CANONICAL_DECIMAL_CHARS:
        raise ExecutionContractValidationError(
            "Decimal exceeds the canonical wire-text length bound"
        )
    significant_digits = "".join(str(digit) for digit in digits[:end])
    return significant_digits, exponent


def _decimal_text(value: Decimal) -> str:
    """Render a finite nonnegative Decimal as bounded canonical plain notation."""

    _decimal(value, "decimal payload", allow_zero=True)
    significant_digits, exponent = _canonical_decimal_components(value)
    if significant_digits == "0":
        return "0"
    if exponent >= 0:
        return significant_digits + ("0" * exponent)
    decimal_position = len(significant_digits) + exponent
    if decimal_position > 0:
        return significant_digits[:decimal_position] + "." + significant_digits[decimal_position:]
    return "0." + ("0" * -decimal_position) + significant_digits


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _content_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seal_content_hash(payload: dict[str, object], supplied: object, field_name: str) -> str:
    expected = _content_hash(payload)
    if supplied == "":
        return expected
    _digest(supplied, field_name)
    if supplied != expected:
        raise ExecutionContractValidationError(f"{field_name} does not match canonical content")
    return expected


def _require_enum(value: object, enum_type: type[Enum], field_name: str) -> None:
    if type(value) is not enum_type:
        raise ExecutionContractValidationError(f"{field_name} must be {enum_type.__name__}")


@dataclass(frozen=True, slots=True)
class ExecutionQuantityConstraint:
    """Side-specific minimum, increment, and maximum order quantity."""

    minimum: Decimal
    step: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        """Require exact positive whole-share bounds and a consistent maximum."""

        _share_quantity(self.minimum, "minimum")
        _share_quantity(self.step, "step")
        _share_quantity(self.maximum, "maximum")
        if self.maximum < self.minimum:
            raise ExecutionContractValidationError("maximum must be at least minimum")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical wire projection for this quantity constraint."""

        return {
            "minimum": _decimal_text(self.minimum),
            "step": _decimal_text(self.step),
            "maximum": _decimal_text(self.maximum),
        }


@dataclass(frozen=True, slots=True)
class AShareExecutionRule:
    """Immutable execution constraints for one exact A-share security/version."""

    rule_id: str
    rule_version: str
    security_id: str
    market: str
    board: str
    buy_quantity: ExecutionQuantityConstraint
    sell_quantity: ExecutionQuantityConstraint
    sell_odd_lot_mode: SellOddLotMode
    price_tick: Decimal
    rule_source_id: str
    rule_source_version: str
    rule_source_hash: str
    source_observed_at: datetime
    source_available_at: datetime
    effective_from: datetime
    valid_until: datetime
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate explicit rule terms, provenance, validity, and canonical content hash."""

        for field_name in (
            "rule_id",
            "rule_version",
            "security_id",
            "market",
            "board",
            "rule_source_id",
            "rule_source_version",
        ):
            _token(getattr(self, field_name), field_name)
        if type(self.buy_quantity) is not ExecutionQuantityConstraint:
            raise ExecutionContractValidationError(
                "buy_quantity must be ExecutionQuantityConstraint"
            )
        if type(self.sell_quantity) is not ExecutionQuantityConstraint:
            raise ExecutionContractValidationError(
                "sell_quantity must be ExecutionQuantityConstraint"
            )
        self.buy_quantity.__post_init__()
        self.sell_quantity.__post_init__()
        _require_enum(self.sell_odd_lot_mode, SellOddLotMode, "sell_odd_lot_mode")
        if (
            self.sell_odd_lot_mode is SellOddLotMode.SELL_ODD_REMAINDER_ONCE
            and self.sell_quantity.minimum != self.sell_quantity.step
        ):
            raise ExecutionContractValidationError(
                "SELL_ODD_REMAINDER_ONCE requires sell minimum and step to match"
            )
        _decimal(self.price_tick, "price_tick")
        _digest(self.rule_source_hash, "rule_source_hash")
        for field_name in (
            "source_observed_at",
            "source_available_at",
            "effective_from",
            "valid_until",
        ):
            _aware(getattr(self, field_name), field_name)
        if self.source_observed_at > self.source_available_at:
            raise ExecutionContractValidationError(
                "rule source observed_at must not follow available_at"
            )
        if self.source_available_at >= self.valid_until:
            raise ExecutionContractValidationError(
                "rule source is not available within its validity window"
            )
        if self.effective_from >= self.valid_until:
            raise ExecutionContractValidationError("rule effective window is invalid")
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash, "content_hash"),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "security_id": self.security_id,
            "market": self.market,
            "board": self.board,
            "buy_quantity": self.buy_quantity.to_payload(),
            "sell_quantity": self.sell_quantity.to_payload(),
            "sell_odd_lot_mode": self.sell_odd_lot_mode.value,
            "price_tick": _decimal_text(self.price_tick),
            "rule_source_id": self.rule_source_id,
            "rule_source_version": self.rule_source_version,
            "rule_source_hash": self.rule_source_hash,
            "source_observed_at": _utc_text(self.source_observed_at),
            "source_available_at": _utc_text(self.source_available_at),
            "effective_from": _utc_text(self.effective_from),
            "valid_until": _utc_text(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical rule projection and its content hash."""

        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class SellPositionEvidence:
    """Fresh broker evidence for the available and restricted account balance.

    COMPLETE means the source explicitly reports both quantities for this exact
    security. A zero restricted quantity is required for sellable-balance
    odd-lot handling; the evidence does not establish holdings outside its scope.
    """

    security_id: str
    account_id: int
    available_to_sell_quantity: Decimal | None
    restricted_quantity: Decimal | None
    completeness: SellPositionCompleteness
    source_id: str
    source_version: str
    source_hash: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Validate account-bound quantities, completeness, provenance, and source times."""

        _token(self.security_id, "security_id")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ExecutionContractValidationError("account_id must be a positive integer")
        _require_enum(self.completeness, SellPositionCompleteness, "completeness")
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.source_hash, "source_hash")
        if self.completeness is SellPositionCompleteness.COMPLETE:
            if self.available_to_sell_quantity is None or self.restricted_quantity is None:
                raise ExecutionContractValidationError(
                    "complete sell position evidence requires both quantities"
                )
        for field_name in ("available_to_sell_quantity", "restricted_quantity"):
            value = getattr(self, field_name)
            if value is not None:
                _share_quantity(value, field_name, allow_zero=True)
        for field_name in ("observed_at", "available_at", "valid_until"):
            _aware(getattr(self, field_name), field_name)
        if self.observed_at > self.available_at or self.available_at >= self.valid_until:
            raise ExecutionContractValidationError("sell position evidence window is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the account-scoped position evidence projection."""

        return {
            "security_id": self.security_id,
            "account_id": self.account_id,
            "available_to_sell_quantity": (
                _decimal_text(self.available_to_sell_quantity)
                if self.available_to_sell_quantity is not None
                else None
            ),
            "restricted_quantity": (
                _decimal_text(self.restricted_quantity)
                if self.restricted_quantity is not None
                else None
            ),
            "completeness": self.completeness.value,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "observed_at": _utc_text(self.observed_at),
            "available_at": _utc_text(self.available_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class ExecutionMarketEvidence:
    """Immutable calendar, session, security-state, and price evidence."""

    security_id: str
    market: str
    board: str
    trading_date: date
    calendar_id: str
    calendar_version: str
    calendar_source_hash: str
    calendar_observed_at: datetime
    calendar_available_at: datetime
    calendar_valid_until: datetime
    session_id: str
    session_timezone: str
    session_open_at: datetime
    session_close_at: datetime
    session_state: SessionState
    security_state: SecurityTradingState
    market_source_id: str
    market_source_version: str
    market_source_hash: str
    price_boundary_mode: PriceBoundaryMode
    lower_limit_price: Decimal | None
    upper_limit_price: Decimal | None
    reference_price: Decimal
    market_observed_at: datetime
    market_available_at: datetime
    market_valid_until: datetime
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate calendar, session, security state, and price evidence without defaults."""

        _token(self.security_id, "security_id")
        _token(self.market, "market")
        _token(self.board, "board")
        if type(self.trading_date) is not date:
            raise ExecutionContractValidationError("trading_date must be an exact date")
        for field_name in (
            "calendar_id",
            "calendar_version",
            "session_id",
            "market_source_id",
            "market_source_version",
        ):
            _token(getattr(self, field_name), field_name)
        _digest(self.calendar_source_hash, "calendar_source_hash")
        _digest(self.market_source_hash, "market_source_hash")
        for field_name in (
            "calendar_observed_at",
            "calendar_available_at",
            "calendar_valid_until",
            "session_open_at",
            "session_close_at",
            "market_observed_at",
            "market_available_at",
            "market_valid_until",
        ):
            _aware(getattr(self, field_name), field_name)
        if not (
            self.calendar_observed_at <= self.calendar_available_at < self.calendar_valid_until
        ):
            raise ExecutionContractValidationError("calendar evidence window is invalid")
        if not self.market_observed_at <= self.market_available_at < self.market_valid_until:
            raise ExecutionContractValidationError("market evidence window is invalid")
        if self.session_open_at >= self.session_close_at:
            raise ExecutionContractValidationError("session interval is invalid")
        _token(self.session_timezone, "session_timezone")
        try:
            ZoneInfo(self.session_timezone)
        except ZoneInfoNotFoundError as error:
            raise ExecutionContractValidationError("session_timezone is unknown") from error
        _require_enum(self.session_state, SessionState, "session_state")
        _require_enum(self.security_state, SecurityTradingState, "security_state")
        _require_enum(self.price_boundary_mode, PriceBoundaryMode, "price_boundary_mode")
        _decimal(self.reference_price, "reference_price")
        if self.price_boundary_mode is PriceBoundaryMode.LIMITED:
            if self.lower_limit_price is None or self.upper_limit_price is None:
                raise ExecutionContractValidationError(
                    "LIMITED boundary requires both limit prices"
                )
            _decimal(self.lower_limit_price, "lower_limit_price")
            _decimal(self.upper_limit_price, "upper_limit_price")
            if self.lower_limit_price > self.upper_limit_price:
                raise ExecutionContractValidationError("LIMITED boundary range is reversed")
        elif self.lower_limit_price is not None or self.upper_limit_price is not None:
            raise ExecutionContractValidationError(
                f"{self.price_boundary_mode.value} boundary requires null limit prices"
            )
        object.__setattr__(
            self,
            "content_hash",
            _seal_content_hash(self._content_payload(), self.content_hash, "content_hash"),
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "market": self.market,
            "board": self.board,
            "trading_date": self.trading_date.isoformat(),
            "calendar_id": self.calendar_id,
            "calendar_version": self.calendar_version,
            "calendar_source_hash": self.calendar_source_hash,
            "calendar_observed_at": _utc_text(self.calendar_observed_at),
            "calendar_available_at": _utc_text(self.calendar_available_at),
            "calendar_valid_until": _utc_text(self.calendar_valid_until),
            "session_id": self.session_id,
            "session_timezone": self.session_timezone,
            "session_open_at": _utc_text(self.session_open_at),
            "session_close_at": _utc_text(self.session_close_at),
            "session_state": self.session_state.value,
            "security_state": self.security_state.value,
            "market_source_id": self.market_source_id,
            "market_source_version": self.market_source_version,
            "market_source_hash": self.market_source_hash,
            "price_boundary_mode": self.price_boundary_mode.value,
            "lower_limit_price": (
                _decimal_text(self.lower_limit_price)
                if self.lower_limit_price is not None
                else None
            ),
            "upper_limit_price": (
                _decimal_text(self.upper_limit_price)
                if self.upper_limit_price is not None
                else None
            ),
            "reference_price": _decimal_text(self.reference_price),
            "market_observed_at": _utc_text(self.market_observed_at),
            "market_available_at": _utc_text(self.market_available_at),
            "market_valid_until": _utc_text(self.market_valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical calendar and market evidence with its hash."""

        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ExecutionOrder:
    """Exact account/security limit order input evaluated by the domain."""

    order_id: str
    account_id: int
    security_id: str
    side: ExecutionSide
    quantity: Decimal
    limit_price: Decimal
    sell_position_evidence: SellPositionEvidence | None

    def __post_init__(self) -> None:
        """Validate the exact order identity, side, quantities, and optional sell evidence."""

        _token(self.order_id, "order_id")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ExecutionContractValidationError("account_id must be a positive integer")
        _token(self.security_id, "security_id")
        _require_enum(self.side, ExecutionSide, "side")
        _share_quantity(self.quantity, "quantity")
        _decimal(self.limit_price, "limit_price")
        if (
            self.sell_position_evidence is not None
            and type(self.sell_position_evidence) is not SellPositionEvidence
        ):
            raise ExecutionContractValidationError(
                "sell_position_evidence must be SellPositionEvidence or None"
            )
        if self.sell_position_evidence is not None:
            self.sell_position_evidence.__post_init__()

    def to_payload(self) -> dict[str, object]:
        """Return the exact order fields and optional sell-position evidence."""

        return {
            "order_id": self.order_id,
            "account_id": self.account_id,
            "security_id": self.security_id,
            "side": self.side.value,
            "quantity": _decimal_text(self.quantity),
            "limit_price": _decimal_text(self.limit_price),
            "sell_position_evidence": (
                self.sell_position_evidence.to_payload()
                if self.sell_position_evidence is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ExecutionTradingDecision:
    """Typed tradability result bound to an order and two evidence hashes.

    ALLOWED means only that the supplied rule, market, session, and required
    sell-balance evidence passed. Cash, account permission, risk policy, live
    gates, and broker acceptance are outside this result.
    """

    status: ExecutionDecisionStatus
    reason_codes: tuple[ExecutionDenyCode, ...]
    order_id: str
    rule_content_hash: str
    market_evidence_content_hash: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        """Validate decision status, ordered reasons, and input content-hash bindings."""

        _require_enum(self.status, ExecutionDecisionStatus, "status")
        _token(self.order_id, "order_id")
        _digest(self.rule_content_hash, "rule_content_hash")
        _digest(self.market_evidence_content_hash, "market_evidence_content_hash")
        _aware(self.evaluated_at, "evaluated_at")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not ExecutionDenyCode for reason in self.reason_codes
        ):
            raise ExecutionContractValidationError("reason_codes must be a tuple of deny codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ExecutionContractValidationError("reason_codes must be unique")
        if self.status is ExecutionDecisionStatus.ALLOWED and self.reason_codes:
            raise ExecutionContractValidationError("ALLOWED decision cannot contain reason_codes")
        if self.status is ExecutionDecisionStatus.DENIED and not self.reason_codes:
            raise ExecutionContractValidationError("DENIED decision requires reason_codes")

    def to_payload(self) -> dict[str, object]:
        """Return decision data; the envelope alone carries the evaluation clock."""

        return {
            "status": self.status.value,
            "reason_codes": [reason.value for reason in self.reason_codes],
            "order_id": self.order_id,
            "rule_content_hash": self.rule_content_hash,
            "market_evidence_content_hash": self.market_evidence_content_hash,
        }


def _evidence_time_codes(
    *,
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    as_of: datetime,
    not_yet_available: ExecutionDenyCode,
    expired: ExecutionDenyCode,
) -> tuple[ExecutionDenyCode, ...]:
    reasons: list[ExecutionDenyCode] = []
    if observed_at > as_of or available_at > as_of:
        reasons.append(not_yet_available)
    if as_of >= valid_until:
        reasons.append(expired)
    return tuple(reasons)


def _position_evidence_codes(
    evidence: SellPositionEvidence | None,
    *,
    order: ExecutionOrder,
    as_of: datetime,
    require_sellable_balance_to_zero: bool,
    require_zero_restricted_balance: bool = False,
) -> tuple[ExecutionDenyCode, ...]:
    if evidence is None:
        return (ExecutionDenyCode.POSITION_EVIDENCE_MISSING,)
    reasons: list[ExecutionDenyCode] = []
    if evidence.account_id != order.account_id:
        reasons.append(ExecutionDenyCode.POSITION_ACCOUNT_MISMATCH)
    if evidence.security_id != order.security_id:
        reasons.append(ExecutionDenyCode.POSITION_SECURITY_MISMATCH)
    reasons.extend(
        _evidence_time_codes(
            observed_at=evidence.observed_at,
            available_at=evidence.available_at,
            valid_until=evidence.valid_until,
            as_of=as_of,
            not_yet_available=ExecutionDenyCode.POSITION_EVIDENCE_NOT_YET_AVAILABLE,
            expired=ExecutionDenyCode.POSITION_EVIDENCE_EXPIRED,
        )
    )
    if evidence.completeness is not SellPositionCompleteness.COMPLETE:
        reasons.append(ExecutionDenyCode.POSITION_EVIDENCE_INCOMPLETE)
    if evidence.completeness is SellPositionCompleteness.COMPLETE:
        available_quantity = evidence.available_to_sell_quantity
        restricted_quantity = evidence.restricted_quantity
        if available_quantity is not None and order.quantity > available_quantity:
            reasons.append(ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT)
        if (
            require_sellable_balance_to_zero or require_zero_restricted_balance
        ) and restricted_quantity != Decimal("0"):
            reasons.append(ExecutionDenyCode.ODD_LOT_HAS_RESTRICTED_BALANCE)
        if require_sellable_balance_to_zero and available_quantity != order.quantity:
            reasons.append(ExecutionDenyCode.ODD_LOT_NOT_FULL_SELLABLE_BALANCE)
    return tuple(reasons)


def evaluate_execution_order(
    rule: AShareExecutionRule,
    market: ExecutionMarketEvidence,
    order: ExecutionOrder,
    as_of: datetime,
) -> ExecutionTradingDecision:
    """Evaluate one exact order against current rule, calendar, and market evidence.

    Missing or stale evidence and unknown states produce typed DENIED outcomes.
    No market defaults are inferred from symbol, board, or order side.
    """

    if type(rule) is not AShareExecutionRule:
        raise ExecutionContractValidationError("rule must be AShareExecutionRule")
    if type(market) is not ExecutionMarketEvidence:
        raise ExecutionContractValidationError("market must be ExecutionMarketEvidence")
    if type(order) is not ExecutionOrder:
        raise ExecutionContractValidationError("order must be ExecutionOrder")
    _aware(as_of, "as_of")
    try:
        rule.__post_init__()
        market.__post_init__()
        order.__post_init__()
    except ExecutionContractValidationError:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ExecutionContractValidationError(
            "typed execution input failed revalidation"
        ) from error

    reasons: list[ExecutionDenyCode] = []
    if rule.security_id != market.security_id:
        reasons.append(ExecutionDenyCode.RULE_MARKET_SECURITY_MISMATCH)
    if rule.market != market.market:
        reasons.append(ExecutionDenyCode.RULE_MARKET_MISMATCH)
    if rule.board != market.board:
        reasons.append(ExecutionDenyCode.RULE_BOARD_MISMATCH)
    if order.security_id != rule.security_id or order.security_id != market.security_id:
        reasons.append(ExecutionDenyCode.ORDER_SECURITY_MISMATCH)

    reasons.extend(
        _evidence_time_codes(
            observed_at=rule.source_observed_at,
            available_at=rule.source_available_at,
            valid_until=rule.valid_until,
            as_of=as_of,
            not_yet_available=ExecutionDenyCode.RULE_SOURCE_NOT_YET_AVAILABLE,
            expired=ExecutionDenyCode.RULE_SOURCE_EXPIRED,
        )
    )
    if as_of < rule.effective_from:
        reasons.append(ExecutionDenyCode.RULE_NOT_YET_EFFECTIVE)
    reasons.extend(
        _evidence_time_codes(
            observed_at=market.calendar_observed_at,
            available_at=market.calendar_available_at,
            valid_until=market.calendar_valid_until,
            as_of=as_of,
            not_yet_available=ExecutionDenyCode.CALENDAR_EVIDENCE_NOT_YET_AVAILABLE,
            expired=ExecutionDenyCode.CALENDAR_EVIDENCE_EXPIRED,
        )
    )
    reasons.extend(
        _evidence_time_codes(
            observed_at=market.market_observed_at,
            available_at=market.market_available_at,
            valid_until=market.market_valid_until,
            as_of=as_of,
            not_yet_available=ExecutionDenyCode.MARKET_EVIDENCE_NOT_YET_AVAILABLE,
            expired=ExecutionDenyCode.MARKET_EVIDENCE_EXPIRED,
        )
    )

    if market.session_state is SessionState.UNKNOWN:
        reasons.append(ExecutionDenyCode.SESSION_STATE_UNKNOWN)
    elif market.session_state is SessionState.CLOSED:
        reasons.append(ExecutionDenyCode.SESSION_CLOSED)
    local_as_of = as_of.astimezone(ZoneInfo(market.session_timezone))
    if local_as_of.date() != market.trading_date:
        reasons.append(ExecutionDenyCode.OUTSIDE_TRADING_DATE)
    if not market.session_open_at <= as_of < market.session_close_at:
        reasons.append(ExecutionDenyCode.OUTSIDE_SESSION)

    if market.security_state is SecurityTradingState.UNKNOWN:
        reasons.append(ExecutionDenyCode.SECURITY_STATE_UNKNOWN)
    elif market.security_state is SecurityTradingState.SUSPENDED:
        reasons.append(ExecutionDenyCode.SECURITY_SUSPENDED)
    elif market.security_state is SecurityTradingState.DELISTED:
        reasons.append(ExecutionDenyCode.SECURITY_DELISTED)

    if market.price_boundary_mode is PriceBoundaryMode.UNKNOWN:
        reasons.append(ExecutionDenyCode.PRICE_BOUNDARY_UNKNOWN)
    if not _is_decimal_multiple(market.reference_price, rule.price_tick):
        reasons.append(ExecutionDenyCode.REFERENCE_PRICE_NOT_ON_TICK)
    if not _is_decimal_multiple(order.limit_price, rule.price_tick):
        reasons.append(ExecutionDenyCode.LIMIT_PRICE_NOT_ON_TICK)
    if market.price_boundary_mode is PriceBoundaryMode.LIMITED:
        lower_limit = market.lower_limit_price
        upper_limit = market.upper_limit_price
        if lower_limit is not None and upper_limit is not None:
            if not lower_limit <= market.reference_price <= upper_limit:
                reasons.append(ExecutionDenyCode.REFERENCE_PRICE_OUTSIDE_BOUNDARY)
            if not lower_limit <= order.limit_price <= upper_limit:
                reasons.append(ExecutionDenyCode.LIMIT_PRICE_OUTSIDE_BOUNDARY)

    quantity_constraint = (
        rule.buy_quantity if order.side is ExecutionSide.BUY else rule.sell_quantity
    )
    if order.quantity > quantity_constraint.maximum:
        reasons.append(ExecutionDenyCode.QUANTITY_ABOVE_MAXIMUM)
    is_on_step = _is_decimal_multiple(order.quantity, quantity_constraint.step)
    is_sell = order.side is ExecutionSide.SELL
    needs_odd_lot_exception = is_sell and not is_on_step
    needs_sellable_balance_clear_exception = (
        is_sell
        and rule.sell_odd_lot_mode is SellOddLotMode.SELLABLE_BALANCE_TO_ZERO
        and (needs_odd_lot_exception or order.quantity < quantity_constraint.minimum)
    )
    needs_odd_remainder_once_exception = (
        is_sell
        and rule.sell_odd_lot_mode is SellOddLotMode.SELL_ODD_REMAINDER_ONCE
        and needs_odd_lot_exception
    )
    odd_lot_reasons: tuple[ExecutionDenyCode, ...] = ()
    position_reasons: tuple[ExecutionDenyCode, ...] = ()
    sellable_balance_clear_succeeded = False
    odd_remainder_once_succeeded = False
    if is_sell:
        position_reasons = _position_evidence_codes(
            order.sell_position_evidence,
            order=order,
            as_of=as_of,
            require_sellable_balance_to_zero=needs_sellable_balance_clear_exception,
            require_zero_restricted_balance=needs_odd_remainder_once_exception,
        )
        reasons.extend(position_reasons)
    if needs_odd_lot_exception:
        if needs_sellable_balance_clear_exception:
            odd_lot_reasons = position_reasons
        elif needs_odd_remainder_once_exception:
            position = order.sell_position_evidence
            available_quantity = (
                position.available_to_sell_quantity if position is not None else None
            )
            if (
                not position_reasons
                and available_quantity is not None
                and order.quantity <= available_quantity
                and _is_decimal_difference_multiple(
                    available_quantity, order.quantity, quantity_constraint.step
                )
            ):
                odd_remainder_once_succeeded = True
            elif not position_reasons:
                odd_lot_reasons = (ExecutionDenyCode.QUANTITY_NOT_ON_STEP,)
        else:
            odd_lot_reasons = (ExecutionDenyCode.QUANTITY_NOT_ON_STEP,)
        reasons.extend(odd_lot_reasons)
    if needs_sellable_balance_clear_exception:
        sellable_balance_clear_succeeded = not position_reasons
    if (
        order.quantity < quantity_constraint.minimum
        and not sellable_balance_clear_succeeded
        and not odd_remainder_once_succeeded
    ):
        reasons.append(ExecutionDenyCode.QUANTITY_BELOW_MINIMUM)
    if not is_on_step and not needs_odd_lot_exception:
        reasons.append(ExecutionDenyCode.QUANTITY_NOT_ON_STEP)

    stable_reasons = tuple(dict.fromkeys(reasons))
    status = ExecutionDecisionStatus.DENIED if stable_reasons else ExecutionDecisionStatus.ALLOWED
    return ExecutionTradingDecision(
        status=status,
        reason_codes=stable_reasons,
        order_id=order.order_id,
        rule_content_hash=rule.content_hash,
        market_evidence_content_hash=market.content_hash,
        evaluated_at=as_of,
    )


__all__: tuple[str, ...] = (
    "AShareExecutionRule",
    "EXECUTION_CONSTRAINTS_SCHEMA",
    "ExecutionContractValidationError",
    "ExecutionDecisionStatus",
    "ExecutionDenyCode",
    "ExecutionMarketEvidence",
    "ExecutionOrder",
    "ExecutionQuantityConstraint",
    "ExecutionSide",
    "ExecutionTradingDecision",
    "PriceBoundaryMode",
    "SecurityTradingState",
    "SellOddLotMode",
    "SellPositionCompleteness",
    "SellPositionEvidence",
    "SessionState",
    "evaluate_execution_order",
)
