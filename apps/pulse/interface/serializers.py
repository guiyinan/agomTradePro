"""Pulse interface serializers.

The Pulse API currently serializes domain snapshots in `api_views.py`.
This module keeps the interface package aligned with the project layout and
provides reusable serializers for future API contract tightening.
"""

from typing import Any

from rest_framework import serializers


class PulseDimensionSerializer(serializers.Serializer[dict[str, Any]]):
    """Serialized dimension score in a Pulse snapshot."""

    score = serializers.FloatField()
    signal = serializers.CharField()
    indicator_count = serializers.IntegerField()
    description = serializers.CharField(allow_blank=True)


class PulseSnapshotSerializer(serializers.Serializer[dict[str, Any]]):
    """Public Pulse snapshot payload shape."""

    observed_at = serializers.DateField()
    regime_context = serializers.CharField()
    composite_score = serializers.FloatField()
    regime_strength = serializers.CharField()
    transition_warning = serializers.BooleanField()
    transition_direction = serializers.CharField(allow_blank=True)
    transition_reasons = serializers.ListField(child=serializers.CharField())
    data_source = serializers.CharField()
    is_reliable = serializers.BooleanField()
    is_stale = serializers.BooleanField()
    stale_indicator_codes = serializers.ListField(child=serializers.CharField())
    must_not_use_for_decision = serializers.BooleanField()
    blocked_reason = serializers.CharField(allow_blank=True)
    market_data_as_of = serializers.DateField(allow_null=True)
    indicator_observed_at = serializers.DictField(child=serializers.DateField(allow_null=True))
    contract = serializers.DictField()
    dimensions = serializers.DictField(child=PulseDimensionSerializer())


class PulseHistoryQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Validate bounded Pulse history query controls."""

    months = serializers.IntegerField(min_value=1, max_value=120, default=6)
    limit = serializers.IntegerField(
        min_value=1,
        max_value=500,
        required=False,
        allow_null=True,
    )
