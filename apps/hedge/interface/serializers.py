"""Explicit hedge API fields without ORM model resolution in the interface layer."""

from typing import Any, cast

from rest_framework import serializers

from apps.hedge.application import interface_services
from apps.hedge.application.dtos import HedgePairWriteData
from apps.hedge.domain.entities import HedgeMethod


class HedgePairSerializer(serializers.Serializer[Any]):
    """Validate hedge configuration and delegate persistence to the application port."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=100)
    long_asset = serializers.CharField(max_length=20)
    hedge_asset = serializers.CharField(max_length=20)
    hedge_method = serializers.ChoiceField(
        choices=[method.value for method in HedgeMethod], required=False
    )
    target_long_weight = serializers.FloatField(required=False)
    target_hedge_weight = serializers.FloatField(required=False)
    rebalance_trigger = serializers.FloatField(required=False)
    correlation_window = serializers.IntegerField(
        required=False, min_value=-(2**63), max_value=2**63 - 1
    )
    min_correlation = serializers.FloatField(required=False)
    max_correlation = serializers.FloatField(required=False)
    correlation_alert_threshold = serializers.FloatField(required=False)
    max_hedge_cost = serializers.FloatField(required=False)
    beta_target = serializers.FloatField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def validate_name(self, value: str) -> str:
        """Keep unique names while allowing an update to retain its existing name."""
        pair_id = cast(int, self.instance.pk) if self.instance is not None else None
        if interface_services.hedge_pair_name_exists(name=value, exclude_pair_id=pair_id):
            raise serializers.ValidationError(
                "A hedge pair with this name already exists.", code="unique"
            )
        return value

    def create(self, validated_data: dict[str, Any]) -> Any:
        """Create one pair through the persistence port, keeping model-owned defaults."""
        return interface_services.create_hedge_pair_record(
            values=cast(HedgePairWriteData, validated_data)
        )

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        """Update only validated fields through the same persistence port."""
        return interface_services.update_hedge_pair_record(
            pair_id=int(instance.pk), values=cast(HedgePairWriteData, validated_data)
        )


class CorrelationHistorySerializer(serializers.Serializer[dict[str, object]]):
    """Format persisted hedge data without querying or resolving ORM models."""

    id = serializers.IntegerField(read_only=True)
    asset1 = serializers.CharField(read_only=True)
    asset2 = serializers.CharField(read_only=True)
    calc_date = serializers.DateField(read_only=True)
    window_days = serializers.IntegerField(read_only=True)
    correlation = serializers.FloatField(read_only=True)
    covariance = serializers.FloatField(read_only=True)
    beta = serializers.FloatField(read_only=True)
    p_value = serializers.FloatField(read_only=True)
    standard_error = serializers.FloatField(read_only=True)
    correlation_trend = serializers.CharField(read_only=True)
    correlation_ma = serializers.FloatField(read_only=True)
    alert = serializers.CharField(read_only=True)
    alert_type = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class HedgePortfolioSnapshotSerializer(serializers.Serializer[dict[str, object]]):
    """Format persisted hedge data without querying or resolving ORM models."""

    id = serializers.IntegerField(read_only=True)
    pair = serializers.IntegerField(read_only=True, source="pair_id")
    pair_name = serializers.CharField(read_only=True, source="pair.name")
    trade_date = serializers.DateField(read_only=True)
    long_weight = serializers.FloatField(read_only=True)
    hedge_weight = serializers.FloatField(read_only=True)
    hedge_ratio = serializers.FloatField(read_only=True)
    target_hedge_ratio = serializers.FloatField(read_only=True)
    current_correlation = serializers.FloatField(read_only=True)
    correlation_20d = serializers.FloatField(read_only=True)
    correlation_60d = serializers.FloatField(read_only=True)
    portfolio_beta = serializers.FloatField(read_only=True)
    portfolio_volatility = serializers.FloatField(read_only=True)
    hedge_effectiveness = serializers.FloatField(read_only=True)
    daily_return = serializers.FloatField(read_only=True)
    unhedged_return = serializers.FloatField(read_only=True)
    hedge_return = serializers.FloatField(read_only=True)
    value_at_risk = serializers.FloatField(read_only=True)
    max_drawdown = serializers.FloatField(read_only=True)
    rebalance_needed = serializers.BooleanField(read_only=True)
    rebalance_reason = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class HedgeAlertSerializer(serializers.Serializer[dict[str, object]]):
    """Format persisted hedge data without querying or resolving ORM models."""

    id = serializers.IntegerField(read_only=True)
    pair_name = serializers.CharField(read_only=True)
    alert_date = serializers.DateField(read_only=True)
    alert_type = serializers.CharField(read_only=True)
    severity = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    current_value = serializers.FloatField(read_only=True)
    threshold_value = serializers.FloatField(read_only=True)
    action_required = serializers.CharField(read_only=True)
    action_priority = serializers.IntegerField(read_only=True)
    is_resolved = serializers.BooleanField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class HedgePerformanceSerializer(serializers.Serializer[dict[str, object]]):
    """Format persisted hedge data without querying or resolving ORM models."""

    id = serializers.IntegerField(read_only=True)
    pair_name = serializers.CharField(read_only=True)
    period_start = serializers.DateField(read_only=True)
    period_end = serializers.DateField(read_only=True)
    total_return = serializers.FloatField(read_only=True)
    annual_return = serializers.FloatField(read_only=True)
    sharpe_ratio = serializers.FloatField(read_only=True)
    volatility_reduction = serializers.FloatField(read_only=True)
    drawdown_reduction = serializers.FloatField(read_only=True)
    hedge_effectiveness = serializers.FloatField(read_only=True)
    hedge_cost = serializers.FloatField(read_only=True)
    cost_benefit_ratio = serializers.FloatField(read_only=True)
    avg_correlation = serializers.FloatField(read_only=True)
    correlation_stability = serializers.FloatField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class HedgeEffectivenessRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Serializer for hedge effectiveness request"""

    lookback_days = serializers.IntegerField(default=60, required=False)


class CorrelationMatrixRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Serializer for correlation matrix request"""

    asset_codes = serializers.ListField(
        child=serializers.CharField(max_length=20, allow_blank=False, trim_whitespace=True),
        required=True,
        min_length=2,
        max_length=50,
    )
    window_days = serializers.IntegerField(
        default=60,
        required=False,
        min_value=2,
        max_value=5000,
    )

    def validate_asset_codes(self, value: list[str]) -> list[str]:
        """Require at least two distinct assets while preserving input order."""

        normalized = list(dict.fromkeys(code.strip().upper() for code in value))
        if len(normalized) < 2:
            raise serializers.ValidationError("至少需要两个不同的资产代码")
        return normalized


class CorrelationCalculationRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Validate one pairwise correlation calculation request."""

    asset1 = serializers.CharField(max_length=20, allow_blank=False, trim_whitespace=True)
    asset2 = serializers.CharField(max_length=20, allow_blank=False, trim_whitespace=True)
    window_days = serializers.IntegerField(
        default=60,
        required=False,
        min_value=2,
        max_value=5000,
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Normalize asset codes and reject self-correlation requests."""

        asset1 = str(attrs["asset1"]).strip().upper()
        asset2 = str(attrs["asset2"]).strip().upper()
        if asset1 == asset2:
            raise serializers.ValidationError("asset1 和 asset2 必须不同")
        attrs["asset1"] = asset1
        attrs["asset2"] = asset2
        return attrs


class HedgeRatioRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Validate a hedge-ratio calculation request."""

    pair_name = serializers.CharField(
        max_length=100,
        allow_blank=False,
        trim_whitespace=True,
    )


class RecentAlertsRequestSerializer(serializers.Serializer[dict[str, object]]):
    """Validate the recent-alert lookback query."""

    days = serializers.IntegerField(default=7, min_value=1, max_value=3650)
