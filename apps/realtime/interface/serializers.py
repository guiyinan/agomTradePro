"""Realtime interface serializers."""

from rest_framework import serializers


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
