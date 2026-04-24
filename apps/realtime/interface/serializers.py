"""Realtime interface serializers."""

from rest_framework import serializers


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
