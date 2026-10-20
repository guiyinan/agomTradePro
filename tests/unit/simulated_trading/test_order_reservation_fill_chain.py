"""Test the persisted G2 fill economics chain independently of its writer."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_primitives import _hash_payload
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationError,
    OrderReservationRequest,
    reserve_order,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillEconomics,
    OrderReservationFillRequest,
    _payload_for_economics,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_chain import (
    OrderReservationFillChainEntry,
    validate_order_reservation_fill_chain,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
ZERO = Decimal("0.00")
ZERO_SHARES = Decimal("0.000000")
ZERO_FEES = TradeFeeBreakdown(ZERO, ZERO, ZERO, ZERO, ZERO)


def _intent(
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    quantity: Decimal = Decimal("100.000000"),
    price: Decimal = Decimal("10.0000"),
    key: str = "chain-order-001",
) -> SimulatedTradeIntent:
    """Build a complete intent for pure persisted-chain tests."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key=key,
        side=side,
        security_id="SH.FILL.SECURITY",
        asset_code="600000.SH",
        asset_name="chain test security",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=quantity,
        price=price,
        reason="test-only persisted fee chain",
        signal_id=None,
    )


def _fee_policy(
    *,
    min_commission: Decimal = Decimal("5"),
    commission_rate: Decimal = Decimal("0.0003"),
) -> SimulatedFeePolicyV2:
    """Build the exact-case frozen FeeV2 input used by the existing G2 tests."""

    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=commission_rate,
        commission_rate_sell=commission_rate,
        min_commission=min_commission,
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=FeeApplicability.APPLIES,
            slippage=FeeApplicability.APPLIES,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    start = AS_OF - timedelta(days=1)
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="fill-chain-test-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=start,
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=start,
        transaction_cases=cases,
    )


def _reservation(
    intent: SimulatedTradeIntent,
    *,
    fee_policy: SimulatedFeePolicyV2,
    fee_budget: Decimal = Decimal("100.00"),
) -> OrderReservation:
    """Create a parent from the real pure G1 reserve calculation."""

    request = OrderReservationRequest(
        account_id=intent.account_id,
        security_id=intent.security_id,
        idempotency_key=intent.idempotency_key,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.price,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        fee_budget=fee_budget if intent.side is SimulatedTradeSide.BUY else None,
    )
    book = OrderReservationBook(
        intent.account_id,
        intent.security_id,
        Decimal("1000000.00"),
        None,
        Decimal("1000000.000000"),
        (),
    )
    return reserve_order(book, request, fee_policy, reserved_at=AS_OF).reservation


def _initial_accrual() -> OrderReservationFillAccrual:
    """Declare the only valid no-fill starting state."""

    return OrderReservationFillAccrual(
        fill_count=0,
        cumulative_quantity=ZERO_SHARES,
        cumulative_gross=ZERO,
        cumulative_fees=ZERO_FEES,
    )


def _prepare(
    *,
    intent: SimulatedTradeIntent,
    reservation: OrderReservation,
    fee_policy: SimulatedFeePolicyV2,
    event_id: str,
    quantity: Decimal,
    price: Decimal,
    prior: OrderReservationFillAccrual | None = None,
    close_order: bool = False,
) -> OrderReservationFillEconomics:
    """Build one immutable row through the unchanged single-fill API."""

    return prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=event_id,
            intent=intent,
            stored_intent_payload_hash=intent.request_payload_hash,
            reservation=reservation,
            fee_policy=fee_policy,
            fill_occurred_at=AS_OF,
            quantity=quantity,
            price=price,
            prior=prior or _initial_accrual(),
            close_order=close_order,
        )
    )


def _apply_fill_for_chain_fixture(
    reservation: OrderReservation,
    economics: OrderReservationFillEconomics,
) -> OrderReservation:
    """Advance only G1's typed quantity/status fixture; chain validation ignores resources."""

    cash_consumed = Decimal("0.01") if reservation.side is SimulatedTradeSide.BUY else ZERO
    return reservation.apply_fill(
        filled_quantity=economics.quantity,
        cash_consumed=cash_consumed,
        close_order=economics.close_order,
    )


def _two_fills(
    *,
    quantity: Decimal = Decimal("100.000000"),
    first_quantity: Decimal = Decimal("50.000000"),
    second_quantity: Decimal = Decimal("50.000000"),
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    close_second: bool = False,
) -> tuple[
    SimulatedTradeIntent,
    SimulatedFeePolicyV2,
    OrderReservation,
    OrderReservation,
    OrderReservation,
    OrderReservationFillEconomics,
    OrderReservationFillEconomics,
]:
    """Create a valid two-row math chain and a matching G1 parent state."""

    intent = _intent(side=side, quantity=quantity)
    policy = _fee_policy()
    initial = _reservation(intent, fee_policy=policy)
    first = _prepare(
        intent=intent,
        reservation=initial,
        fee_policy=policy,
        event_id="chain-fill-001",
        quantity=first_quantity,
        price=Decimal("10.0000"),
    )
    after_first = _apply_fill_for_chain_fixture(initial, first)
    second = _prepare(
        intent=intent,
        reservation=after_first,
        fee_policy=policy,
        event_id="chain-fill-002",
        quantity=second_quantity,
        price=Decimal("10.0000"),
        prior=first.cumulative_state,
        close_order=close_second,
    )
    after_second = _apply_fill_for_chain_fixture(after_first, second)
    return intent, policy, initial, after_first, after_second, first, second


def _reseal_request_hash(
    economics: OrderReservationFillEconomics,
    *,
    asset_code: str | None = None,
    fill_occurred_at: datetime | None = None,
    intent_payload_hash: str | None = None,
    limit_price: Decimal | None = None,
    side: SimulatedTradeSide | None = None,
    user_id: int | None = None,
) -> OrderReservationFillEconomics:
    """Change immutable request fields and recompute their canonical request hash."""

    next_asset_code = economics.asset_code if asset_code is None else asset_code
    next_occurred_at = economics.fill_occurred_at if fill_occurred_at is None else fill_occurred_at
    next_intent_hash = (
        economics.intent_payload_hash if intent_payload_hash is None else intent_payload_hash
    )
    next_limit_price = economics.limit_price if limit_price is None else limit_price
    next_side = economics.side if side is None else side
    next_user_id = economics.user_id if user_id is None else user_id
    payload = _payload_for_economics(
        fill_event_id=economics.fill_event_id,
        identity=economics.reservation_identity,
        user_id=next_user_id,
        intent_payload_hash=next_intent_hash,
        fee_policy_hash=economics.fee_policy_hash,
        side=next_side,
        asset_code=next_asset_code,
        asset_type=economics.asset_type,
        market=economics.market,
        board=economics.board,
        limit_price=next_limit_price,
        quantity=economics.quantity,
        price=economics.price,
        fill_occurred_at=next_occurred_at,
        close_order=economics.close_order,
    )
    return replace(
        economics,
        asset_code=next_asset_code,
        fill_occurred_at=next_occurred_at,
        intent_payload_hash=next_intent_hash,
        limit_price=next_limit_price,
        side=next_side,
        user_id=next_user_id,
        payload_hash=_hash_payload(payload),
    )


def _chain(
    intent: SimulatedTradeIntent,
    policy: SimulatedFeePolicyV2,
    reservation: OrderReservation,
    entries: tuple[OrderReservationFillChainEntry, ...],
) -> OrderReservationFillAccrual:
    """Invoke the proposed pure whole-history validator."""

    return validate_order_reservation_fill_chain(
        intent=intent,
        stored_intent_payload_hash=intent.request_payload_hash,
        reservation=reservation,
        fee_policy=policy,
        entries=entries,
    )


def test_valid_complete_chain_reprices_fee_v2_from_the_zero_prefix() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()

    result = _chain(
        intent,
        policy,
        completed,
        (OrderReservationFillChainEntry(1, first), OrderReservationFillChainEntry(2, second)),
    )

    assert completed.status.value == "completed"
    assert result.fill_count == 2
    assert result.cumulative_quantity == Decimal("100.000000")
    assert result.cumulative_gross == Decimal("1000.00")
    assert first.incremental_fees.commission == Decimal("5.00")
    assert second.incremental_fees.commission == ZERO
    assert result.cumulative_fees.commission == Decimal("5.00")


def test_two_rows_with_self_consistent_but_skipped_prior_are_rejected() -> None:
    intent = _intent(quantity=Decimal("100.000000"), price=Decimal("20.0000"))
    policy = _fee_policy()
    initial = _reservation(intent, fee_policy=policy)
    first = _prepare(
        intent=intent,
        reservation=initial,
        fee_policy=policy,
        event_id="actual-prefix",
        quantity=Decimal("50.000000"),
        price=Decimal("10.0000"),
    )
    alternate_prefix = _prepare(
        intent=intent,
        reservation=initial,
        fee_policy=policy,
        event_id="different-prefix",
        quantity=Decimal("50.000000"),
        price=Decimal("11.0000"),
    )
    alternate_parent = _apply_fill_for_chain_fixture(initial, alternate_prefix)
    second = _prepare(
        intent=intent,
        reservation=alternate_parent,
        fee_policy=policy,
        event_id="later-fill",
        quantity=Decimal("50.000000"),
        price=Decimal("9.0000"),
        prior=alternate_prefix.cumulative_state,
    )
    actual_parent = _apply_fill_for_chain_fixture(initial, first)
    completed = _apply_fill_for_chain_fixture(actual_parent, second)

    first.__post_init__()
    second.__post_init__()
    assert second.prior == alternate_prefix.cumulative_state
    assert second.prior != first.cumulative_state
    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (OrderReservationFillChainEntry(1, first), OrderReservationFillChainEntry(2, second)),
        )

    assert raised.value.code == "FILL_CHAIN_PRIOR_MISMATCH"


def test_self_consistent_changed_first_gross_breaks_the_following_prior() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    changed_first = _prepare(
        intent=intent,
        reservation=_reservation(intent, fee_policy=policy),
        fee_policy=policy,
        event_id=first.fill_event_id,
        quantity=Decimal("51.000000"),
        price=Decimal("10.0000"),
    )
    changed_first.__post_init__()
    assert changed_first.gross_amount == Decimal("510.00")
    assert changed_first.payload_hash != first.payload_hash

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (
                OrderReservationFillChainEntry(1, changed_first),
                OrderReservationFillChainEntry(2, second),
            ),
        )

    assert raised.value.code == "FILL_CHAIN_PRIOR_MISMATCH"


@pytest.mark.parametrize(
    "entries",
    [
        "gap",
        "duplicate",
        "reverse",
    ],
)
def test_chain_requires_unique_contiguous_ordered_sequence(entries: str) -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    valid_entries = (
        OrderReservationFillChainEntry(1, first),
        OrderReservationFillChainEntry(2, second),
    )
    invalid_entries = {
        "gap": (valid_entries[0], OrderReservationFillChainEntry(3, second)),
        "duplicate": (valid_entries[0], OrderReservationFillChainEntry(1, second)),
        "reverse": (valid_entries[1], valid_entries[0]),
    }[entries]

    with pytest.raises(OrderReservationError) as raised:
        _chain(intent, policy, completed, invalid_entries)

    assert raised.value.code == "FILL_CHAIN_SEQUENCE_INVALID"


def test_first_persisted_row_cannot_claim_a_nonzero_prior() -> None:
    intent, policy, _, after_first, _, first, second = _two_fills()
    assert second.prior == first.cumulative_state

    with pytest.raises(OrderReservationError) as raised:
        _chain(intent, policy, after_first, (OrderReservationFillChainEntry(1, second),))

    assert raised.value.code == "FILL_CHAIN_PRIOR_MISMATCH"


def test_self_consistent_fee_reseal_is_recomputed_against_frozen_fee_v2() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    forged_incremental = replace(
        first.incremental_fees,
        commission=Decimal("6.00"),
        total_fee=first.incremental_fees.total_fee + Decimal("1.00"),
    )
    forged_cumulative_fees = replace(
        first.cumulative_state.cumulative_fees,
        commission=Decimal("6.00"),
        total_fee=first.cumulative_state.cumulative_fees.total_fee + Decimal("1.00"),
    )
    forged_first = replace(
        first,
        incremental_fees=forged_incremental,
        cumulative_state=replace(first.cumulative_state, cumulative_fees=forged_cumulative_fees),
    )
    forged_first.__post_init__()
    assert forged_first.payload_hash == first.payload_hash

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (
                OrderReservationFillChainEntry(1, forged_first),
                OrderReservationFillChainEntry(2, second),
            ),
        )

    assert raised.value.code == "FILL_CHAIN_ECONOMICS_MISMATCH"


def test_changed_metadata_with_a_valid_request_hash_still_must_match_parent() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    forged_first = _reseal_request_hash(first, asset_code="601000.SH")
    forged_first.__post_init__()

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (
                OrderReservationFillChainEntry(1, forged_first),
                OrderReservationFillChainEntry(2, second),
            ),
        )

    assert raised.value.code == "FILL_CHAIN_ECONOMICS_PARENT_MISMATCH"


@pytest.mark.parametrize(
    "field_name",
    [
        "side",
        "limit_price",
        "user_id",
        "intent_payload_hash",
    ],
)
def test_resealed_single_fill_identity_fields_remain_bound_to_parent(
    field_name: str,
) -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    if field_name == "side":
        forged = _reseal_request_hash(first, side=SimulatedTradeSide.SELL)
    elif field_name == "limit_price":
        forged = _reseal_request_hash(first, limit_price=Decimal("11.0000"))
    elif field_name == "user_id":
        forged = _reseal_request_hash(first, user_id=12)
    else:
        forged = _reseal_request_hash(first, intent_payload_hash="f" * 64)

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (OrderReservationFillChainEntry(1, forged), OrderReservationFillChainEntry(2, second)),
        )

    assert raised.value.code == "FILL_CHAIN_ECONOMICS_PARENT_MISMATCH"


def test_resealed_fill_time_before_reservation_is_rejected_for_history() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    predating = _reseal_request_hash(first, fill_occurred_at=AS_OF - timedelta(seconds=1))

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (
                OrderReservationFillChainEntry(1, predating),
                OrderReservationFillChainEntry(2, second),
            ),
        )

    assert raised.value.code == "FILL_CHAIN_ECONOMICS_PARENT_MISMATCH"


def test_impossible_resealed_gross_is_rejected_by_single_fill_economics() -> None:
    intent, policy, _, _, _, first, _ = _two_fills()
    with pytest.raises(OrderReservationError) as raised:
        replace(first, gross_amount=first.gross_amount + Decimal("0.01"))

    assert raised.value.code == "FILL_RESULT_GROSS_MISMATCH"


def test_parent_missing_a_persisted_prefix_cannot_be_assumed_to_have_zero_fills() -> None:
    intent, policy, _, after_first, _, _, _ = _two_fills()

    with pytest.raises(OrderReservationError) as raised:
        _chain(intent, policy, after_first, ())

    assert raised.value.code == "FILL_CHAIN_PARENT_QUANTITY_MISMATCH"


def test_wrong_frozen_fee_policy_cannot_validate_a_stored_chain() -> None:
    intent, policy, _, _, completed, first, second = _two_fills()
    changed_policy = _fee_policy(min_commission=Decimal("6"))

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            changed_policy,
            completed,
            (OrderReservationFillChainEntry(1, first), OrderReservationFillChainEntry(2, second)),
        )

    assert raised.value.code == "FILL_CHAIN_RESERVATION_POLICY_MISMATCH"


def test_partial_close_and_later_cancel_keep_valid_historical_prefixes() -> None:
    intent, policy, initial, after_first, after_second, first, second = _two_fills(
        quantity=Decimal("100.000000"),
        first_quantity=Decimal("25.000000"),
        second_quantity=Decimal("25.000000"),
        close_second=True,
    )
    assert after_second.status.value == "cancelled"
    final = _chain(
        intent,
        policy,
        after_second,
        (OrderReservationFillChainEntry(1, first), OrderReservationFillChainEntry(2, second)),
    )
    assert final.cumulative_quantity == Decimal("50.000000")
    assert first.cumulative_state != final

    intent2, policy2, _, after_first2, active_parent2, first2, second2 = _two_fills(
        quantity=Decimal("100.000000"),
        first_quantity=Decimal("25.000000"),
        second_quantity=Decimal("25.000000"),
    )
    assert active_parent2.status.value == "active"
    cancelled_parent = active_parent2.release_remaining()
    replayed_history = _chain(
        intent2,
        policy2,
        cancelled_parent,
        (OrderReservationFillChainEntry(1, first2), OrderReservationFillChainEntry(2, second2)),
    )
    assert replayed_history.cumulative_quantity == Decimal("50.000000")
    assert first2.cumulative_state != replayed_history
    assert after_first2.filled_quantity == Decimal("25.000000")
    assert initial.filled_quantity == ZERO_SHARES
    assert after_first.filled_quantity == Decimal("25.000000")


def test_sell_chain_uses_the_same_frozen_fee_v2_prefix_rules() -> None:
    intent, policy, _, _, completed, first, second = _two_fills(side=SimulatedTradeSide.SELL)

    result = _chain(
        intent,
        policy,
        completed,
        (OrderReservationFillChainEntry(1, first), OrderReservationFillChainEntry(2, second)),
    )

    assert result.cumulative_quantity == Decimal("100.000000")
    assert result.cumulative_gross == Decimal("1000.00")
    assert result.cumulative_fees == policy.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=Decimal("1000.00"),
        as_of=completed.reserved_at,
    )


def test_chain_sequence_rejects_bool_even_though_bool_is_an_int_subclass() -> None:
    _, _, _, _, _, first, _ = _two_fills()

    with pytest.raises(OrderReservationError) as raised:
        OrderReservationFillChainEntry(True, first)

    assert raised.value.code == "FILL_CHAIN_SEQUENCE_INVALID"


def test_empty_cancelled_parent_has_only_the_explicit_zero_fill_prefix() -> None:
    intent = _intent()
    policy = _fee_policy()
    cancelled = _reservation(intent, fee_policy=policy).release_remaining()

    assert _chain(intent, policy, cancelled, ()) == _initial_accrual()


def test_close_order_flag_is_allowed_only_on_the_final_entry() -> None:
    intent, policy, initial, _, completed, first, second = _two_fills()
    close_first = _prepare(
        intent=intent,
        reservation=initial,
        fee_policy=policy,
        event_id="chain-close-too-early",
        quantity=Decimal("50.000000"),
        price=Decimal("10.0000"),
        close_order=True,
    )

    with pytest.raises(OrderReservationError) as raised:
        _chain(
            intent,
            policy,
            completed,
            (
                OrderReservationFillChainEntry(1, close_first),
                OrderReservationFillChainEntry(2, second),
            ),
        )

    assert raised.value.code == "FILL_CHAIN_CLOSE_NOT_FINAL"
