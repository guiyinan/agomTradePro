"""
Alpha Serializers

Django REST Framework 序列化器定义。
"""

from typing import Any

from rest_framework import serializers

from ..application.pool_resolver import get_alpha_pool_mode_choices
from ..domain.entities import AlphaResult, StockScore

_ALPHA_POOL_MODE_VALUES = [item["value"] for item in get_alpha_pool_mode_choices()]


class StockScoreSerializer(serializers.Serializer):
    """股票评分序列化器"""

    code = serializers.CharField(help_text="股票代码")
    score = serializers.FloatField(help_text="评分")
    rank = serializers.IntegerField(help_text="排名")
    factors = serializers.DictField(
        child=serializers.FloatField(), help_text="因子暴露", required=False, default={}
    )
    source = serializers.CharField(help_text="来源")
    confidence = serializers.FloatField(help_text="置信度")

    # 审计字段
    model_id = serializers.CharField(help_text="模型标识", required=False, allow_null=True)
    model_artifact_hash = serializers.CharField(
        help_text="模型哈希", required=False, allow_null=True
    )
    asof_date = serializers.DateField(help_text="信号真实日期", required=False, allow_null=True)
    intended_trade_date = serializers.DateField(
        help_text="计划交易日期", required=False, allow_null=True
    )
    universe_id = serializers.CharField(help_text="股票池标识", required=False, allow_null=True)
    feature_set_id = serializers.CharField(help_text="特征集标识", required=False, allow_null=True)
    label_id = serializers.CharField(help_text="标签标识", required=False, allow_null=True)
    data_version = serializers.CharField(help_text="数据版本", required=False, allow_null=True)

    def create(self, validated_data: dict[str, Any]) -> StockScore:
        """从验证数据创建 StockScore"""
        return StockScore(**validated_data)

    def to_representation(self, instance: StockScore) -> dict[str, Any]:
        """转换为字典表示"""
        return instance.to_dict()


class AlphaResultSerializer(serializers.Serializer):
    """Alpha 结果序列化器"""

    success = serializers.BooleanField(help_text="是否成功")
    source = serializers.CharField(help_text="数据来源")
    timestamp = serializers.CharField(help_text="时间戳")
    status = serializers.CharField(help_text="状态")
    error_message = serializers.CharField(help_text="错误信息", required=False, allow_null=True)
    latency_ms = serializers.IntegerField(help_text="延迟（毫秒）", required=False, allow_null=True)
    staleness_days = serializers.IntegerField(
        help_text="数据陈旧天数", required=False, allow_null=True
    )
    stocks = StockScoreSerializer(many=True, help_text="股票评分列表")
    metadata = serializers.DictField(help_text="额外元数据", required=False, default={})

    def create(self, validated_data: dict[str, Any]) -> AlphaResult:
        """从验证数据创建 AlphaResult"""
        stocks_data = validated_data.pop("stocks", [])
        stocks = [StockScore(**s) for s in stocks_data]

        return AlphaResult(stocks=stocks, **validated_data)

    def to_representation(self, instance: AlphaResult) -> dict[str, Any]:
        """转换为字典表示"""
        return instance.to_dict()


class GetStockScoresRequestSerializer(serializers.Serializer):
    """获取股票评分请求序列化器"""

    universe = serializers.CharField(default="csi300", help_text="股票池标识")
    trade_date = serializers.DateField(required=False, help_text="交易日期（ISO 格式）")
    top_n = serializers.IntegerField(
        default=30, min_value=1, max_value=500, help_text="返回前 N 只股票"
    )
    user_id = serializers.IntegerField(
        required=False, min_value=1, help_text="管理员可选：指定查看某个用户的个人评分"
    )
    provider = serializers.CharField(
        required=False,
        default="",
        help_text="强制使用指定 Provider（qlib/cache/simple/etf），留空则自动降级",
    )


class ProviderStatusSerializer(serializers.Serializer):
    """Provider 状态序列化器"""

    priority = serializers.IntegerField(help_text="优先级")
    status = serializers.CharField(help_text="状态")
    max_staleness_days = serializers.IntegerField(help_text="最大陈旧天数", required=False)
    error = serializers.CharField(help_text="错误信息", required=False, allow_null=True)


class UploadScoreItemSerializer(serializers.Serializer):
    """单条评分上传序列化器"""

    code = serializers.CharField(help_text="股票代码")
    score = serializers.FloatField(help_text="评分")
    rank = serializers.IntegerField(help_text="排名")
    factors = serializers.DictField(
        child=serializers.FloatField(), required=False, default=dict, help_text="因子暴露"
    )
    confidence = serializers.FloatField(required=False, default=1.0, help_text="置信度")
    source = serializers.CharField(required=False, default="local_qlib", help_text="来源标识")


class UploadScoresSerializer(serializers.Serializer):
    """批量评分上传序列化器"""

    universe_id = serializers.CharField(help_text="股票池标识")
    asof_date = serializers.DateField(help_text="信号真实生成日期")
    intended_trade_date = serializers.DateField(help_text="计划交易日期")
    model_id = serializers.CharField(required=False, default="local_qlib", help_text="模型标识")
    model_artifact_hash = serializers.CharField(
        required=False, default="", help_text="模型文件哈希"
    )
    scope = serializers.ChoiceField(
        choices=["user", "system"],
        default="user",
        help_text="写入范围：user=个人，system=全局（仅 admin）",
    )
    scores = UploadScoreItemSerializer(many=True, help_text="评分列表")


class AlphaOpsInferenceTriggerSerializer(serializers.Serializer):
    """Trigger serializer for Alpha inference ops actions."""

    MODE_GENERAL = "general"
    MODE_PORTFOLIO_SCOPED = "portfolio_scoped"
    MODE_DAILY_SCOPED_BATCH = "daily_scoped_batch"

    mode = serializers.ChoiceField(
        choices=[MODE_GENERAL, MODE_PORTFOLIO_SCOPED, MODE_DAILY_SCOPED_BATCH]
    )
    trade_date = serializers.DateField(required=False, help_text="目标交易日")
    top_n = serializers.IntegerField(default=30, min_value=1, max_value=500)
    universe_id = serializers.CharField(required=False, allow_blank=False)
    portfolio_id = serializers.IntegerField(required=False, min_value=1)
    pool_mode = serializers.ChoiceField(
        required=False,
        choices=_ALPHA_POOL_MODE_VALUES,
        default="price_covered",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        mode = attrs["mode"]
        if mode in {self.MODE_GENERAL, self.MODE_PORTFOLIO_SCOPED} and "trade_date" not in attrs:
            raise serializers.ValidationError({"trade_date": "该模式必须提供 trade_date"})
        if mode == self.MODE_GENERAL and not attrs.get("universe_id"):
            raise serializers.ValidationError({"universe_id": "general 模式必须提供 universe_id"})
        if mode == self.MODE_PORTFOLIO_SCOPED and not attrs.get("portfolio_id"):
            raise serializers.ValidationError(
                {"portfolio_id": "portfolio_scoped 模式必须提供 portfolio_id"}
            )
        return attrs


class QlibDataRefreshTriggerSerializer(serializers.Serializer):
    """Trigger serializer for Qlib runtime data refresh actions."""

    MODE_UNIVERSES = "universes"
    MODE_SCOPED_CODES = "scoped_codes"

    mode = serializers.ChoiceField(choices=[MODE_UNIVERSES, MODE_SCOPED_CODES])
    target_date = serializers.DateField(help_text="目标日期")
    lookback_days = serializers.IntegerField(default=400, min_value=1, max_value=2000)
    universes = serializers.JSONField(required=False)
    portfolio_ids = serializers.JSONField(required=False)
    all_active_portfolios = serializers.BooleanField(required=False, default=False)
    pool_mode = serializers.ChoiceField(
        required=False,
        choices=_ALPHA_POOL_MODE_VALUES,
        default="price_covered",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        mode = attrs["mode"]

        raw_universes = attrs.get("universes")
        if isinstance(raw_universes, str):
            attrs["universes"] = [item.strip() for item in raw_universes.split(",") if item.strip()]
        elif isinstance(raw_universes, list):
            attrs["universes"] = [str(item).strip() for item in raw_universes if str(item).strip()]
        elif raw_universes is None:
            attrs["universes"] = []
        else:
            raise serializers.ValidationError({"universes": "universes 必须是数组或逗号分隔字符串"})

        raw_portfolio_ids = attrs.get("portfolio_ids")
        if isinstance(raw_portfolio_ids, str):
            attrs["portfolio_ids"] = [
                int(item.strip()) for item in raw_portfolio_ids.split(",") if item.strip()
            ]
        elif isinstance(raw_portfolio_ids, list):
            attrs["portfolio_ids"] = [int(item) for item in raw_portfolio_ids]
        elif raw_portfolio_ids in (None, ""):
            attrs["portfolio_ids"] = []
        else:
            raise serializers.ValidationError(
                {"portfolio_ids": "portfolio_ids 必须是数组或逗号分隔字符串"}
            )

        if mode == self.MODE_UNIVERSES and not attrs["universes"]:
            raise serializers.ValidationError({"universes": "universes 模式必须提供 universes"})
        if mode == self.MODE_SCOPED_CODES and not (
            attrs.get("all_active_portfolios") or attrs["portfolio_ids"]
        ):
            raise serializers.ValidationError(
                {
                    "portfolio_ids": "scoped_codes 模式必须提供 portfolio_ids 或 all_active_portfolios=1"
                }
            )
        return attrs
