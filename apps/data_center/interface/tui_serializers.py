"""Strict flat serializers for Data Center TUI adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from rest_framework import serializers


class StrictDataCenterTuiSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject fields outside the curated TUI contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, Mapping):
            unknown_fields = sorted(set(data) - set(self.fields))
            if unknown_fields:
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
                )
        return cast(dict[str, Any], super().to_internal_value(data))


class MacroGovernanceTuiActionSerializer(StrictDataCenterTuiSerializer):
    """Select one supported macro-governance repair action."""

    action = serializers.ChoiceField(
        choices=(
            "run_full_repair",
            "canonicalize_sources",
            "normalize_units",
            "sync_missing_series",
        )
    )


class MarketThermometerTuiConfigSerializer(StrictDataCenterTuiSerializer):
    """Flatten the user-facing thermometer config without raw object fields."""

    short_window = serializers.IntegerField(required=False, min_value=1)
    medium_window = serializers.IntegerField(required=False, min_value=1)
    long_window = serializers.IntegerField(required=False, min_value=1)
    daily_stale_days = serializers.IntegerField(required=False, min_value=1)
    monthly_stale_days = serializers.IntegerField(required=False, min_value=1)
    warm_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    hot_threshold = serializers.FloatField(required=False, min_value=0.0, max_value=100.0)
    overheat_threshold = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=100.0,
    )
    extreme_threshold = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=100.0,
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require a real patch and preserve increasing threshold order."""

        if not attrs:
            raise serializers.ValidationError("At least one config field is required.")
        return attrs
