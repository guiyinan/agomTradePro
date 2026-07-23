"""
账户业绩与估值 API 序列化器

Interface 层：只做输入验证和输出格式化，无业务逻辑。
"""

from typing import Any

from rest_framework import serializers

# ---------------------------------------------------------------------------
# 请求参数序列化器
# ---------------------------------------------------------------------------


class PerformanceReportQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """GET /performance-report/ 查询参数。"""

    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if data["start_date"] >= data["end_date"]:
            raise serializers.ValidationError("end_date 必须晚于 start_date")
        return data


class ValuationSnapshotQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """GET /valuation-snapshot/ 查询参数。"""

    as_of_date = serializers.DateField(required=True)


class ValuationTimelineQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """GET /valuation-timeline/ 查询参数。"""

    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)


class BenchmarkComponentInputSerializer(serializers.Serializer[dict[str, Any]]):
    """PUT /benchmarks/ 单个基准成分输入。"""

    benchmark_code = serializers.CharField(max_length=30)
    weight = serializers.FloatField(min_value=0)  # 归一化前可超过 1，用例内部处理
    display_name = serializers.CharField(
        max_length=100, required=False, default="", allow_blank=True
    )
    sort_order = serializers.IntegerField(required=False, default=0)


class BenchmarkPutSerializer(serializers.Serializer[dict[str, Any]]):
    """PUT /benchmarks/ 请求体。"""

    components = BenchmarkComponentInputSerializer(many=True)

    def validate_components(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not value:
            raise serializers.ValidationError("至少需要配置 1 个基准成分")
        return value


# ---------------------------------------------------------------------------
# 响应序列化器（用于 drf_spectacular 文档和输出格式化）
# ---------------------------------------------------------------------------


class CoverageInfoSerializer(serializers.Serializer[dict[str, Any]]):
    data_start = serializers.DateField(allow_null=True)
    data_end = serializers.DateField(allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField())


class PerformancePeriodSerializer(serializers.Serializer[dict[str, Any]]):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    days = serializers.IntegerField()


class PerformanceReturnsSerializer(serializers.Serializer[dict[str, Any]]):
    twr = serializers.FloatField(allow_null=True)
    mwr = serializers.FloatField(allow_null=True)
    annualized_twr = serializers.FloatField(allow_null=True)
    annualized_mwr = serializers.FloatField(allow_null=True)


class PerformanceRiskSerializer(serializers.Serializer[dict[str, Any]]):
    volatility = serializers.FloatField(allow_null=True)
    downside_volatility = serializers.FloatField(allow_null=True)
    max_drawdown = serializers.FloatField(allow_null=True)


class PerformanceRatiosSerializer(serializers.Serializer[dict[str, Any]]):
    sharpe = serializers.FloatField(allow_null=True)
    sortino = serializers.FloatField(allow_null=True)
    calmar = serializers.FloatField(allow_null=True)
    treynor = serializers.FloatField(allow_null=True)


class BenchmarkStatsSerializer(serializers.Serializer[dict[str, Any]]):
    benchmark_return = serializers.FloatField(allow_null=True)
    excess_return = serializers.FloatField(allow_null=True)
    beta = serializers.FloatField(allow_null=True)
    alpha = serializers.FloatField(allow_null=True)
    tracking_error = serializers.FloatField(allow_null=True)
    information_ratio = serializers.FloatField(allow_null=True)


class TradeStatsSerializer(serializers.Serializer[dict[str, Any]]):
    win_rate = serializers.FloatField(allow_null=True)
    profit_factor = serializers.FloatField(allow_null=True)
    total_closed_trades = serializers.IntegerField()


class PerformanceReportResponseSerializer(serializers.Serializer[dict[str, Any]]):
    period = PerformancePeriodSerializer()
    returns = PerformanceReturnsSerializer()
    risk = PerformanceRiskSerializer()
    ratios = PerformanceRatiosSerializer()
    benchmark = BenchmarkStatsSerializer(allow_null=True)
    trade_stats = TradeStatsSerializer()
    coverage = CoverageInfoSerializer()
    warnings = serializers.ListField(child=serializers.CharField())


class ValuationRowSerializer(serializers.Serializer[dict[str, Any]]):
    asset_code = serializers.CharField()
    asset_name = serializers.CharField()
    asset_type = serializers.CharField()
    quantity = serializers.FloatField()
    avg_cost = serializers.FloatField()
    close_price = serializers.FloatField()
    market_value = serializers.FloatField()
    weight = serializers.FloatField()
    unrealized_pnl = serializers.FloatField()
    unrealized_pnl_pct = serializers.FloatField()


class AccountValuationSummarySerializer(serializers.Serializer[dict[str, Any]]):
    total_value = serializers.FloatField()
    cash = serializers.FloatField()
    market_value = serializers.FloatField()
    unrealized_pnl = serializers.FloatField()
    unrealized_pnl_pct = serializers.FloatField()


class ValuationSnapshotResponseSerializer(serializers.Serializer[dict[str, Any]]):
    as_of_date = serializers.DateField()
    account_summary = AccountValuationSummarySerializer()
    rows = ValuationRowSerializer(many=True)
    coverage = CoverageInfoSerializer()


class ValuationTimelinePointSerializer(serializers.Serializer[dict[str, Any]]):
    date = serializers.DateField()
    cash = serializers.FloatField()
    market_value = serializers.FloatField()
    total_value = serializers.FloatField()
    net_value = serializers.FloatField()
    twr_cumulative = serializers.FloatField()
    drawdown = serializers.FloatField()


class ValuationTimelineResponseSerializer(serializers.Serializer[dict[str, Any]]):
    points = ValuationTimelinePointSerializer(many=True)


class BenchmarkComponentResponseSerializer(serializers.Serializer[dict[str, Any]]):
    account_id = serializers.IntegerField()
    benchmark_code = serializers.CharField()
    weight = serializers.FloatField()
    display_name = serializers.CharField()
    sort_order = serializers.IntegerField()
    is_active = serializers.BooleanField()
