"""Project retained match decisions with exact, currently visible fill receipts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_history import OrderHistoryDecision
from apps.simulated_trading.domain.order_reservation import OrderReservation
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import _decode_row
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)


class DjangoOrderDecisionHistoryReader:
    """Verify one immutable decision and derive only its public posting status."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the database alias used for exact receipt lookup."""

        if type(using) is not str or not using:
            raise SimulatedTradeExecutionInputError("订单决定历史数据库别名无效")
        self._using = using

    def read_decision(
        self,
        *,
        decision_row: LocalDailyMatchModel,
        reservation_row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        account_id: int,
        user_id: int,
        membership_cutoff: datetime,
        read_at: datetime,
    ) -> OrderHistoryDecision:
        """Decode one decision and verify receipts visible by this read clock.

        The caller must hold the current owner's account, active-user, and
        reservation locks in the same transaction for the complete page read.
        """

        if type(decision_row) is not LocalDailyMatchModel:
            raise _decision_invalid()
        if type(reservation_row) is not SimulatedOrderReservationModel:
            raise _decision_invalid()
        if type(decision_row.pk) is not int or type(reservation_row.pk) is not int:
            raise _decision_invalid()
        if type(reservation) is not OrderReservation:
            raise _decision_invalid()
        try:
            cutoff = _require_aware(membership_cutoff, "membership_cutoff")
            current = _require_aware(read_at, "read_at")
            recorded_at = _require_aware(decision_row.recorded_at, "decision.recorded_at")
            if cutoff > current or recorded_at > cutoff or recorded_at > current:
                raise ValueError("decision clock exceeds its read membership")
            if (
                decision_row.account_id != account_id
                or decision_row.reservation_id != reservation_row.pk
                or reservation_row.account_id != account_id
                or reservation_row.owner_user_id != user_id
            ):
                raise ValueError("decision does not belong to the requested order scope")

            decision = _decode_row(decision_row, replayed=False)
            if (
                decision.command.account_id != account_id
                or decision.command.user_id != user_id
                or decision.command.order_idempotency_key != reservation.identity.idempotency_key
                or decision.command.session_date != decision_row.session_date
            ):
                raise ValueError("decoded decision differs from its current reservation")

            outcome = decision.result.outcome.value
            event = decision.event
            receipt_rows = self._matching_receipts(
                account_id=account_id,
                source_namespace=decision_row.source_namespace,
                source_event_id=decision_row.event_id,
            )
            if len(receipt_rows) > 1:
                raise _receipt_invalid()
            if outcome == LocalDailyMatchModel.OUTCOME_NO_MATCH:
                quantity = decision.result.matched_quantity
                if type(quantity) is not Decimal or event is not None or receipt_rows:
                    raise _receipt_invalid()
                return OrderHistoryDecision(
                    decision_id=decision_row.pk,
                    order_id=reservation_row.pk,
                    session_date=decision_row.session_date,
                    outcome="no_match",
                    matched_quantity=quantity,
                    matched_price=None,
                    recorded_at=recorded_at,
                    occurred_at=None,
                    posting_state="not_applicable",
                    receipt_id=None,
                    trade_id=None,
                )
            if outcome != LocalDailyMatchModel.OUTCOME_MATCHED or event is None:
                raise ValueError("stored decision outcome or event is invalid")
            quantity = decision.result.matched_quantity
            price = decision.result.matched_price
            if type(quantity) is not Decimal or type(price) is not Decimal:
                raise ValueError("stored matched result is missing exact financial values")

            if not receipt_rows:
                return OrderHistoryDecision(
                    decision_id=decision_row.pk,
                    order_id=reservation_row.pk,
                    session_date=decision_row.session_date,
                    outcome="matched",
                    matched_quantity=quantity,
                    matched_price=price,
                    recorded_at=recorded_at,
                    occurred_at=event.occurred_at,
                    posting_state="unconfirmed",
                    receipt_id=None,
                    trade_id=None,
                )

            receipt_row = receipt_rows[0]
            receipt_created_at = _require_aware(receipt_row.created_at, "receipt.created_at")
            if receipt_created_at > current or receipt_row.reservation_id != reservation_row.pk:
                raise _receipt_invalid()
            verified = read_order_reservation_fill_row(
                reservation_row=reservation_row,
                receipt_row=receipt_row,
                trade_row=receipt_row.trade,
            )
            if (
                verified.reservation_id != reservation_row.pk
                or verified.receipt_id != receipt_row.pk
                or verified.trade_id != receipt_row.trade_id
                or verified.event != event
            ):
                raise _receipt_invalid()
            return OrderHistoryDecision(
                decision_id=decision_row.pk,
                order_id=reservation_row.pk,
                session_date=decision_row.session_date,
                outcome="matched",
                matched_quantity=quantity,
                matched_price=price,
                recorded_at=recorded_at,
                occurred_at=event.occurred_at,
                posting_state="applied",
                receipt_id=verified.receipt_id,
                trade_id=verified.trade_id,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except (
            ArithmeticError,
            AttributeError,
            KeyError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _decision_invalid() from error

    def _matching_receipts(
        self,
        *,
        account_id: int,
        source_namespace: str,
        source_event_id: str,
    ) -> list[SimulatedOrderFillReceiptModel]:
        """Find a source locator account-wide so a wrong-order receipt cannot disappear."""

        return list(
            SimulatedOrderFillReceiptModel._base_manager.using(self._using)
            .select_related("trade")
            .filter(
                reservation__account_id=account_id,
                source_namespace=source_namespace,
                source_event_id=source_event_id,
            )
            .order_by("pk")[:2]
        )


def _require_aware(value: object, field_name: str) -> datetime:
    """Require one exact timezone-aware timestamp read from stored rows or request."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"{field_name} has no UTC offset")
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must have a valid UTC offset") from error
    return value


def _decision_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block when a persisted decision cannot be verified."""

    return SimulatedTradeExecutionBlocked(
        "已保存的撮合决定无法精确核对",
        code="ORDER_HISTORY_DECISION_INVALID",
    )


def _receipt_invalid() -> SimulatedTradeExecutionBlocked:
    """Return a stable block for a missing, duplicated, future, or misbound receipt."""

    return SimulatedTradeExecutionBlocked(
        "撮合决定对应的成交回执无法精确核对",
        code="ORDER_HISTORY_RECEIPT_INVALID",
    )


__all__ = ("DjangoOrderDecisionHistoryReader",)
