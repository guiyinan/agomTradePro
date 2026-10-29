"""Whitelisted request and response contracts for owner order operations."""

from __future__ import annotations

from typing import TypeAlias

from rest_framework import serializers

from apps.simulated_trading.application.owner_order_operations import (
    OwnerOrderCancelled,
    OwnerOrderFillApplied,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus

JsonObject: TypeAlias = dict[str, object]


class OwnerOrderOperationConfirmationSerializer(serializers.Serializer[JsonObject]):
    """Document the one exact confirmation field accepted by either write route."""

    confirmed = serializers.BooleanField(required=True)


class OwnerOrderFillFeesSerializer(serializers.Serializer[JsonObject]):
    """Serialize the immutable incremental fee breakdown without numeric coercion."""

    commission = serializers.CharField()
    transfer_fee = serializers.CharField()
    stamp_duty = serializers.CharField()
    slippage = serializers.CharField()
    total_fee = serializers.CharField()


class OwnerOrderFillAppliedResponseSerializer(serializers.Serializer[JsonObject]):
    """Describe only identities and economics carried by the immutable fill result."""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1)
    decision_id = serializers.IntegerField(min_value=1)
    trade_id = serializers.IntegerField(min_value=1)
    fill_sequence = serializers.IntegerField(min_value=1)
    asset_code = serializers.CharField()
    side = serializers.ChoiceField(choices=("buy", "sell"))
    quantity = serializers.CharField()
    price = serializers.CharField()
    gross_amount = serializers.CharField()
    incremental_fees = OwnerOrderFillFeesSerializer()
    occurred_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=("applied",))
    replayed = serializers.BooleanField()


class OwnerOrderCancelledResponseSerializer(serializers.Serializer[JsonObject]):
    """Describe the terminal reservation and its cumulative resource release."""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(
        choices=(OrderReservationStatus.CANCELLED.value, OrderReservationStatus.COMPLETED.value)
    )
    released_cash = serializers.CharField()
    released_shares = serializers.CharField()
    remaining_cash = serializers.CharField()
    remaining_shares = serializers.CharField()


class OwnerOrderOperationErrorResponseSerializer(serializers.Serializer[JsonObject]):
    """Document safe public errors without internal exception details."""

    success = serializers.BooleanField()
    code = serializers.CharField()
    message = serializers.CharField()
    effects_indeterminate = serializers.BooleanField(required=False)


def fill_applied_payload(operation: OwnerOrderFillApplied) -> JsonObject:
    """Render the exact persisted fill result without source locators or guessed fields."""

    if type(operation) is not OwnerOrderFillApplied:
        raise TypeError("owner fill result has an invalid type")
    operation.__post_init__()
    result = operation.result
    economics = result.economics
    fees = economics.incremental_fees
    return {
        "success": True,
        "account_id": operation.account_id,
        "order_id": operation.order_id,
        "decision_id": operation.decision_id,
        "trade_id": result.trade_id,
        "fill_sequence": economics.cumulative_state.fill_count,
        "asset_code": economics.asset_code,
        "side": economics.side.value,
        "quantity": str(economics.quantity),
        "price": str(economics.price),
        "gross_amount": str(economics.gross_amount),
        "incremental_fees": {
            "commission": str(fees.commission),
            "transfer_fee": str(fees.transfer_fee),
            "stamp_duty": str(fees.stamp_duty),
            "slippage": str(fees.slippage),
            "total_fee": str(fees.total_fee),
        },
        "occurred_at": economics.fill_occurred_at.isoformat(),
        "status": "applied",
        "replayed": result.replayed,
    }


def order_cancelled_payload(operation: OwnerOrderCancelled) -> JsonObject:
    """Render actual terminal status and cumulative release totals from the reservation."""

    if type(operation) is not OwnerOrderCancelled:
        raise TypeError("owner cancellation result has an invalid type")
    operation.__post_init__()
    reservation = operation.reservation
    return {
        "success": True,
        "account_id": operation.account_id,
        "order_id": operation.order_id,
        "status": reservation.status.value,
        "released_cash": str(reservation.cash_released),
        "released_shares": str(reservation.shares_released),
        "remaining_cash": str(reservation.remaining_cash),
        "remaining_shares": str(reservation.remaining_shares),
    }


__all__ = (
    "OwnerOrderCancelledResponseSerializer",
    "OwnerOrderFillAppliedResponseSerializer",
    "OwnerOrderFillFeesSerializer",
    "OwnerOrderOperationConfirmationSerializer",
    "OwnerOrderOperationErrorResponseSerializer",
    "fill_applied_payload",
    "order_cancelled_payload",
)
