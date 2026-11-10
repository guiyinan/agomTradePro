"""Revalidate Portfolio bindings against the existing reservation ledger history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanOrderExecutionBinding,
    TransitionPlanRevision,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.transition_plan_execution import (
    TransitionPlanLockedActionGuard,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.infrastructure.models import SimulatedOrderReservationModel
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_snapshot import (
    decode_plan_execution_binding,
    validate_binding_matches_intent,
)


def require_stored_transition_plan_binding(
    *,
    snapshot: dict[str, object],
    expected_binding: TransitionPlanOrderExecutionBinding | None,
    expected_recorded_at: datetime | None,
) -> None:
    """Require idempotent reads to preserve the same optional plan proof exactly."""

    if "transition_plan_binding" not in snapshot:
        if expected_binding is not None or expected_recorded_at is not None:
            raise SimulatedTradeIdempotencyConflict(
                "order key is not bound to the exact requested plan action"
            )
        return
    stored_binding, stored_recorded_at = decode_plan_execution_binding(
        snapshot["transition_plan_binding"]
    )
    if (
        expected_binding is None
        or expected_recorded_at is None
        or stored_binding.to_payload() != expected_binding.to_payload()
        or stored_recorded_at.isoformat() != expected_recorded_at.isoformat()
    ):
        raise SimulatedTradeIdempotencyConflict(
            "order key is bound to a different transition-plan action"
        )


def validate_transition_plan_intent_binding(
    *,
    binding: TransitionPlanOrderExecutionBinding,
    intent: SimulatedTradeIntent,
    owner_user_id: int,
    recorded_at: datetime,
) -> None:
    """Bind one exact plan line to the current owner intent before persistence."""

    if type(binding) is not TransitionPlanOrderExecutionBinding:
        raise SimulatedTradeExecutionBlocked(
            "plan binding must use Portfolio's exact typed value",
            code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
        )
    try:
        binding.__post_init__()
        intent.__post_init__()
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "plan action binding failed exact validation",
            code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
        ) from error
    if type(recorded_at) is not datetime or recorded_at.tzinfo is None:
        raise SimulatedTradeExecutionBlocked(
            "plan revision clock is missing",
            code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
        )
    if recorded_at.utcoffset() is None or recorded_at >= binding.plan_expires_at:
        raise SimulatedTradeExecutionBlocked(
            "plan revision clock is outside its validity window",
            code="TRANSITION_PLAN_EXECUTION_BINDING_INVALID",
        )
    try:
        validate_binding_matches_intent(binding=binding, intent=intent)
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "plan action differs from the exact approved order binding",
            code="TRANSITION_PLAN_ORDER_BINDING_MISMATCH",
        ) from error
    if binding.owner_user_id != owner_user_id:
        raise SimulatedTradeExecutionBlocked(
            "plan action belongs to another owner",
            code="TRANSITION_PLAN_OWNER_SCOPE_MISMATCH",
        )


def validate_locked_transition_plan_binding(
    *,
    revision: TransitionPlanRevision,
    binding: TransitionPlanOrderExecutionBinding,
    intent: SimulatedTradeIntent,
    owner_user_id: int,
    as_of: datetime,
    recorded_at: datetime,
) -> None:
    """Recheck the Portfolio guard result and exact line inside the account lock."""

    if type(revision) is not TransitionPlanRevision:
        raise SimulatedTradeExecutionBlocked(
            "locked plan guard returned no exact revision",
            code="TRANSITION_PLAN_GUARD_UNAVAILABLE",
        )
    try:
        revision.__post_init__()
        validate_transition_plan_intent_binding(
            binding=binding,
            intent=intent,
            owner_user_id=owner_user_id,
            recorded_at=recorded_at,
        )
        identity = revision.identity
        if (
            identity.plan_id != binding.plan_id
            or identity.family_id != binding.family_id
            or identity.root_plan_id != binding.root_plan_id
            or identity.version != binding.plan_version
            or identity.revision_hash != binding.revision_hash
            or identity.account_id != binding.account_id
            or identity.owner_user_id != owner_user_id
            or identity.recorded_at.isoformat() != recorded_at.isoformat()
            or identity.valid_until != binding.plan_expires_at
            or as_of < identity.recorded_at
            or as_of >= identity.valid_until
            or revision.plan.status in {"CANCELLED", "REJECTED"}
            or binding.order_ordinal >= len(revision.orders)
        ):
            raise ValueError("locked revision identity differs from the exact action")
        order = revision.orders[binding.order_ordinal]
        expected = order.to_execution_binding(
            identity,
            owner_user_id=owner_user_id,
            action_attempt_key=binding.action_attempt_key,
        )
        if expected.to_payload() != binding.to_payload():
            raise ValueError("locked order content differs from its exact action binding")
    except (ArithmeticError, AttributeError, IndexError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "locked plan, owner or order binding changed",
            code="TRANSITION_PLAN_ORDER_BINDING_MISMATCH",
        ) from error


def require_final_transition_plan_lease(
    *,
    binding: TransitionPlanOrderExecutionBinding | None,
    guard: TransitionPlanLockedActionGuard | None,
    recorded_at: datetime | None,
    intent: SimulatedTradeIntent,
    initial_now: datetime,
    read_clock: Callable[[], datetime],
) -> None:
    """Recheck the plan lease after inserting a hold, before its transaction commits."""

    if binding is None:
        return
    if guard is None or recorded_at is None:
        raise SimulatedTradeExecutionBlocked(
            "plan execution guard disappeared before hold persistence",
            code="TRANSITION_PLAN_GUARD_UNAVAILABLE",
        )
    final_now = read_clock()
    if final_now < initial_now:
        raise SimulatedTradeExecutionBlocked(
            "reservation clock moved backwards before hold persistence",
            code="ORDER_RESERVATION_PLAN_STALE",
        )
    final_revision = guard.validate_locked_action(
        binding=binding,
        account_id=intent.account_id,
        owner_user_id=intent.user_id,
        as_of=final_now,
    )
    validate_locked_transition_plan_binding(
        revision=final_revision,
        binding=binding,
        intent=intent,
        owner_user_id=intent.user_id,
        as_of=final_now,
        recorded_at=recorded_at,
    )


def require_no_conflicting_plan_reservation_history(
    *,
    using: str,
    account_id: int,
    owner_user_id: int,
    binding: TransitionPlanOrderExecutionBinding,
    current_idempotency_key: str,
) -> None:
    """Prevent a duplicate attempt or concurrent old-family order for the same security."""

    rows = SimulatedOrderReservationModel._base_manager.using(using).filter(
        account_id=account_id,
        owner_user_id=owner_user_id,
    )
    for row in rows.iterator():
        snapshot = validated_plan_snapshot(row)
        if "transition_plan_binding" not in snapshot:
            continue
        prior, _ = decode_plan_execution_binding(snapshot["transition_plan_binding"])
        if (
            prior.account_id != account_id
            or prior.owner_user_id != owner_user_id
            or row.idempotency_key != decode_order_reservation(row).identity.idempotency_key
        ):
            raise SimulatedTradeExecutionBlocked(
                "stored plan-bound reservation scope is inconsistent",
                code="TRANSITION_PLAN_EXECUTION_HISTORY_INVALID",
            )
        if prior.plan_id == binding.plan_id and prior.order_ordinal == binding.order_ordinal:
            if row.idempotency_key != current_idempotency_key:
                raise SimulatedTradeExecutionBlocked(
                    "this plan order already has a previous attempt; review a successor",
                    code="TRANSITION_PLAN_SUCCESSOR_REQUIRED",
                )
            continue
        same_family_security = (
            prior.family_id == binding.family_id
            and prior.root_plan_id == binding.root_plan_id
            and prior.asset_code == binding.asset_code
            and prior.security_id == binding.security_id
        )
        if same_family_security and row.status == SimulatedOrderReservationModel.STATUS_ACTIVE:
            raise SimulatedTradeExecutionBlocked(
                "an older plan revision still has an active hold for this security",
                code="TRANSITION_PLAN_FAMILY_ORDER_IN_FLIGHT",
            )
