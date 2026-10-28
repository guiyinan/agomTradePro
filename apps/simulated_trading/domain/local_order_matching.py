"""Pure rules for an explicitly requested daily-close simulated-order match.

The calculation models a conservative simulation assumption: a qualifying
daily close may support a bounded quantity for an order accepted before that
observation. It does not establish source provenance, real-world liquidity,
queue priority, persistence, event uniqueness, or account-level concurrency.
The Application owner must validate the source contract and supply its exact
facts, decision cutoff, and persisted same-session prior-event facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationError,
    OrderReservationStatus,
)

_SHARE_SCALE = 6
_ZERO_QUANTITY = Decimal("0.000000")
_MAX_POLICY_DIGITS = 64
_MAX_POLICY_EXPONENT = 64


class LocalMatchOutcome(StrEnum):
    """Describe whether the pure calculation matched, declined, or blocked."""

    MATCHED = "matched"
    NO_MATCH = "no_match"
    BLOCKED = "blocked"


class LocalMatchPriceAdjustment(StrEnum):
    """State whether the supplied close is an unadjusted market price."""

    UNADJUSTED = "unadjusted"
    FORWARD_ADJUSTED = "forward_adjusted"
    BACKWARD_ADJUSTED = "backward_adjusted"
    UNKNOWN = "unknown"


class LocalMatchVolumeUnit(StrEnum):
    """Unit carried by the source's daily traded-volume fact."""

    CANONICAL_SHARES = "canonical_shares"
    LOTS = "lots"
    UNKNOWN = "unknown"


class LocalMatchTradingState(StrEnum):
    """Trading-state qualification carried by the market observation."""

    TRADING = "trading"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class LocalMatchLimitState(StrEnum):
    """State whether daily price bounds apply and are known for an observation."""

    BOUNDED = "bounded"
    UNBOUNDED = "unbounded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LocalMatchPolicy:
    """Explicit simulation participation fraction and minimum share step."""

    participation_rate: Decimal
    share_step: Decimal


@dataclass(frozen=True, slots=True)
class LocalMatchObservation:
    """Immutable, fully dimensioned daily-close facts supplied by an owner.

    This value carries facts, not source qualification. The Application caller
    must verify the source's publication, freshness, security, session, units,
    and trading-state contract before creating this input.
    """

    security_id: str
    session_date: date
    observation_id: str
    observed_at: datetime
    available_at: datetime
    close_price: Decimal
    price_adjustment: LocalMatchPriceAdjustment
    traded_volume: Decimal
    volume_unit: LocalMatchVolumeUnit
    trading_state: LocalMatchTradingState
    limit_state: LocalMatchLimitState
    lower_limit_price: Decimal | None
    upper_limit_price: Decimal | None


@dataclass(frozen=True, slots=True)
class PriorLocalMatchEvent:
    """One already-persisted match quantity consuming same-session capacity.

    ``observation_id`` is retained as event identity evidence, but it does not
    partition capacity: all rows for the same account, security, and session
    consume the same daily allowance even if a provider or publication changes.
    """

    account_id: int
    security_id: str
    session_date: date
    observation_id: str
    event_id: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class LocalOrderMatchResult:
    """Immutable calculation outcome with no implicit quantity for blocked work."""

    outcome: LocalMatchOutcome
    reason_code: str
    matched_quantity: Decimal | None
    matched_price: Decimal | None

    def __post_init__(self) -> None:
        """Keep result fields consistent with their executable outcome."""

        if type(self.outcome) is not LocalMatchOutcome:
            raise ValueError("MATCH_RESULT_OUTCOME_INVALID")
        if type(self.reason_code) is not str or not self.reason_code:
            raise ValueError("MATCH_RESULT_REASON_INVALID")
        if self.outcome is LocalMatchOutcome.MATCHED:
            if (
                type(self.matched_quantity) is not Decimal
                or not self.matched_quantity.is_finite()
                or self.matched_quantity <= 0
                or type(self.matched_price) is not Decimal
                or not self.matched_price.is_finite()
                or self.matched_price <= 0
            ):
                raise ValueError("MATCH_RESULT_MATCHED_FIELDS_INVALID")
        elif self.outcome is LocalMatchOutcome.NO_MATCH:
            if (
                type(self.matched_quantity) is not Decimal
                or self.matched_quantity != _ZERO_QUANTITY
                or self.matched_price is not None
            ):
                raise ValueError("MATCH_RESULT_NO_MATCH_FIELDS_INVALID")
        elif self.matched_quantity is not None or self.matched_price is not None:
            raise ValueError("MATCH_RESULT_BLOCKED_FIELDS_MUST_BE_UNKNOWN")


class _LocalMatchInputError(ValueError):
    """Internal validation failure represented publicly as a BLOCKED result."""

    def __init__(self, code: str) -> None:
        """Retain a stable machine-readable reason code."""

        self.code = code
        super().__init__(code)


def _blocked(code: str) -> LocalOrderMatchResult:
    """Return a non-executable result without pretending unknown means zero."""

    return LocalOrderMatchResult(
        outcome=LocalMatchOutcome.BLOCKED,
        reason_code=code,
        matched_quantity=None,
        matched_price=None,
    )


def _no_match(code: str) -> LocalOrderMatchResult:
    """Return a known zero-quantity result for a valid but nonmatching case."""

    return LocalOrderMatchResult(
        outcome=LocalMatchOutcome.NO_MATCH,
        reason_code=code,
        matched_quantity=_ZERO_QUANTITY,
        matched_price=None,
    )


def _matched(quantity_units: int, price: Decimal) -> LocalOrderMatchResult:
    """Build a match using integer share units converted without context math."""

    return LocalOrderMatchResult(
        outcome=LocalMatchOutcome.MATCHED,
        reason_code="MATCHED",
        matched_quantity=_decimal_from_units(quantity_units),
        matched_price=price,
    )


def _need(condition: bool, code: str) -> None:
    """Raise a stable local validation error for one failed matcher invariant."""

    if not condition:
        raise _LocalMatchInputError(code)


def _require_token(value: object, field_name: str) -> None:
    """Require a bounded canonical token for market and persisted event identity."""

    _need(
        type(value) is str
        and bool(value)
        and value.strip() == value
        and len(value) <= 192
        and not any(character.isspace() for character in value),
        f"{field_name.upper()}_INVALID",
    )


def _aware_utc(value: object, field_name: str) -> datetime:
    """Validate an aware clock and normalize only its instant for comparison."""

    if type(value) is not datetime or value.tzinfo is None:
        raise _LocalMatchInputError(f"{field_name.upper()}_INVALID")
    try:
        if value.utcoffset() is None:
            raise _LocalMatchInputError(f"{field_name.upper()}_INVALID")
        return value.astimezone(UTC)
    except _LocalMatchInputError:
        raise
    except (OverflowError, TypeError, ValueError) as error:
        raise _LocalMatchInputError(f"{field_name.upper()}_INVALID") from error


def _integer_units(value: Decimal, *, scale: int, field_name: str) -> int:
    """Convert a validated fixed-scale Decimal into exact signed integer units."""

    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        raise _LocalMatchInputError(f"{field_name.upper()}_PRECISION_INVALID")
    coefficient = int("".join(str(digit) for digit in parts.digits))
    power = exponent + scale
    if power >= 0:
        scaled = coefficient * int(10**power)
    else:
        divisor = int(10 ** (-power))
        scaled, remainder = divmod(coefficient, divisor)
        _need(remainder == 0, f"{field_name.upper()}_PRECISION_INVALID")
    return (-1 if parts.sign else 1) * scaled


def _decimal_from_units(units: int) -> Decimal:
    """Build a six-decimal share amount directly from its exact integer units."""

    digits = str(abs(units))
    return Decimal((int(units < 0), tuple(int(character) for character in digits), -_SHARE_SCALE))


def _validated_price(value: object, field_name: str) -> Decimal:
    """Validate a positive ledger price and map failures to a stable match code."""

    try:
        return validate_ledger_price(value, field_name, allow_zero=False)
    except (SimulatedSettlementContractError, TypeError, ValueError, OverflowError) as error:
        raise _LocalMatchInputError(f"{field_name.upper()}_INVALID") from error


def _validated_quantity_units(value: object, field_name: str) -> int:
    """Validate a positive ledger share quantity and return exact micro-share units."""

    try:
        quantity = validate_ledger_quantity(value, field_name, allow_zero=False)
    except (SimulatedSettlementContractError, TypeError, ValueError, OverflowError) as error:
        raise _LocalMatchInputError(f"{field_name.upper()}_INVALID") from error
    return _integer_units(quantity, scale=_SHARE_SCALE, field_name=field_name)


def _validate_order(order: object) -> OrderReservation:
    """Require a valid active reservation as the original accepted order."""

    if type(order) is not OrderReservation:
        raise _LocalMatchInputError("ORDER_INVALID")
    try:
        order.__post_init__()
    except OrderReservationError as error:
        raise _LocalMatchInputError(error.code) from error
    except (SimulatedSettlementContractError, TypeError, ValueError, OverflowError) as error:
        raise _LocalMatchInputError("ORDER_INVALID") from error
    _need(order.status is OrderReservationStatus.ACTIVE, "ORDER_NOT_ACTIVE")
    _need(type(order.side) is SimulatedTradeSide, "ORDER_SIDE_INVALID")
    return order


def _validate_observation(
    observation: object,
    *,
    order: OrderReservation,
    as_of: datetime,
) -> tuple[datetime, Decimal, int]:
    """Validate daily-close facts, time identity, trading state, units, and limits."""

    if type(observation) is not LocalMatchObservation:
        raise _LocalMatchInputError("OBSERVATION_INVALID")
    _require_token(observation.security_id, "observation_security")
    _require_token(observation.observation_id, "observation_id")
    _need(type(observation.session_date) is date, "OBSERVATION_SESSION_INVALID")
    _need(
        observation.security_id == order.identity.security_id,
        "ORDER_OBSERVATION_SECURITY_MISMATCH",
    )

    observed_at = _aware_utc(observation.observed_at, "observation_observed_at")
    available_at = _aware_utc(observation.available_at, "observation_available_at")
    decision_cutoff = _aware_utc(as_of, "decision_cutoff")
    accepted_at = _aware_utc(order.reserved_at, "order_reserved_at")
    _need(accepted_at < observed_at, "ORDER_NOT_ACCEPTED_BEFORE_OBSERVATION")
    _need(
        observed_at <= available_at <= decision_cutoff,
        "OBSERVATION_NOT_AVAILABLE_AS_OF",
    )

    _need(
        type(observation.price_adjustment) is LocalMatchPriceAdjustment
        and observation.price_adjustment is LocalMatchPriceAdjustment.UNADJUSTED,
        "OBSERVATION_PRICE_ADJUSTMENT_INVALID",
    )
    _need(
        type(observation.volume_unit) is LocalMatchVolumeUnit
        and observation.volume_unit is LocalMatchVolumeUnit.CANONICAL_SHARES,
        "OBSERVATION_VOLUME_UNIT_INVALID",
    )
    _need(
        type(observation.trading_state) is LocalMatchTradingState
        and observation.trading_state is LocalMatchTradingState.TRADING,
        "OBSERVATION_TRADING_STATE_INVALID",
    )

    close_price = _validated_price(observation.close_price, "observation_close_price")
    traded_volume_units = 0
    if type(observation.traded_volume) is not Decimal or not observation.traded_volume.is_finite():
        raise _LocalMatchInputError("OBSERVATION_VOLUME_INVALID")
    try:
        traded_volume = validate_ledger_quantity(
            observation.traded_volume,
            "observation_traded_volume",
            allow_zero=True,
        )
    except (SimulatedSettlementContractError, TypeError, ValueError, OverflowError) as error:
        raise _LocalMatchInputError("OBSERVATION_VOLUME_INVALID") from error
    traded_volume_units = _integer_units(
        traded_volume,
        scale=_SHARE_SCALE,
        field_name="observation_traded_volume",
    )

    _need(type(observation.limit_state) is LocalMatchLimitState, "OBSERVATION_LIMIT_STATE_INVALID")
    if observation.limit_state is LocalMatchLimitState.UNKNOWN:
        raise _LocalMatchInputError("OBSERVATION_LIMIT_STATE_UNKNOWN")
    if observation.limit_state is LocalMatchLimitState.UNBOUNDED:
        _need(
            observation.lower_limit_price is None and observation.upper_limit_price is None,
            "OBSERVATION_UNBOUNDED_LIMITS_INVALID",
        )
    elif observation.limit_state is LocalMatchLimitState.BOUNDED:
        lower_limit = _validated_price(
            observation.lower_limit_price,
            "observation_lower_limit_price",
        )
        upper_limit = _validated_price(
            observation.upper_limit_price,
            "observation_upper_limit_price",
        )
        _need(lower_limit <= upper_limit, "OBSERVATION_LIMIT_RANGE_INVALID")
        _need(
            close_price > lower_limit and close_price < upper_limit,
            "OBSERVATION_AT_OR_OUTSIDE_LIMIT",
        )
    else:
        raise _LocalMatchInputError("OBSERVATION_LIMIT_STATE_INVALID")

    return observed_at, close_price, traded_volume_units


def _validate_policy(policy: object) -> tuple[int, int, int]:
    """Return the exact participation rational and share-step units."""

    if type(policy) is not LocalMatchPolicy:
        raise _LocalMatchInputError("MATCH_POLICY_INVALID")
    rate = policy.participation_rate
    if type(rate) is not Decimal or not rate.is_finite():
        raise _LocalMatchInputError("MATCH_PARTICIPATION_RATE_INVALID")
    parts = rate.as_tuple()
    exponent = parts.exponent
    if (
        not isinstance(exponent, int)
        or len(parts.digits) > _MAX_POLICY_DIGITS
        or abs(exponent) > _MAX_POLICY_EXPONENT
        or rate <= 0
        or rate > 1
    ):
        raise _LocalMatchInputError("MATCH_PARTICIPATION_RATE_INVALID")

    coefficient = int("".join(str(digit) for digit in parts.digits))
    if exponent >= 0:
        rate_numerator = coefficient * 10**exponent
        rate_denominator = 1
    else:
        rate_numerator = coefficient
        rate_denominator = 10 ** (-exponent)
    share_step_units = _validated_quantity_units(policy.share_step, "match_share_step")
    return rate_numerator, rate_denominator, share_step_units


def _validate_prior_events(
    prior_events: object,
    *,
    order: OrderReservation,
    observation: LocalMatchObservation,
) -> int:
    """Validate and sum persisted capacity events for this account/security/session."""

    if type(prior_events) is not tuple:
        raise _LocalMatchInputError("PRIOR_EVENTS_INVALID")
    seen_event_ids: set[str] = set()
    consumed_units = 0
    for event in prior_events:
        if type(event) is not PriorLocalMatchEvent:
            raise _LocalMatchInputError("PRIOR_EVENT_INVALID")
        if type(event.account_id) is not int or event.account_id <= 0:
            raise _LocalMatchInputError("PRIOR_EVENT_ACCOUNT_INVALID")
        _require_token(event.security_id, "prior_event_security")
        _require_token(event.observation_id, "prior_event_observation_id")
        _require_token(event.event_id, "prior_event_id")
        _need(type(event.session_date) is date, "PRIOR_EVENT_SESSION_INVALID")
        _need(
            event.account_id == order.identity.account_id
            and event.security_id == order.identity.security_id
            and event.session_date == observation.session_date,
            "PRIOR_EVENT_SCOPE_MISMATCH",
        )
        _need(event.event_id not in seen_event_ids, "PRIOR_EVENT_DUPLICATE")
        seen_event_ids.add(event.event_id)
        consumed_units += _validated_quantity_units(event.quantity, "prior_event_quantity")
    return consumed_units


def _floor_to_step(value_units: int, step_units: int) -> int:
    """Floor a nonnegative share-unit count to an explicit positive step."""

    return (value_units // step_units) * step_units


def _remaining_order_units(order: OrderReservation) -> int:
    """Return active original order quantity remaining in exact micro-share units."""

    total_units = _validated_quantity_units(order.quantity, "order_quantity")
    filled_units = _integer_units(
        order.filled_quantity, scale=_SHARE_SCALE, field_name="order_filled_quantity"
    )
    _need(total_units >= filled_units, "ORDER_REMAINING_QUANTITY_INVALID")
    return total_units - filled_units


def calculate_local_order_match(
    *,
    order: OrderReservation,
    observation: LocalMatchObservation,
    policy: LocalMatchPolicy,
    prior_events: tuple[PriorLocalMatchEvent, ...],
    as_of: datetime,
) -> LocalOrderMatchResult:
    """Calculate a conservative simulated match from one daily-close observation.

    The caller must establish source qualification before creating the typed
    observation and must read every already-persisted match event for the same
    account, security, and session. This function does not establish source
    authenticity, persist a source event, serialize competing matchers, enforce
    order/observation uniqueness, or apply the fill to the simulated ledger.
    The daily-close calculation is an explicit simulation assumption and does
    not assert real market liquidity or queue priority.
    """

    try:
        valid_order = _validate_order(order)
        valid_observation = observation
        _observed_at, close_price, volume_units = _validate_observation(
            valid_observation,
            order=valid_order,
            as_of=as_of,
        )
        rate_numerator, rate_denominator, share_step_units = _validate_policy(policy)
        prior_units = _validate_prior_events(
            prior_events,
            order=valid_order,
            observation=valid_observation,
        )

        raw_capacity_units = (volume_units * rate_numerator) // rate_denominator
        _need(prior_units <= raw_capacity_units, "PRIOR_MATCHES_EXCEED_DAILY_CAPACITY")

        is_crossing = (
            close_price <= valid_order.limit_price
            if valid_order.side is SimulatedTradeSide.BUY
            else close_price >= valid_order.limit_price
        )
        if not is_crossing:
            return _no_match("LIMIT_NOT_CROSSED")

        remaining_capacity_units = _floor_to_step(
            raw_capacity_units - prior_units,
            share_step_units,
        )
        order_remaining_units = _remaining_order_units(valid_order)
        matched_units = _floor_to_step(
            min(remaining_capacity_units, order_remaining_units),
            share_step_units,
        )
        if matched_units <= 0:
            return _no_match("ZERO_MATCH_CAPACITY")
        return _matched(matched_units, close_price)
    except _LocalMatchInputError as error:
        return _blocked(error.code)
    except (SimulatedSettlementContractError, TypeError, ValueError, OverflowError) as error:
        if isinstance(error, OrderReservationError):
            return _blocked(error.code)
        return _blocked("MATCH_INPUT_INVALID")
