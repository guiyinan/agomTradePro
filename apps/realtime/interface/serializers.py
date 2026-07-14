"""Realtime interface serializers."""

from decimal import Decimal
from typing import Any

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    """Reject unknown input fields instead of silently ignoring them."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate that every submitted field is declared."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return super().to_internal_value(data)


class PriceAlertCreateSerializer(StrictSerializer):
    """Validate a price-alert creation command."""

    asset_code = serializers.CharField(min_length=1, max_length=32, trim_whitespace=True)
    condition = serializers.ChoiceField(
        choices=("above", "below", "cross_up", "cross_down")
    )
    threshold = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
    )
    message = serializers.CharField(
        max_length=500,
        allow_blank=True,
        required=False,
        default="",
    )


class PriceAlertUpdateSerializer(StrictSerializer):
    """Validate a bounded alert update command."""

    condition = serializers.ChoiceField(
        choices=("above", "below", "cross_up", "cross_down"),
        required=False,
    )
    threshold = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        required=False,
    )
    status = serializers.ChoiceField(
        choices=("active", "inactive"),
        required=False,
    )
    message = serializers.CharField(
        max_length=500,
        allow_blank=True,
        required=False,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require at least one mutable field."""

        if not attrs:
            raise serializers.ValidationError("At least one field is required.")
        return attrs


class PriceSubscriptionCommandSerializer(StrictSerializer):
    """Validate a durable subscription command."""

    asset_code = serializers.CharField(min_length=1, max_length=32, trim_whitespace=True)


class PriceAlertResponseSerializer(serializers.Serializer):
    """Serialize a durable price alert."""

    id = serializers.IntegerField()
    asset_code = serializers.CharField()
    condition = serializers.CharField()
    threshold = serializers.DecimalField(max_digits=20, decimal_places=6)
    status = serializers.CharField()
    message = serializers.CharField()
    triggered_price = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        allow_null=True,
    )
    triggered_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class PriceSubscriptionResponseSerializer(serializers.Serializer):
    """Serialize a durable realtime subscription."""

    id = serializers.IntegerField()
    asset_code = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)


class SectorPerformanceQuerySerializer(serializers.Serializer):
    """Reject parameters for the zero-input sector performance contract."""

    def to_internal_value(self, data):
        """Reject unknown query parameters instead of silently ignoring them."""

        unknown_fields = sorted(set(data))
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        f"Unknown query parameters: {', '.join(unknown_fields)}"
                    ]
                }
            )
        return super().to_internal_value(data)


class TopMoversQuerySerializer(serializers.Serializer):
    """Validate the persisted top-movers query."""

    direction = serializers.ChoiceField(choices=("up", "down"), default="up")
    limit = serializers.IntegerField(min_value=1, max_value=200, default=10)

    def to_internal_value(self, data):
        """Reject unknown query parameters instead of silently ignoring them."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        f"Unknown query parameters: {', '.join(unknown_fields)}"
                    ]
                }
            )
        return super().to_internal_value(data)


class RealtimePriceSerializer(serializers.Serializer):
    """Realtime price response payload."""

    asset_code = serializers.CharField()
    asset_type = serializers.CharField()
    price = serializers.DecimalField(max_digits=20, decimal_places=6)
    change = serializers.DecimalField(max_digits=20, decimal_places=6, allow_null=True)
    change_pct = serializers.DecimalField(max_digits=12, decimal_places=6, allow_null=True)
    volume = serializers.IntegerField(allow_null=True)
    timestamp = serializers.DateTimeField()
    source = serializers.CharField()
