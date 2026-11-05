"""Owner-scoped read of plan bindings, immutable fill receipts, and actual fees."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.transition_plan_execution_progress import (
    PlanExecutionHistoryRead,
)
from apps.simulated_trading.domain.order_reservation import OrderReservation
from apps.simulated_trading.domain.order_reservation_fill import OrderReservationFillAccrual
from apps.simulated_trading.domain.transition_plan_execution import (
    PlanExecutionReservation,
    VerifiedPlanFill,
    derive_plan_order_idempotency_key,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    decode_order_reservation_intent,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.transition_plan_execution_snapshot import (
    decode_plan_execution_binding,
)


class DjangoTransitionPlanExecutionHistoryRepository:
    """Read all plan-bound reservation attempts without altering ledger state."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Use the same configured database as simulated account reservations."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using

    def read_plan_history(
        self, *, account_id: int, owner_user_id: int, as_of: datetime
    ) -> PlanExecutionHistoryRead:
        """Return facts visible at ``as_of`` and fail closed for malformed history."""

        self._validate_request(account_id=account_id, owner_user_id=owner_user_id, as_of=as_of)
        started_at = timezone.now()
        reservations: list[PlanExecutionReservation] = []
        reasons: list[str] = []
        complete = True
        if as_of > started_at:
            complete = False
            reasons.append("TRANSITION_PLAN_HISTORY_FUTURE_CUTOFF")
        try:
            with transaction.atomic(using=self._using):
                account = (
                    SimulatedAccountModel._base_manager.using(self._using)
                    .select_for_update()
                    .filter(pk=account_id, user_id=owner_user_id, is_active=True)
                    .first()
                )
                if account is None:
                    return PlanExecutionHistoryRead(
                        account_id=account_id,
                        owner_user_id=owner_user_id,
                        read_at=timezone.now(),
                        reservations=(),
                        complete=False,
                        reason_codes=("TRANSITION_PLAN_ACCOUNT_SCOPE_UNAVAILABLE",),
                    )
                rows = list(
                    SimulatedOrderReservationModel._base_manager.using(self._using)
                    .select_for_update()
                    .filter(
                        account_id=account_id,
                        owner_user_id=owner_user_id,
                        created_at__lte=as_of,
                    )
                    .order_by("pk")
                )
                for row in rows:
                    try:
                        item = self._decode_attempt(row=row, as_of=as_of)
                    except (
                        ArithmeticError,
                        AttributeError,
                        SimulatedTradeExecutionBlocked,
                        TypeError,
                        ValueError,
                    ):
                        complete = False
                        reasons.append("TRANSITION_PLAN_EXECUTION_HISTORY_INVALID")
                        continue
                    if item is None:
                        continue
                    reservations.append(item)
                    if row.updated_at > as_of:
                        complete = False
                        reasons.append("TRANSITION_PLAN_RESERVATION_CHANGED_AFTER_CUTOFF")
                    if item.fills is None:
                        complete = False
                        reasons.append("TRANSITION_PLAN_FILL_HISTORY_INCOMPLETE")
        except (
            ArithmeticError,
            AttributeError,
            SimulatedTradeExecutionBlocked,
            TypeError,
            ValueError,
        ):
            complete = False
            reasons.append("TRANSITION_PLAN_EXECUTION_HISTORY_UNAVAILABLE")
        read_at = timezone.now()
        if as_of > read_at:
            complete = False
            reasons.append("TRANSITION_PLAN_HISTORY_FUTURE_CUTOFF")
        return PlanExecutionHistoryRead(
            account_id=account_id,
            owner_user_id=owner_user_id,
            read_at=read_at,
            reservations=tuple(reservations),
            complete=complete,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def _decode_attempt(
        self, *, row: SimulatedOrderReservationModel, as_of: datetime
    ) -> PlanExecutionReservation | None:
        """Validate one reservation, optional Portfolio binding, and complete fill chain."""

        if type(row) is not SimulatedOrderReservationModel or type(row.pk) is not int:
            raise ValueError("reservation row identity is invalid")
        reservation: OrderReservation = decode_order_reservation(row)
        snapshot = validated_plan_snapshot(row)
        if "transition_plan_binding" not in snapshot:
            return None
        binding, recorded_at = decode_plan_execution_binding(snapshot["transition_plan_binding"])
        intent = decode_order_reservation_intent(row)
        if (
            binding.account_id != row.account_id
            or binding.owner_user_id != row.owner_user_id
            or binding.asset_code != row.asset_code
            or binding.security_id != row.security_id
            or binding.asset_type != row.asset_type
            or binding.side != row.side
            or binding.order_ordinal < 0
            or row.quantity > binding.approved_quantity
            or row.idempotency_key != derive_plan_order_idempotency_key(binding.content_hash)
            or intent.idempotency_key != row.idempotency_key
            or recorded_at > as_of
        ):
            raise ValueError("reservation fields differ from its exact plan binding")
        if (
            binding.approved_limit_price is not None
            and reservation.limit_price != binding.approved_limit_price
        ):
            raise ValueError("reservation price differs from the explicit plan limit")
        fills = self._read_verified_fills(
            row=row,
            reservation=reservation,
            as_of=as_of,
        )
        return PlanExecutionReservation(
            reservation_id=row.pk,
            binding=binding,
            revision_recorded_at=recorded_at,
            intent=intent,
            reservation=reservation,
            fills=fills,
        )

    def _read_verified_fills(
        self,
        *,
        row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        as_of: datetime,
    ) -> tuple[VerifiedPlanFill, ...] | None:
        """Verify contiguous receipts, fee components, and the final reserved quantity."""

        rows = list(
            SimulatedOrderFillReceiptModel._base_manager.using(self._using)
            .select_related("trade")
            .filter(reservation_id=row.pk, created_at__lte=as_of)
            .order_by("fill_sequence", "pk")
        )
        verified: list[VerifiedPlanFill] = []
        previous_accrual: OrderReservationFillAccrual | None = None
        total_quantity = Decimal("0")
        for expected_sequence, receipt in enumerate(rows, start=1):
            decoded = read_order_reservation_fill_row(
                reservation_row=row,
                receipt_row=receipt,
                trade_row=receipt.trade,
            )
            economics = decoded.economics
            if decoded.fill_sequence != expected_sequence:
                return None
            if previous_accrual is None:
                if economics.prior.fill_count != 0:
                    return None
            elif economics.prior != previous_accrual:
                return None
            previous_accrual = economics.cumulative_state
            with localcontext() as context:
                context.prec = 80
                total_quantity += economics.quantity
            verified.append(
                VerifiedPlanFill(
                    receipt_id=decoded.receipt_id,
                    trade_id=decoded.trade_id,
                    quantity=economics.quantity,
                    gross_amount=economics.gross_amount,
                    actual_fee=economics.incremental_fees.total_fee,
                )
            )
        if total_quantity != reservation.filled_quantity:
            return None
        if previous_accrual is not None and previous_accrual.cumulative_quantity != total_quantity:
            return None
        return tuple(verified)

    @staticmethod
    def _validate_request(*, account_id: int, owner_user_id: int, as_of: datetime) -> None:
        """Reject any scope or time that cannot safely bound a read-only history query."""

        if type(account_id) is not int or account_id <= 0:
            raise ValueError("account_id must be positive")
        if type(owner_user_id) is not int or owner_user_id <= 0:
            raise ValueError("owner_user_id must be positive")
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone aware")


__all__: tuple[str, ...] = ("DjangoTransitionPlanExecutionHistoryRepository",)
