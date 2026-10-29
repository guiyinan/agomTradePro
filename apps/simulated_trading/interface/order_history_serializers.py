"""Explicit HTTP contracts for owner order and retained receipt history."""

from __future__ import annotations

from rest_framework import serializers

_ORDER_STATUS_CHOICES = ("active", "completed", "cancelled")
_SIDE_CHOICES = ("buy", "sell")
_OBSERVATION_BASIS_CHOICES = ("legacy_source_observed", "daily_interval_end")


class OrderHistoryQuerySerializer(serializers.Serializer[dict[str, object]]):
    """Validate bounded list pagination without accepting caller identity fields."""

    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=100)
    cursor = serializers.CharField(required=False, allow_blank=False, max_length=4096)


class OrderHistoryOrderSerializer(serializers.Serializer[dict[str, object]]):
    """Whitelist one public order summary with monetary values as strings."""

    order_id = serializers.IntegerField(min_value=1)
    asset_code = serializers.CharField(max_length=20)
    asset_name = serializers.CharField(max_length=100)
    side = serializers.ChoiceField(choices=_SIDE_CHOICES)
    status = serializers.ChoiceField(choices=_ORDER_STATUS_CHOICES)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, coerce_to_string=True)
    filled_quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        coerce_to_string=True,
    )
    limit_price = serializers.DecimalField(max_digits=10, decimal_places=4, coerce_to_string=True)
    remaining_cash = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        coerce_to_string=True,
    )
    remaining_shares = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        coerce_to_string=True,
    )
    reserved_at = serializers.DateTimeField()


class OrderHistoryResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Whitelist the orders page envelope and its independent read clocks."""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField(min_value=1)
    orders = OrderHistoryOrderSerializer(many=True)
    has_more = serializers.BooleanField()
    next_cursor = serializers.CharField(allow_null=True, allow_blank=False)
    membership_cutoff = serializers.DateTimeField()
    read_at = serializers.DateTimeField()


class OrderHistoryFillSerializer(serializers.Serializer[dict[str, object]]):
    """Whitelist one exact single-row receipt verification."""

    receipt_id = serializers.IntegerField(min_value=1)
    trade_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1)
    fill_sequence = serializers.IntegerField(min_value=1)
    asset_code = serializers.CharField(max_length=20)
    side = serializers.ChoiceField(choices=_SIDE_CHOICES)
    quantity = serializers.DecimalField(max_digits=20, decimal_places=6, coerce_to_string=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=4, coerce_to_string=True)
    occurred_at = serializers.DateTimeField()
    recorded_at = serializers.DateTimeField()
    observation_basis = serializers.ChoiceField(choices=_OBSERVATION_BASIS_CHOICES)
    verification_status = serializers.ChoiceField(choices=("single_receipt_verified",))


class OrderFillsResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Whitelist one fill-receipt page and explain that an empty page is inconclusive."""

    success = serializers.BooleanField()
    account_id = serializers.IntegerField(min_value=1)
    order_id = serializers.IntegerField(min_value=1)
    fills = OrderHistoryFillSerializer(many=True)
    has_more = serializers.BooleanField()
    next_cursor = serializers.CharField(allow_null=True, allow_blank=False)
    membership_cutoff = serializers.DateTimeField()
    read_at = serializers.DateTimeField()
    receipt_scope_note = serializers.CharField()


__all__ = (
    "OrderFillsResponseSerializer",
    "OrderHistoryFillSerializer",
    "OrderHistoryOrderSerializer",
    "OrderHistoryQuerySerializer",
    "OrderHistoryResponseSerializer",
)
