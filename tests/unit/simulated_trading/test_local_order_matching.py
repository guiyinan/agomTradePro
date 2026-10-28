"""Pure-domain contracts for conservative daily-close order matching."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast

import pytest

from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchLimitState,
    LocalMatchObservation,
    LocalMatchOutcome,
    LocalMatchPolicy,
    LocalMatchPriceAdjustment,
    LocalMatchTradingState,
    LocalMatchVolumeUnit,
    LocalOrderMatchResult,
    PriorLocalMatchEvent,
    calculate_local_order_match,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationIdentity,
    OrderReservationStatus,
)

SESSION = date(2026, 10, 27)
OBSERVED_AT = datetime(2026, 10, 27, 7, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 10, 27, 7, 5, tzinfo=UTC)
AS_OF = datetime(2026, 10, 27, 7, 10, tzinfo=UTC)
ORDER_ACCEPTED_AT = OBSERVED_AT - timedelta(minutes=1)
SECURITY_ID = "SH.600000"
ACCOUNT_ID = 19


def _order(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("500"),
    filled_quantity: Decimal = Decimal("0"),
    limit_price: Decimal = Decimal("10.0100"),
    security_id: str = SECURITY_ID,
    account_id: int = ACCOUNT_ID,
    reserved_at: datetime = ORDER_ACCEPTED_AT,
) -> OrderReservation:
    """Build an immutable active reservation with internally consistent holds."""

    notional = (quantity * limit_price).quantize(Decimal("0.01"))
    filled_notional = (filled_quantity * limit_price).quantize(Decimal("0.01"))
    is_buy = side is SimulatedTradeSide.BUY
    return OrderReservation(
        identity=OrderReservationIdentity(
            account_id=account_id,
            security_id=security_id,
            idempotency_key="local-match-order",
            request_payload_hash="a" * 64,
        ),
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        notional=notional,
        fee_estimate=Decimal("0.00"),
        fee_budget=Decimal("0.00") if is_buy else None,
        cash_reserved=notional if is_buy else Decimal("0.00"),
        shares_reserved=Decimal("0") if is_buy else quantity,
        reserved_at=reserved_at,
        status=OrderReservationStatus.ACTIVE,
        filled_quantity=filled_quantity,
        cash_consumed=filled_notional if is_buy else Decimal("0.00"),
        shares_consumed=Decimal("0") if is_buy else filled_quantity,
    )


def _observation(**changes: object) -> LocalMatchObservation:
    """Build one explicitly dimensioned close observation for unit examples."""

    observation = LocalMatchObservation(
        security_id=SECURITY_ID,
        session_date=SESSION,
        observation_id="close-observation-v1",
        observed_at=OBSERVED_AT,
        available_at=AVAILABLE_AT,
        close_price=Decimal("10.0000"),
        price_adjustment=LocalMatchPriceAdjustment.UNADJUSTED,
        traded_volume=Decimal("10000"),
        volume_unit=LocalMatchVolumeUnit.CANONICAL_SHARES,
        trading_state=LocalMatchTradingState.TRADING,
        limit_state=LocalMatchLimitState.BOUNDED,
        lower_limit_price=Decimal("9.0000"),
        upper_limit_price=Decimal("11.0000"),
    )
    return replace(observation, **changes)


def _policy(
    *,
    participation_rate: Decimal = Decimal("0.05"),
    share_step: Decimal = Decimal("100"),
) -> LocalMatchPolicy:
    """Build a fully explicit policy; the matcher supplies no business defaults."""

    return LocalMatchPolicy(
        participation_rate=participation_rate,
        share_step=share_step,
    )


def _prior_event(
    *,
    account_id: int = ACCOUNT_ID,
    security_id: str = SECURITY_ID,
    session_date: date = SESSION,
    observation_id: str = "earlier-close-publication",
    event_id: str = "persisted-match-e1",
    quantity: Decimal = Decimal("300"),
) -> PriorLocalMatchEvent:
    """Build one prior persisted source-event summary in the same session."""

    return PriorLocalMatchEvent(
        account_id=account_id,
        security_id=security_id,
        session_date=session_date,
        observation_id=observation_id,
        event_id=event_id,
        quantity=quantity,
    )


def _match(
    *,
    order: OrderReservation | None = None,
    observation: LocalMatchObservation | None = None,
    policy: LocalMatchPolicy | None = None,
    prior_events: tuple[PriorLocalMatchEvent, ...] = (),
    as_of: datetime = AS_OF,
) -> LocalOrderMatchResult:
    """Call the matcher with explicit current-scope examples."""

    return calculate_local_order_match(
        order=_order() if order is None else order,
        observation=_observation() if observation is None else observation,
        policy=_policy() if policy is None else policy,
        prior_events=prior_events,
        as_of=as_of,
    )


def _assert_blocked(result: LocalOrderMatchResult) -> None:
    """Require a blocked result to be non-executable and machine-readable."""

    assert result.outcome is LocalMatchOutcome.BLOCKED
    assert result.matched_quantity is None
    assert result.matched_price is None
    assert isinstance(result.reason_code, str)
    assert result.reason_code


def test_buy_close_matching_uses_explicit_capacity_and_original_limit() -> None:
    result = _match()

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("500")
    assert result.matched_price == Decimal("10.0000")


def test_sell_close_matching_uses_opposite_original_limit_direction() -> None:
    result = _match(order=_order(side=SimulatedTradeSide.SELL, limit_price=Decimal("9.9900")))

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("500")
    assert result.matched_price == Decimal("10.0000")


@pytest.mark.parametrize(
    ("side", "limit_price"),
    (
        (SimulatedTradeSide.BUY, Decimal("9.9900")),
        (SimulatedTradeSide.SELL, Decimal("10.0100")),
    ),
)
def test_non_crossing_close_returns_an_explicit_no_match(
    side: SimulatedTradeSide,
    limit_price: Decimal,
) -> None:
    result = _match(order=_order(side=side, limit_price=limit_price))

    assert result.outcome is LocalMatchOutcome.NO_MATCH
    assert result.matched_quantity == Decimal("0")
    assert result.matched_price is None
    assert result.reason_code


def test_known_zero_volume_returns_no_match_and_missing_volume_blocks() -> None:
    no_volume = _match(observation=_observation(traded_volume=Decimal("0")))
    missing_volume = _match(observation=_observation(traded_volume=None))

    assert no_volume.outcome is LocalMatchOutcome.NO_MATCH
    assert no_volume.matched_quantity == Decimal("0")
    _assert_blocked(missing_volume)


def test_prior_session_events_reduce_capacity_across_observation_versions() -> None:
    order = _order(filled_quantity=Decimal("300"))
    prior_events = (
        _prior_event(
            event_id="persisted-match-e1",
            observation_id="provider-a-publication-1",
            quantity=Decimal("100"),
        ),
        _prior_event(
            event_id="persisted-match-e2",
            observation_id="provider-b-publication-7",
            quantity=Decimal("200"),
        ),
    )

    result = _match(order=order, prior_events=prior_events)

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("200")
    assert result.matched_price == Decimal("10.0000")


def test_remaining_capacity_is_floored_to_the_explicit_share_step() -> None:
    result = _match(
        prior_events=(_prior_event(quantity=Decimal("175")),),
    )

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("300")
    assert result.matched_quantity % Decimal("100") == 0


def test_prior_usage_above_the_daily_allowance_blocks_new_matching() -> None:
    result = _match(
        prior_events=(_prior_event(quantity=Decimal("600")),),
    )

    _assert_blocked(result)


def test_capacity_is_rounded_after_subtracting_prior_order_consumption() -> None:
    """A prior partial fill must not discard usable fractional-step daily capacity."""
    result = _match(
        observation=_observation(traded_volume=Decimal("11800")),
        prior_events=(_prior_event(quantity=Decimal("75")),),
    )

    # 11800 * 0.05 - 75 = 515 shares: the new order may match 500.
    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("500")


def test_non_crossing_limit_does_not_hide_inconsistent_prior_consumption() -> None:
    """A known no-crossing price cannot turn invalid history into an accepted no-match."""
    result = _match(
        order=_order(limit_price=Decimal("9.9900")),
        prior_events=(_prior_event(quantity=Decimal("600")),),
    )

    _assert_blocked(result)


@pytest.mark.parametrize(
    "event",
    (
        _prior_event(account_id=ACCOUNT_ID + 1),
        _prior_event(security_id="SH.600001"),
        _prior_event(session_date=date(2026, 10, 26)),
    ),
)
def test_prior_event_from_another_account_security_or_session_blocks(
    event: PriorLocalMatchEvent,
) -> None:
    _assert_blocked(_match(prior_events=(event,)))


def test_duplicate_prior_event_id_blocks_double_count_or_corrupt_input() -> None:
    event = _prior_event()
    duplicate = replace(event, observation_id="another-publication")

    _assert_blocked(_match(prior_events=(event, duplicate)))


def test_order_security_must_match_the_observation_security() -> None:
    order = _order(security_id="SH.600001")

    _assert_blocked(_match(order=order))


@pytest.mark.parametrize(
    "reserved_at",
    (
        OBSERVED_AT,
        OBSERVED_AT + timedelta(microseconds=1),
    ),
)
def test_order_must_be_accepted_strictly_before_the_market_observation(
    reserved_at: datetime,
) -> None:
    _assert_blocked(_match(order=_order(reserved_at=reserved_at)))


@pytest.mark.parametrize(
    ("observed_at", "available_at", "as_of"),
    (
        (None, AVAILABLE_AT, AS_OF),
        (OBSERVED_AT.replace(tzinfo=None), AVAILABLE_AT, AS_OF),
        (OBSERVED_AT, OBSERVED_AT - timedelta(seconds=1), AS_OF),
        (OBSERVED_AT, AS_OF + timedelta(seconds=1), AS_OF),
        (AS_OF + timedelta(seconds=1), AS_OF + timedelta(seconds=2), AS_OF),
    ),
)
def test_observation_clocks_must_be_aware_ordered_and_visible_by_explicit_cutoff(
    observed_at: datetime | None,
    available_at: datetime,
    as_of: datetime,
) -> None:
    observation = _observation(observed_at=observed_at, available_at=available_at)

    _assert_blocked(_match(observation=observation, as_of=cast(datetime, as_of)))


@pytest.mark.parametrize(
    "as_of",
    (
        AS_OF.replace(tzinfo=None),
        None,
    ),
)
def test_decision_cutoff_must_be_explicit_and_timezone_aware(as_of: datetime | None) -> None:
    _assert_blocked(_match(as_of=cast(datetime, as_of)))


@pytest.mark.parametrize(
    "observation_changes",
    (
        {"session_date": datetime(2026, 10, 27, tzinfo=UTC)},
        {"observation_id": ""},
        {"close_price": None},
        {"close_price": True},
        {"close_price": Decimal("NaN")},
        {"close_price": Decimal("Infinity")},
        {"close_price": Decimal("10.00001")},
        {"traded_volume": True},
        {"traded_volume": Decimal("NaN")},
        {"traded_volume": Decimal("Infinity")},
        {"traded_volume": Decimal("10000.0000001")},
        {"traded_volume": Decimal("-1")},
    ),
)
def test_malformed_prices_volumes_and_observation_identity_block(
    observation_changes: dict[str, object],
) -> None:
    result = _match(observation=_observation(**observation_changes))

    _assert_blocked(result)


@pytest.mark.parametrize(
    "changes",
    (
        {"price_adjustment": LocalMatchPriceAdjustment.FORWARD_ADJUSTED},
        {"price_adjustment": LocalMatchPriceAdjustment.UNKNOWN},
        {"volume_unit": LocalMatchVolumeUnit.UNKNOWN},
        {"volume_unit": LocalMatchVolumeUnit.LOTS},
        {"trading_state": LocalMatchTradingState.SUSPENDED},
        {"trading_state": LocalMatchTradingState.UNKNOWN},
        {"trading_state": "trading"},
    ),
)
def test_adjusted_unknown_or_nontrading_observations_block(
    changes: dict[str, object],
) -> None:
    _assert_blocked(_match(observation=_observation(**changes)))


@pytest.mark.parametrize(
    "changes",
    (
        {"limit_state": LocalMatchLimitState.UNKNOWN},
        {"limit_state": LocalMatchLimitState.BOUNDED, "close_price": Decimal("11.0000")},
        {"limit_state": LocalMatchLimitState.BOUNDED, "close_price": Decimal("9.0000")},
        {"limit_state": LocalMatchLimitState.BOUNDED, "close_price": Decimal("11.0100")},
        {"limit_state": LocalMatchLimitState.BOUNDED, "upper_limit_price": None},
        {
            "limit_state": LocalMatchLimitState.BOUNDED,
            "lower_limit_price": Decimal("12.0000"),
            "upper_limit_price": Decimal("11.0000"),
        },
        {
            "limit_state": LocalMatchLimitState.BOUNDED,
            "upper_limit_price": Decimal("NaN"),
        },
        {
            "limit_state": LocalMatchLimitState.UNBOUNDED,
            "upper_limit_price": Decimal("11.0000"),
        },
    ),
)
def test_unknown_or_inconsistent_daily_limit_evidence_blocks(
    changes: dict[str, object],
) -> None:
    _assert_blocked(_match(observation=_observation(**changes)))


def test_explicit_unbounded_market_does_not_mean_unknown_limits() -> None:
    observation = _observation(
        limit_state=LocalMatchLimitState.UNBOUNDED,
        lower_limit_price=None,
        upper_limit_price=None,
    )

    result = _match(observation=observation)

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("500")


@pytest.mark.parametrize(
    "policy_changes",
    (
        {"participation_rate": None},
        {"participation_rate": True},
        {"participation_rate": Decimal("NaN")},
        {"participation_rate": Decimal("0")},
        {"participation_rate": Decimal("1.01")},
        {"share_step": None},
        {"share_step": True},
        {"share_step": Decimal("0")},
        {"share_step": Decimal("0.0000001")},
        {"share_step": Decimal("Infinity")},
    ),
)
def test_missing_boolean_nonfinite_or_invalid_policy_blocks(
    policy_changes: dict[str, object],
) -> None:
    policy = replace(_policy(), **policy_changes)

    _assert_blocked(_match(policy=policy))


def test_bad_prior_quantity_or_non_tuple_prior_collection_blocks() -> None:
    invalid_quantity = replace(_prior_event(), quantity=Decimal("NaN"))

    _assert_blocked(_match(prior_events=(invalid_quantity,)))
    _assert_blocked(_match(prior_events=cast(tuple[PriorLocalMatchEvent, ...], [_prior_event()])))


def test_capacity_multiplication_and_flooring_ignore_low_ambient_decimal_precision() -> None:
    order = _order(quantity=Decimal("5000"), limit_price=Decimal("10.0000"))
    observation = _observation(traded_volume=Decimal("12345.678900"))
    policy = _policy(
        participation_rate=Decimal("0.17"),
        share_step=Decimal("100"),
    )

    with localcontext() as context:
        context.prec = 2
        result = _match(order=order, observation=observation, policy=policy)

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("2000")
    assert result.matched_price == Decimal("10.0000")


def test_cancelled_order_cannot_generate_a_new_matching_decision() -> None:
    """A valid released reservation stays terminal even with crossing market facts."""
    order = _order()
    cancelled = replace(
        order,
        status=OrderReservationStatus.CANCELLED,
        cash_released=order.cash_reserved,
    )

    _assert_blocked(_match(order=cancelled))


@pytest.mark.parametrize("field", ("order", "observation", "policy"))
def test_missing_typed_inputs_cannot_be_interpreted_as_matching_defaults(field: str) -> None:
    """Malformed direct callers must not obtain implicit business inputs."""
    inputs: dict[str, object] = {
        "order": _order(),
        "observation": _observation(),
        "policy": _policy(),
        "prior_events": (),
        "as_of": AS_OF,
    }
    inputs[field] = None

    _assert_blocked(calculate_local_order_match(**inputs))


def test_invalid_reservation_conservation_is_rejected_before_matching() -> None:
    """Revalidate frozen values received across a boundary before using remaining shares."""
    order = _order()
    object.__setattr__(order, "cash_reserved", Decimal("1.00"))

    _assert_blocked(_match(order=order))


@pytest.mark.parametrize(
    "event",
    (None, replace(_prior_event(), account_id=True)),
)
def test_missing_or_boolean_prior_event_identity_blocks_capacity_claims(event: object) -> None:
    _assert_blocked(_match(prior_events=cast(tuple[PriorLocalMatchEvent, ...], (event,))))


def test_timezone_representation_and_decimal_trailing_zeroes_preserve_the_match() -> None:
    """Equal instants and exact quantities retain one numerical result."""
    from datetime import timezone

    order = _order(filled_quantity=Decimal("300.0000000"))
    observation = _observation(
        observed_at=OBSERVED_AT.astimezone(timezone(timedelta(hours=8))),
        available_at=AVAILABLE_AT.astimezone(timezone(timedelta(hours=-5))),
    )

    result = _match(order=order, observation=observation)

    assert result.outcome is LocalMatchOutcome.MATCHED
    assert result.matched_quantity == Decimal("200")


@pytest.mark.parametrize(
    ("outcome", "reason_code", "quantity", "price"),
    (
        ("matched", "MATCHED", Decimal("100"), Decimal("10")),
        (LocalMatchOutcome.MATCHED, "", Decimal("100"), Decimal("10")),
        (LocalMatchOutcome.MATCHED, "MATCHED", Decimal("0"), Decimal("10")),
        (LocalMatchOutcome.MATCHED, "MATCHED", Decimal("100"), None),
        (LocalMatchOutcome.NO_MATCH, "ZERO_CAPACITY", Decimal("100"), None),
        (LocalMatchOutcome.BLOCKED, "UNKNOWN", Decimal("0"), None),
        (LocalMatchOutcome.BLOCKED, "UNKNOWN", None, Decimal("10")),
    ),
)
def test_result_contract_cannot_claim_executable_or_known_values_for_wrong_outcomes(
    outcome: object,
    reason_code: str,
    quantity: Decimal | None,
    price: Decimal | None,
) -> None:
    with pytest.raises(ValueError):
        LocalOrderMatchResult(
            outcome=cast(LocalMatchOutcome, outcome),
            reason_code=reason_code,
            matched_quantity=quantity,
            matched_price=price,
        )
