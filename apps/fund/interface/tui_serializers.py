"""Strict serializers for TUI-facing fund operations."""

from __future__ import annotations

from typing import Any, cast

from rest_framework import serializers

from apps.regime.domain.services_v2 import RegimeType


class FundTuiMultiDimScreenRequestSerializer(serializers.Serializer[Any]):
    """Validate flat multidimensional fund filters for the TUI."""

    fund_type = serializers.CharField(max_length=50, required=False, allow_blank=True)
    investment_style = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )
    min_scale = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
    )
    regime = serializers.ChoiceField(
        choices=tuple(regime.value for regime in RegimeType),
        required=True,
    )
    policy_level = serializers.ChoiceField(
        choices=("P0", "P1", "P2", "P3"),
        required=True,
    )
    sentiment_index = serializers.FloatField(
        required=True,
        min_value=-1,
        max_value=1,
    )
    max_count = serializers.IntegerField(default=30, min_value=1, max_value=100)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject fields outside the flat published contract."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown parameters: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))
