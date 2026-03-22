"""
Alpha Serializers

Django REST Framework 序列化器定义。
"""

from datetime import date
from typing import Any, Dict

from rest_framework import serializers

from ..domain.entities import StockScore, AlphaResult


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

    def create(self, validated_data: Dict[str, Any]) -> StockScore:
        """从验证数据创建 StockScore"""
        return StockScore(**validated_data)

    def to_representation(self, instance: StockScore) -> Dict[str, Any]:
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

    def create(self, validated_data: Dict[str, Any]) -> AlphaResult:
        """从验证数据创建 AlphaResult"""
        stocks_data = validated_data.pop("stocks", [])
        stocks = [StockScore(**s) for s in stocks_data]

        return AlphaResult(stocks=stocks, **validated_data)

    def to_representation(self, instance: AlphaResult) -> Dict[str, Any]:
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
