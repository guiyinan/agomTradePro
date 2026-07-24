"""
Rotation Module Interface Layer - Serializers

DRF Serializers for the rotation module API.
"""

from datetime import date
from typing import Any, Protocol, TypedDict

from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework import serializers

from apps.rotation.domain.services import is_rotation_signal_stale

AssetClassModel = django_apps.get_model("rotation", "AssetClassModel")
MomentumScoreModel = django_apps.get_model("rotation", "MomentumScoreModel")
PortfolioRotationConfigModel = django_apps.get_model("rotation", "PortfolioRotationConfigModel")
RotationConfigModel = django_apps.get_model("rotation", "RotationConfigModel")
RotationPortfolioModel = django_apps.get_model("rotation", "RotationPortfolioModel")
RotationSignalModel = django_apps.get_model("rotation", "RotationSignalModel")
RotationTemplateModel = django_apps.get_model("rotation", "RotationTemplateModel")


class RotationSignalConfigRecord(Protocol):
    """Configuration fields consumed by signal serialization."""

    asset_universe: list[str]
    strategy_type: str
    rebalance_frequency: str


class RotationSignalRecord(Protocol):
    """Persisted signal projection consumed by serializer helpers."""

    config: RotationSignalConfigRecord
    signal_date: date
    momentum_ranking: list[Any]
    target_allocation: dict[str, float]
    expected_return: float
    expected_volatility: float


class SignalDataQuality(TypedDict):
    """Stable data-quality payload returned by the signal API."""

    status: str
    universe_size: int
    ranked_asset_count: int
    selected_asset_count: int
    coverage_ratio: float
    metrics_available: bool
    warnings: list[str]


class AssetClassSerializer(serializers.ModelSerializer[Any]):
    """Serializer for AssetClass"""

    class Meta:
        model = AssetClassModel
        fields = [
            "id",
            "code",
            "name",
            "category",
            "description",
            "underlying_index",
            "currency",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RotationConfigSerializer(serializers.ModelSerializer[Any]):
    """Serializer for RotationConfig"""

    class Meta:
        model = RotationConfigModel
        fields = [
            "id",
            "name",
            "description",
            "strategy_type",
            "asset_universe",
            "params",
            "rebalance_frequency",
            "min_weight",
            "max_weight",
            "max_turnover",
            "lookback_period",
            "regime_allocations",
            "momentum_periods",
            "top_n",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RotationSignalSerializer(serializers.ModelSerializer[Any]):
    """Serializer for RotationSignal"""

    config_name = serializers.CharField(source="config.name", read_only=True)
    data_quality = serializers.SerializerMethodField()
    is_stale = serializers.SerializerMethodField()
    staleness_days = serializers.SerializerMethodField()
    actionable = serializers.SerializerMethodField()
    execution_block_reason = serializers.SerializerMethodField()

    class Meta:
        model = RotationSignalModel
        fields = [
            "id",
            "config",
            "config_name",
            "signal_date",
            "target_allocation",
            "current_regime",
            "momentum_ranking",
            "expected_volatility",
            "expected_return",
            "action_required",
            "reason",
            "data_quality",
            "is_stale",
            "staleness_days",
            "actionable",
            "execution_block_reason",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_data_quality(self, obj: RotationSignalRecord) -> SignalDataQuality:
        """Expose data-quality metadata for persisted signals."""
        universe = getattr(obj.config, "asset_universe", []) or []
        strategy_type = getattr(obj.config, "strategy_type", "")
        ranking = obj.momentum_ranking or []
        allocation = obj.target_allocation or {}
        requires_ranking = strategy_type in {
            "momentum",
            "regime_based",
            "custom",
            "mean_reversion",
        }
        coverage_count = len(ranking) if requires_ranking else len(allocation)
        coverage_ratio = coverage_count / len(universe) if universe else 0.0
        metrics_available = (
            float(obj.expected_return or 0.0) != 0.0 or float(obj.expected_volatility or 0.0) != 0.0
        )
        warnings: list[str] = []
        status = "ok"
        if universe and coverage_count < len(universe):
            status = "degraded"
            warnings.append("partial_price_coverage")
        if not metrics_available:
            status = "degraded"
            warnings.append("risk_return_metrics_unavailable")
        if not allocation:
            status = "invalid"
            warnings.append("empty_target_allocation")
        return {
            "status": status,
            "universe_size": len(universe),
            "ranked_asset_count": len(ranking),
            "selected_asset_count": len(allocation),
            "coverage_ratio": round(coverage_ratio, 4),
            "metrics_available": metrics_available,
            "warnings": warnings,
        }

    def get_is_stale(self, obj: RotationSignalRecord) -> bool:
        """Whether the signal has crossed its configured rebalance period."""
        return bool(
            is_rotation_signal_stale(
                obj.signal_date,
                obj.config.rebalance_frequency,
                timezone.localdate(),
            )
        )

    def get_staleness_days(self, obj: RotationSignalRecord) -> int:
        """Age of the signal in calendar days."""
        return max((timezone.localdate() - obj.signal_date).days, 0)

    def get_actionable(self, obj: RotationSignalRecord) -> bool:
        """Only fresh, full-quality persisted signals are executable."""
        return (not self.get_is_stale(obj)) and self.get_data_quality(obj)["status"] == "ok"

    def get_execution_block_reason(self, obj: RotationSignalRecord) -> str | None:
        """Explain why this signal must not drive trading actions."""
        if self.get_actionable(obj):
            return None
        if self.get_is_stale(obj):
            return "stale_rotation_signal"
        return f"rotation_data_quality_{self.get_data_quality(obj)['status']}"


class RotationPortfolioSerializer(serializers.ModelSerializer[Any]):
    """Serializer for RotationPortfolio"""

    config_name = serializers.CharField(source="config.name", read_only=True)

    class Meta:
        model = RotationPortfolioModel
        fields = [
            "id",
            "config",
            "config_name",
            "trade_date",
            "current_allocation",
            "daily_return",
            "cumulative_return",
            "portfolio_volatility",
            "max_drawdown",
            "turnover_since_last",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MomentumScoreSerializer(serializers.ModelSerializer[Any]):
    """Serializer for MomentumScore"""

    class Meta:
        model = MomentumScoreModel
        fields = [
            "id",
            "asset_code",
            "calc_date",
            "momentum_1m",
            "momentum_3m",
            "momentum_6m",
            "momentum_12m",
            "composite_score",
            "rank",
            "sharpe_1m",
            "sharpe_3m",
            "ma_signal",
            "trend_strength",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class RotationSignalRequestSerializer(serializers.Serializer[Any]):
    """Serializer for rotation signal request"""

    signal_date = serializers.DateField(required=False)


class RotationTemplateSerializer(serializers.ModelSerializer[Any]):
    """Serializer for RotationTemplate (read-only presets from DB)"""

    allocations = serializers.JSONField(source="regime_allocations", read_only=True)

    class Meta:
        model = RotationTemplateModel
        fields = [
            "id",
            "key",
            "name",
            "description",
            "regime_allocations",
            "allocations",
            "display_order",
        ]


class PortfolioRotationConfigSerializer(serializers.ModelSerializer[Any]):
    """
    Serializer for per-account rotation config.

    MCP and frontend both use this to read/write per-account regime allocations
    and risk tolerance. Validates that each regime's weights sum to 1.0.
    """

    account_name = serializers.CharField(source="account.account_name", read_only=True)
    account_type = serializers.CharField(source="account.account_type", read_only=True)
    base_config_name = serializers.CharField(
        source="base_config.name", read_only=True, default=None
    )

    class Meta:
        model = PortfolioRotationConfigModel
        fields = [
            "id",
            "account",
            "account_name",
            "account_type",
            "base_config",
            "base_config_name",
            "risk_tolerance",
            "regime_allocations",
            "is_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_regime_allocations(
        self,
        value: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        """Each regime's weights must sum to 1.0 (±0.01 tolerance)."""
        normalized: dict[str, dict[str, float]] = {}
        for regime, allocations in value.items():
            if not isinstance(allocations, dict):
                raise serializers.ValidationError(
                    f"象限 {regime} 的配置必须是 dict，收到 {type(allocations).__name__}"
                )
            normalized_allocations: dict[str, float] = {}
            for asset_code, weight in allocations.items():
                if (
                    not isinstance(asset_code, str)
                    or not asset_code
                    or isinstance(weight, bool)
                    or not isinstance(weight, (int, float))
                ):
                    raise serializers.ValidationError(
                        f"象限 {regime} 的资产代码和权重必须分别为非空字符串与数字"
                    )
                normalized_allocations[asset_code] = float(weight)
            total = sum(normalized_allocations.values())
            if abs(total - 1.0) > 0.01:
                raise serializers.ValidationError(
                    f"象限 {regime} 的权重之和为 {total:.4f}，必须为 1.0（允许 ±0.01 误差）"
                )
            normalized[regime] = normalized_allocations
        return normalized
