"""
DRF Serializers for Regime API.
"""

from datetime import date
from typing import Any, Dict

from rest_framework import serializers


class RegimeSnapshotSerializer(serializers.Serializer):
    """Serializer for RegimeSnapshot domain entity"""

    observed_at = serializers.DateField()
    dominant_regime = serializers.CharField(max_length=20)
    confidence = serializers.FloatField()
    growth_momentum_z = serializers.FloatField(allow_null=True)
    inflation_momentum_z = serializers.FloatField(allow_null=True)
    regime_distribution = serializers.DictField(child=serializers.FloatField())
    data_source = serializers.CharField(max_length=20)
    created_at = serializers.DateTimeField()


class RegimeCalculateRequestSerializer(serializers.Serializer):
    """Serializer for Regime calculation request"""

    as_of_date = serializers.DateField(required=False, default=date.today)
    use_pit = serializers.BooleanField(default=True)
    growth_indicator = serializers.CharField(default="PMI")
    inflation_indicator = serializers.CharField(default="CPI")
    data_source = serializers.CharField(default="akshare")


class RegimeCalculateResponseSerializer(serializers.Serializer):
    """Serializer for Regime calculation response"""

    success = serializers.BooleanField()
    snapshot = RegimeSnapshotSerializer(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    error = serializers.CharField(allow_null=True)
    raw_data = serializers.DictField(allow_null=True, required=False)
    intermediate_data = serializers.DictField(allow_null=True, required=False)


class RegimeLogSerializer(serializers.Serializer):
    """Serializer for regime history payloads."""

    id = serializers.IntegerField()
    observed_at = serializers.DateField()
    dominant_regime = serializers.CharField(max_length=20)
    confidence = serializers.FloatField()
    growth_momentum_z = serializers.FloatField(allow_null=True)
    inflation_momentum_z = serializers.FloatField(allow_null=True)
    distribution = serializers.DictField(required=False)
    created_at = serializers.DateTimeField()


class RegimeHistoryQuerySerializer(serializers.Serializer):
    """Serializer for Regime history query parameters"""

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    regime = serializers.CharField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=100, min_value=1, max_value=1000)
