"""
DRF Serializers for Backtest Module.
"""

import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

from django.apps import apps as django_apps
from django.db.models import Model
from rest_framework import serializers

from ..application.use_cases import GetBacktestStatisticsResponse

BacktestResultModel = cast(
    type[Model],
    django_apps.get_model("backtest", "BacktestResultModel"),
)
BacktestTradeModel = cast(
    type[Model],
    django_apps.get_model("backtest", "BacktestTradeModel"),
)


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject request fields outside the published backtest contract."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Validate the request key set before normal field conversion."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected an object payload.")
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown_fields)}"]}
            )
        return cast(dict[str, Any], super().to_internal_value(data))


class FiniteFloatField(serializers.FloatField):
    """DRF float field that rejects booleans, NaN, and infinities."""

    def to_internal_value(self, data: Any) -> float:
        """Return one finite float or raise a field validation error."""

        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("A finite number is required.")
        return value


class BacktestConfigSerializer(StrictFieldsSerializer):
    """回测配置序列化器"""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = FiniteFloatField(min_value=0, allow_null=False)
    rebalance_frequency = serializers.ChoiceField(
        choices=["monthly", "quarterly", "yearly"],
        default="monthly",
    )
    use_pit_data = serializers.BooleanField(default=False)
    transaction_cost_bps = FiniteFloatField(min_value=0, default=10.0)
    trust_status = serializers.ChoiceField(
        choices=["exploratory", "pit_verified"], default="exploratory"
    )
    data_manifest_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    config_hash = serializers.CharField(max_length=64, required=False, allow_blank=True)
    code_commit = serializers.CharField(max_length=64, required=False, allow_blank=True)
    engine_version = serializers.CharField(max_length=64, required=False, default="backtest-v1")
    research_trial_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    decision_snapshot_id = serializers.CharField(max_length=64, required=False, allow_null=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""

        _validate_backtest_configuration(data, require_pit_flag=False)
        return data


class BacktestResultSerializer(serializers.ModelSerializer[Model]):
    """回测结果序列化器"""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = BacktestResultModel
        fields = [
            "id",
            "name",
            "status",
            "status_display",
            "start_date",
            "end_date",
            "initial_capital",
            "final_capital",
            "total_return",
            "annualized_return",
            "max_drawdown",
            "sharpe_ratio",
            "rebalance_frequency",
            "use_pit_data",
            "transaction_cost_bps",
            "data_manifest_id",
            "pit_coverage",
            "trust_status",
            "config_hash",
            "code_commit",
            "engine_version",
            "research_trial_id",
            "decision_snapshot_id",
            "equity_curve",
            "regime_history",
            "trades",
            "warnings",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "final_capital",
            "total_return",
            "annualized_return",
            "max_drawdown",
            "sharpe_ratio",
            "equity_curve",
            "regime_history",
            "trades",
            "warnings",
            "error_message",
            "created_at",
            "updated_at",
            "completed_at",
        ]


class BacktestListSerializer(serializers.ModelSerializer[Model]):
    """回测列表序列化器（精简版）"""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = BacktestResultModel
        fields = [
            "id",
            "name",
            "status",
            "status_display",
            "start_date",
            "end_date",
            "total_return",
            "annualized_return",
            "created_at",
        ]


class RunBacktestSerializer(StrictFieldsSerializer):
    """运行回测请求序列化器"""

    name = serializers.CharField(max_length=200)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = FiniteFloatField(min_value=0, allow_null=False)
    rebalance_frequency = serializers.ChoiceField(
        choices=["monthly", "quarterly", "yearly"],
        default="monthly",
    )
    use_pit_data = serializers.BooleanField(default=False)
    transaction_cost_bps = FiniteFloatField(min_value=0, default=10.0)
    trust_status = serializers.ChoiceField(
        choices=["exploratory", "pit_verified"], default="exploratory"
    )
    data_manifest_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    config_hash = serializers.CharField(max_length=64, required=False, allow_blank=True)
    code_commit = serializers.CharField(max_length=64, required=False, allow_blank=True)
    engine_version = serializers.CharField(max_length=64, required=False, default="backtest-v1")
    research_trial_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    decision_snapshot_id = serializers.CharField(max_length=64, required=False, allow_null=True)
    run_async = serializers.BooleanField(default=False)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """验证请求"""

        _validate_backtest_configuration(data, require_pit_flag=True)
        return data


class DecisionReplayBacktestSerializer(StrictFieldsSerializer):
    """Run a manual decision replay branch."""

    portfolio_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    branch_type = serializers.ChoiceField(
        choices=["actual", "no_action", "system_plan", "delayed_1d"]
    )
    initial_capital = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=Decimal("1000000.00"),
        min_value=Decimal("0.01"),
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate replay dates and finite positive capital."""

        if data["start_date"] >= data["end_date"]:
            raise serializers.ValidationError("start_date must be before end_date")
        initial_capital = data["initial_capital"]
        if not isinstance(initial_capital, Decimal) or not initial_capital.is_finite():
            raise serializers.ValidationError(
                {"initial_capital": "A finite positive amount is required."}
            )
        return data


class BacktestStatisticsSerializer(serializers.Serializer[GetBacktestStatisticsResponse]):
    """回测统计序列化器"""

    total = serializers.IntegerField()
    by_status = serializers.DictField()
    avg_return = serializers.FloatField()
    max_return = serializers.FloatField()
    min_return = serializers.FloatField()


class TradeSerializer(serializers.ModelSerializer[Model]):
    """交易记录序列化器"""

    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = BacktestTradeModel
        fields = [
            "id",
            "backtest",
            "trade_date",
            "asset_class",
            "action",
            "action_display",
            "shares",
            "price",
            "notional",
            "cost",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


def _validate_backtest_configuration(
    data: dict[str, Any],
    *,
    require_pit_flag: bool,
) -> None:
    """Validate shared dates, capital, and point-in-time evidence fields."""

    if data["start_date"] >= data["end_date"]:
        raise serializers.ValidationError("start_date must be before end_date")
    if data["initial_capital"] <= 0:
        raise serializers.ValidationError({"initial_capital": "Must be greater than zero."})

    if data.get("trust_status") != "pit_verified":
        return
    if require_pit_flag and not data.get("use_pit_data"):
        raise serializers.ValidationError(
            {"use_pit_data": "Must be true for pit_verified backtests."}
        )
    if not data.get("data_manifest_id"):
        raise serializers.ValidationError(
            {"data_manifest_id": "Required for pit_verified backtests."}
        )
    missing = [
        field
        for field in (
            "config_hash",
            "code_commit",
            "engine_version",
            "research_trial_id",
            "decision_snapshot_id",
        )
        if not data.get(field)
    ]
    if missing:
        raise serializers.ValidationError(
            dict.fromkeys(missing, "Required for pit_verified backtests.")
        )
