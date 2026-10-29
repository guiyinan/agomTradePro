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


class ExactBooleanField(serializers.BooleanField):
    """Accept JSON booleans without DRF's string or numeric coercion."""

    def to_internal_value(self, data: Any) -> bool:
        """Require a literal boolean value from the JSON request body."""

        if type(data) is not bool:
            raise serializers.ValidationError("Must be a JSON boolean.")
        return data


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


class InstrumentReferenceMappingTuiSerializer(StrictDataCenterTuiSerializer):
    """Validate operator-supplied mapping material without inventing defaults."""

    mapping_id = serializers.CharField(max_length=128, trim_whitespace=False)
    mapping_version = serializers.CharField(max_length=128, trim_whitespace=False)
    source_crosswalk_id = serializers.CharField(max_length=128, trim_whitespace=False)
    source_crosswalk_version = serializers.CharField(max_length=128, trim_whitespace=False)
    exchange_suffix_pairs = serializers.ListField(
        child=serializers.ListField(
            child=serializers.CharField(max_length=128, trim_whitespace=False),
            min_length=2,
            max_length=2,
        ),
        min_length=1,
    )
    exchange_rule_market_pairs = serializers.ListField(
        child=serializers.ListField(
            child=serializers.CharField(max_length=128, trim_whitespace=False),
            min_length=2,
            max_length=2,
        ),
        min_length=1,
    )
    exchange_source_market_board_pairs = serializers.ListField(
        child=serializers.ListField(
            child=serializers.CharField(max_length=128, trim_whitespace=False),
            min_length=3,
            max_length=3,
        ),
        min_length=1,
    )


class InstrumentReferenceCaptureTuiSerializer(StrictDataCenterTuiSerializer):
    """Validate one explicit provider/config/mapping/scope capture request."""

    capture_id = serializers.UUIDField()
    provider_configuration_id = serializers.IntegerField(min_value=1)
    mapping_record_id = serializers.UUIDField()
    exchange_scope = serializers.ListField(
        child=serializers.CharField(max_length=128, trim_whitespace=False),
        min_length=1,
    )
    list_status_scope = serializers.ListField(
        child=serializers.CharField(max_length=128, trim_whitespace=False),
        min_length=1,
    )
    mode = serializers.ChoiceField(choices=("normal", "resume"))
    include_currency = ExactBooleanField(required=False, default=False)


class InstrumentReferenceSnapshotPageTuiSerializer(StrictDataCenterTuiSerializer):
    """Bound both source-row and occurrence pages to a deterministic response."""

    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=200)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
