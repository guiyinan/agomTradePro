"""Pure reconciliation tests for exact simulated transition-plan execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal

import pytest

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderBinding,
    TransitionPlanOrderExecutionBinding,
    TransitionPlanRevisionIdentity,
)
from apps.simulated_trading.domain.execution_settlement_primitives import SimulatedTradeSide
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationIdentity,
    OrderReservationStatus,
)
from apps.simulated_trading.domain.transition_plan_execution import (
    PlanExecutionReservation,
    VerifiedPlanFill,
    derive_plan_order_idempotency_key,
    reconcile_plan_order_execution,
)

AS_OF = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
_HASH = sha256(b"plan execution fixture").hexdigest()


def _identity(
    *,
    plan_id: str = "plan-r1",
    root_plan_id: str = "plan-r1",
    version: int = 1,
    revision_hash: str = _HASH,
    recorded_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> TransitionPlanRevisionIdentity:
    """Build a typed exact synthetic revision identity, not an execution grant."""

    parent = version > 1
    return TransitionPlanRevisionIdentity(
        plan_id=plan_id,
        family_id="family-1",
        root_plan_id=root_plan_id,
        version=version,
        parent_plan_id="plan-r1" if parent else None,
        parent_version=version - 1 if parent else None,
        parent_revision_hash=sha256(b"parent-r1").hexdigest() if parent else None,
        account_id=41,
        owner_user_id=23,
        transition_plan_hash=sha256(b"transition-plan").hexdigest(),
        revision_hash=revision_hash,
        recorded_at=recorded_at or AS_OF - timedelta(minutes=10),
        valid_until=valid_until or AS_OF + timedelta(minutes=5),
    )


def _order(
    identity: TransitionPlanRevisionIdentity,
    *,
    side: Literal["buy", "sell"] = "sell",
    ordinal: int = 0,
    reasons: tuple[str, ...] = (),
    quantity: int = 100,
) -> TransitionPlanOrderBinding:
    """Build one exact Portfolio revision order reference."""

    return TransitionPlanOrderBinding(
        ordinal=ordinal,
        order_content_hash=sha256(f"order-{ordinal}".encode()).hexdigest(),
        plan_order_binding_id=sha256(
            f"{identity.revision_hash}:{ordinal}:{side}".encode()
        ).hexdigest(),
        asset_code="600036.SH",
        security_id="SSE:600036",
        asset_type="equity",
        classification_content_hash=sha256(b"synthetic-classification").hexdigest(),
        side=side,
        requested_quantity=quantity,
        approved_quantity=quantity,
        unapproved_quantity=0,
        reference_price=Decimal("10"),
        estimated_fee=Decimal("1.00"),
        approved_limit_price=None,
        quantity_unit="share",
        money_unit="CNY",
        status="approved",
        reason_codes=reasons,
    )


def _binding(
    identity: TransitionPlanRevisionIdentity,
    order: TransitionPlanOrderBinding,
    *,
    attempt: str = "attempt-1",
) -> TransitionPlanOrderExecutionBinding:
    """Create a real Portfolio-owned action binding for one prior attempt."""

    return order.to_execution_binding(
        identity, owner_user_id=identity.owner_user_id, action_attempt_key=attempt
    )


def _reservation(
    identity: TransitionPlanRevisionIdentity,
    order: TransitionPlanOrderBinding,
    binding: TransitionPlanOrderExecutionBinding,
    *,
    reservation_id: int = 1,
    quantity: Decimal = Decimal("100"),
    filled: Decimal = Decimal("30"),
    status: OrderReservationStatus = OrderReservationStatus.ACTIVE,
) -> PlanExecutionReservation:
    """Build existing reservation facts and receipt-backed fills for one attempt."""

    side = SimulatedTradeSide(binding.side)
    notional = quantity * Decimal("10")
    if side is SimulatedTradeSide.BUY:
        fee_budget = Decimal("1.00")
        cash_reserved = notional + fee_budget
        shares_reserved = Decimal("0")
        cash_consumed = filled * Decimal("10") + Decimal("0.30") if filled else Decimal("0")
        shares_consumed = Decimal("0")
        cash_released = Decimal("0")
        shares_released = Decimal("0")
    else:
        fee_budget = None
        cash_reserved = Decimal("0")
        shares_reserved = quantity
        cash_consumed = Decimal("0")
        shares_consumed = filled
        cash_released = Decimal("0")
        shares_released = (
            quantity - filled if status is OrderReservationStatus.CANCELLED else Decimal("0")
        )
    if status is OrderReservationStatus.COMPLETED:
        filled = quantity
        shares_consumed = quantity if side is SimulatedTradeSide.SELL else Decimal("0")
        cash_consumed = (
            notional + Decimal("1.00") if side is SimulatedTradeSide.BUY else Decimal("0")
        )
        shares_released = Decimal("0")
        cash_released = Decimal("0")
    if status is OrderReservationStatus.CANCELLED and side is SimulatedTradeSide.BUY:
        cash_released = cash_reserved - cash_consumed
    record = OrderReservation(
        identity=OrderReservationIdentity(
            account_id=binding.account_id,
            security_id=binding.security_id,
            idempotency_key=derive_plan_order_idempotency_key(binding.content_hash),
            request_payload_hash=_HASH,
        ),
        side=side,
        quantity=quantity,
        limit_price=Decimal("10"),
        notional=notional,
        fee_estimate=Decimal("1.00"),
        fee_budget=fee_budget,
        cash_reserved=cash_reserved,
        shares_reserved=shares_reserved,
        reserved_at=AS_OF - timedelta(minutes=2),
        status=status,
        filled_quantity=filled,
        cash_consumed=cash_consumed,
        shares_consumed=shares_consumed,
        cash_released=cash_released,
        shares_released=shares_released,
    )
    fill_quantities = (
        (Decimal("30"), Decimal("70"))
        if filled == quantity
        else (Decimal("30"),) if filled == Decimal("30") else ()
    )
    fills = tuple(
        VerifiedPlanFill(
            receipt_id=100 + index,
            trade_id=200 + index,
            quantity=fill_quantity,
            gross_amount=fill_quantity * Decimal("10"),
            actual_fee=Decimal("0.30") if index == 0 else Decimal("0.70"),
        )
        for index, fill_quantity in enumerate(fill_quantities)
    )
    return PlanExecutionReservation(
        reservation_id=reservation_id,
        binding=binding,
        revision_recorded_at=identity.recorded_at,
        intent=SimulatedTradeIntent(
            account_id=binding.account_id,
            user_id=binding.owner_user_id,
            idempotency_key=derive_plan_order_idempotency_key(binding.content_hash),
            side=side,
            security_id=binding.security_id,
            asset_code=binding.asset_code,
            asset_name=binding.asset_code,
            asset_type=binding.asset_type,
            market="CN",
            board="MAIN",
            quantity=quantity,
            price=Decimal("10"),
            reason="synthetic plan fixture",
            signal_id=None,
        ),
        reservation=record,
        fills=fills,
    )


def _progress(
    *,
    identity: TransitionPlanRevisionIdentity | None = None,
    order: TransitionPlanOrderBinding | None = None,
    rows: tuple[PlanExecutionReservation, ...] = (),
    related: tuple[PlanExecutionReservation, ...] = (),
    history_complete: bool = True,
    revision_active: bool = True,
    predecessor_sells_settled: bool | None = True,
    expected_action_attempt_key: str | None = None,
):
    chosen_identity = identity or _identity()
    chosen_order = order or _order(chosen_identity)
    return reconcile_plan_order_execution(
        revision_identity=chosen_identity,
        order=chosen_order,
        reservations=rows,
        related_family_reservations=related,
        history_complete=history_complete,
        revision_active=revision_active,
        as_of=AS_OF,
        predecessor_sells_settled=predecessor_sells_settled,
        expected_action_attempt_key=expected_action_attempt_key,
    )


def test_partial_fill_and_active_reservation_remain_in_flight() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    reservation = _reservation(identity, order, binding)

    progress = _progress(identity=identity, order=order, rows=(reservation,))

    assert progress.filled_quantity == Decimal("30")
    assert progress.in_flight_quantity == Decimal("70")
    assert progress.remaining_quantity == Decimal("70")
    assert progress.unreserved_remaining_quantity == Decimal("0")
    assert progress.active_sell_quantity == Decimal("70")
    assert progress.attempts[0].action_attempt_key == "attempt-1"
    assert progress.active_order_ids == (1,)
    assert progress.can_cancel is True
    assert progress.can_preview is False
    assert progress.outcome == "in_flight"


def test_idempotent_attempt_readback_requires_its_real_attempt_key() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    row = _reservation(identity, order, binding)

    no_selected_attempt = _progress(identity=identity, order=order, rows=(row,))
    replay = _progress(
        identity=identity,
        order=order,
        rows=(row,),
        expected_action_attempt_key="attempt-1",
    )

    assert no_selected_attempt.replay_order_id is None
    assert no_selected_attempt.action_attempt_keys == ("attempt-1",)
    assert replay.replay_order_id == row.reservation_id
    assert replay.can_recover is True
    assert replay.can_preview is False


def test_cancelled_partial_fill_releases_only_the_unfilled_quantity() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    cancelled = _reservation(
        identity, order, binding, status=OrderReservationStatus.CANCELLED, filled=Decimal("30")
    )

    progress = _progress(identity=identity, order=order, rows=(cancelled,))

    assert progress.filled_quantity == Decimal("30")
    assert progress.in_flight_quantity == Decimal("0")
    assert progress.released_quantity == Decimal("70")
    assert progress.remaining_quantity == Decimal("70")
    assert progress.unreserved_remaining_quantity == Decimal("70")
    assert progress.cancelled_order_ids == (1,)
    assert progress.requires_successor is True
    assert progress.can_preview is False
    assert progress.outcome == "successor_required"


def test_completed_sell_never_projects_future_proceeds_as_cash() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    completed = _reservation(
        identity, order, binding, status=OrderReservationStatus.COMPLETED, filled=Decimal("100")
    )

    progress = _progress(identity=identity, order=order, rows=(completed,))

    assert progress.filled_quantity == Decimal("100")
    assert progress.in_flight_quantity == Decimal("0")
    assert progress.remaining_quantity == Decimal("0")
    assert progress.unreserved_remaining_quantity == Decimal("0")
    assert progress.outcome == "complete"
    assert progress.can_preview is False
    assert progress.actual_fees_paid == Decimal("1.00")
    assert progress.fees_complete is True


def test_missing_fill_history_preserves_execution_and_fee_totals_as_unknown() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    row = _reservation(identity, order, binding)
    unknown = PlanExecutionReservation(
        reservation_id=row.reservation_id,
        binding=row.binding,
        revision_recorded_at=row.revision_recorded_at,
        intent=row.intent,
        reservation=row.reservation,
        fills=None,
    )

    progress = _progress(identity=identity, order=order, rows=(unknown,), history_complete=False)

    assert progress.filled_quantity is None
    assert progress.in_flight_quantity is None
    assert progress.released_quantity is None
    assert progress.remaining_quantity is None
    assert progress.actual_fees_paid is None
    assert progress.can_preview is False
    assert "TRANSITION_PLAN_EXECUTION_HISTORY_INCOMPLETE" in progress.reason_codes


def test_unknown_actual_fee_is_not_replaced_by_the_plan_estimate() -> None:
    identity = _identity()
    order = _order(identity)
    binding = _binding(identity, order)
    row = _reservation(identity, order, binding)
    unknown_fee = PlanExecutionReservation(
        reservation_id=row.reservation_id,
        binding=binding,
        revision_recorded_at=identity.recorded_at,
        intent=row.intent,
        reservation=row.reservation,
        fills=(
            VerifiedPlanFill(
                receipt_id=101,
                trade_id=201,
                quantity=Decimal("30"),
                gross_amount=Decimal("300"),
                actual_fee=None,
            ),
        ),
    )

    progress = _progress(identity=identity, order=order, rows=(unknown_fee,))

    assert progress.filled_quantity == Decimal("30")
    assert progress.actual_fees_paid is None
    assert progress.fees_complete is False


def test_active_old_revision_hold_blocks_successor_for_same_asset() -> None:
    old_identity = _identity()
    old_order = _order(old_identity)
    old_binding = _binding(old_identity, old_order, attempt="attempt-old")
    old_row = _reservation(old_identity, old_order, old_binding, reservation_id=7)
    current_identity = _identity(
        plan_id="plan-r2",
        root_plan_id="plan-r1",
        version=2,
        revision_hash=sha256(b"new-revision").hexdigest(),
    )
    current_order = _order(current_identity)

    progress = _progress(
        identity=current_identity,
        order=current_order,
        related=(old_row,),
    )

    assert progress.outcome == "blocked"
    assert progress.can_preview is False
    assert "TRANSITION_PLAN_FAMILY_ORDER_IN_FLIGHT" in progress.reason_codes


def test_explicit_sale_dependency_is_reported_without_inventing_all_sells_gate() -> None:
    identity = _identity()
    buy = _order(
        identity,
        side="buy",
        ordinal=1,
        reasons=("BUY_DEPENDS_ON_SETTLED_SALES",),
    )

    dependency_unknown = _progress(identity=identity, order=buy, predecessor_sells_settled=None)
    dependency_pending = _progress(identity=identity, order=buy, predecessor_sells_settled=False)
    enough_cash_after_partial_sale = _progress(
        identity=identity, order=buy, predecessor_sells_settled=True
    )
    no_dependency = _progress(
        identity=identity,
        order=_order(identity, side="buy", ordinal=2),
        predecessor_sells_settled=None,
    )

    assert dependency_unknown.predecessor_sells_settled is None
    assert dependency_pending.predecessor_sells_settled is False
    assert dependency_pending.can_preview is True
    assert enough_cash_after_partial_sale.predecessor_sells_settled is True
    assert enough_cash_after_partial_sale.can_preview is True
    assert no_dependency.predecessor_sells_settled is None


def test_expired_or_nonhead_revision_cannot_offer_a_preview() -> None:
    expired_identity = _identity(valid_until=AS_OF)
    expired_order = _order(expired_identity)
    expired = _progress(identity=expired_identity, order=expired_order)

    identity = _identity()
    order = _order(identity)
    superseded = _progress(identity=identity, order=order, revision_active=False)

    assert expired.can_preview is False
    assert "TRANSITION_PLAN_EXPIRED" in expired.reason_codes
    assert superseded.can_preview is False
    assert "TRANSITION_PLAN_REVISION_NOT_ACTIVE" in superseded.reason_codes


def test_idempotency_key_uses_the_complete_canonical_binding_hash() -> None:
    hash_a = sha256(b"attempt a").hexdigest()
    hash_b = sha256(b"attempt b").hexdigest()

    key_a = derive_plan_order_idempotency_key(hash_a)
    key_b = derive_plan_order_idempotency_key(hash_b)

    assert key_a.startswith("ash08-")
    assert len(key_a) == 70
    assert key_a != key_b


@pytest.mark.parametrize("bad_hash", ["bad", "A" * 64, "0" * 63 + "g"])
def test_idempotency_key_rejects_noncanonical_binding_hash(bad_hash: str) -> None:
    with pytest.raises(ValueError):
        derive_plan_order_idempotency_key(bad_hash)
