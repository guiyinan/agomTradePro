"""DRF serializers for the factor module API."""

from __future__ import annotations

from typing import Any, cast

from rest_framework import serializers

from apps.factor.application.use_cases import (
    FACTOR_REBALANCE_CHOICES,
    FACTOR_UNIVERSE_CHOICES,
    FACTOR_WEIGHT_METHOD_CHOICES,
)
from apps.factor.domain.entities import FactorCategory, FactorDirection

_UPDATE_FREQUENCIES = ("daily", "weekly", "monthly", "quarterly")


class FactorDefinitionSerializer(serializers.Serializer[Any]):
    """Serializer for factor definition payloads."""

    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=100)
    category = serializers.ChoiceField(choices=tuple(category.value for category in FactorCategory))
    description = serializers.CharField(allow_blank=True, required=False)
    data_source = serializers.CharField(max_length=50)
    data_field = serializers.CharField(max_length=100)
    direction = serializers.ChoiceField(
        choices=tuple(direction.value for direction in FactorDirection),
        default=FactorDirection.POSITIVE.value,
    )
    update_frequency = serializers.ChoiceField(
        choices=_UPDATE_FREQUENCIES,
        default="daily",
    )
    is_active = serializers.BooleanField(default=True)
    min_data_points = serializers.IntegerField(default=20, min_value=1)
    allow_missing = serializers.BooleanField(default=False)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    direction_display = serializers.CharField(source="get_direction_display", read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class FactorExposureSerializer(serializers.Serializer[Any]):
    """Serializer for factor exposure payloads."""

    id = serializers.IntegerField(read_only=True)
    stock_code = serializers.CharField(max_length=20)
    trade_date = serializers.DateField()
    factor_code = serializers.CharField(max_length=50)
    factor_value = serializers.DecimalField(max_digits=18, decimal_places=6)
    percentile_rank = serializers.DecimalField(max_digits=5, decimal_places=4)
    z_score = serializers.DecimalField(max_digits=10, decimal_places=6)
    normalized_score = serializers.DecimalField(max_digits=6, decimal_places=2)
    created_at = serializers.DateTimeField(read_only=True)


class FactorPortfolioConfigSerializer(serializers.Serializer[Any]):
    """Serializer for factor portfolio configuration payloads."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(allow_blank=True, required=False)
    factor_weights = serializers.DictField(
        child=serializers.FloatField(min_value=-1, max_value=1),
        required=False,
        default=dict,
    )
    universe = serializers.ChoiceField(
        choices=tuple(FACTOR_UNIVERSE_CHOICES),
        default="all_a",
    )
    min_market_cap = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
    )
    max_market_cap = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0,
    )
    max_pe = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
        min_value=0,
    )
    min_pe = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
        min_value=0,
    )
    max_pb = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        required=False,
        allow_null=True,
        min_value=0,
    )
    max_debt_ratio = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=100,
    )
    top_n = serializers.IntegerField(default=30, min_value=1, max_value=500)
    rebalance_frequency = serializers.ChoiceField(
        choices=tuple(FACTOR_REBALANCE_CHOICES),
        default="monthly",
    )
    weight_method = serializers.ChoiceField(
        choices=tuple(FACTOR_WEIGHT_METHOD_CHOICES),
        default="equal_weight",
    )
    max_sector_weight = serializers.FloatField(
        required=False,
        default=0.4,
        min_value=0.000001,
        max_value=1,
    )
    max_single_stock_weight = serializers.FloatField(
        required=False,
        default=0.05,
        min_value=0.000001,
        max_value=1,
    )
    is_active = serializers.BooleanField(default=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class FactorWeightMutationSerializer(serializers.Serializer[Any]):
    """Validate one bounded factor-weight update."""

    factor_code = serializers.CharField(max_length=50, allow_blank=False)
    weight = serializers.FloatField(min_value=-1, max_value=1)


class FactorWeightRemovalSerializer(serializers.Serializer[Any]):
    """Validate one factor-weight removal."""

    factor_code = serializers.CharField(max_length=50, allow_blank=False)


class FactorPortfolioHoldingSerializer(serializers.Serializer[Any]):
    """Serializer for factor portfolio holding payloads."""

    id = serializers.IntegerField(read_only=True)
    config = serializers.IntegerField(source="config_id")
    config_name = serializers.CharField(source="config.name", read_only=True)
    trade_date = serializers.DateField()
    stock_code = serializers.CharField(max_length=20)
    stock_name = serializers.CharField(max_length=100)
    weight = serializers.DecimalField(max_digits=10, decimal_places=6)
    factor_score = serializers.DecimalField(max_digits=10, decimal_places=4)
    rank = serializers.IntegerField()
    sector = serializers.CharField(max_length=50, allow_blank=True, required=False)
    factor_scores = serializers.DictField(required=False)
    created_at = serializers.DateTimeField(read_only=True)


class FactorPortfolioReadQuerySerializer(serializers.Serializer[Any]):
    """Validate the persisted factor portfolio read contract."""

    config_name = serializers.CharField(max_length=100, allow_blank=False)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject query parameters outside the governed schema."""

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown query parameters: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class FactorScoreRequestSerializer(serializers.Serializer[Any]):
    """Serializer for factor score calculation requests."""

    trade_date = serializers.DateField(required=False)
    universe = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
    )
    factor_codes = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
    )
    factor_weights = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
        default=dict,
    )
    top_n = serializers.IntegerField(required=False, default=50)


class FactorConfigCalculationRequestSerializer(serializers.Serializer[Any]):
    """Validate score calculation against one stored portfolio config."""

    config_id = serializers.IntegerField(min_value=1)
    trade_date = serializers.DateField(required=False)
    top_n = serializers.IntegerField(required=False, default=30, min_value=1, max_value=100)


class FactorConfigExplanationRequestSerializer(serializers.Serializer[Any]):
    """Validate one stock explanation against a stored portfolio config."""

    config_id = serializers.IntegerField(min_value=1)
    stock_code = serializers.CharField(max_length=20, allow_blank=False)


class FactorScoreResponseSerializer(serializers.Serializer[Any]):
    """Serializer for factor score responses."""

    stock_code = serializers.CharField(max_length=20)
    stock_name = serializers.CharField(max_length=100)
    composite_score = serializers.FloatField()
    percentile_rank = serializers.FloatField()
    factor_scores = serializers.DictField(
        child=serializers.FloatField(),
        required=False,
    )
    sector = serializers.CharField(max_length=50, required=False, allow_blank=True)
    market_cap = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
