"""
资产分析模块 - Interface 层序列化器

使用 Django REST Framework 定义 API 的输入输出序列化器。
"""

from rest_framework import serializers


class ScreenRequestSerializer(serializers.Serializer):
    """
    多维度筛选请求序列化器
    """
    asset_type = serializers.ChoiceField(
        choices=["fund", "equity", "bond", "commodity", "index", "sector"],
        required=True,
        help_text="资产类型"
    )

    filters = serializers.DictField(
        required=False,
        default={},
        help_text="过滤条件"
    )

    weights = serializers.DictField(
        required=False,
        default=None,
        help_text="自定义权重（可选）"
    )

    max_count = serializers.IntegerField(
        required=False,
        default=30,
        min_value=1,
        max_value=100,
        help_text="最大返回数量"
    )

    def validate_weights(self, value):
        """验证权重配置"""
        if value is None:
            return value

        # 检查权重总和
        total = sum(value.values())
        if abs(total - 1.0) > 0.01:
            raise serializers.ValidationError(f"权重总和必须为1.0，当前为 {total:.4f}")

        # 检查权重键名
        valid_keys = {"regime", "policy", "sentiment", "signal"}
        if not set(value.keys()).issubset(valid_keys):
            raise serializers.ValidationError(f"权重键名必须是 {valid_keys} 的子集")

        return value


class AssetScoreSerializer(serializers.Serializer):
    """
    资产评分序列化器
    """
    asset_code = serializers.CharField(help_text="资产代码")
    asset_name = serializers.CharField(help_text="资产名称")
    asset_type = serializers.CharField(help_text="资产类型")
    style = serializers.CharField(required=False, allow_null=True, help_text="风格")
    size = serializers.CharField(required=False, allow_null=True, help_text="规模")
    sector = serializers.CharField(required=False, allow_null=True, help_text="行业")

    regime_score = serializers.FloatField(help_text="Regime 得分")
    policy_score = serializers.FloatField(help_text="Policy 得分")
    sentiment_score = serializers.FloatField(help_text="Sentiment 得分")
    signal_score = serializers.FloatField(help_text="Signal 得分")
    custom_scores = serializers.DictField(required=False, default={}, help_text="自定义得分")

    total_score = serializers.FloatField(help_text="综合得分")
    rank = serializers.IntegerField(help_text="排名")

    allocation = serializers.CharField(help_text="推荐比例")
    risk_level = serializers.CharField(help_text="风险等级")


class ScreenResponseSerializer(serializers.Serializer):
    """
    多维度筛选响应序列化器
    """
    success = serializers.BooleanField(help_text="是否成功")
    timestamp = serializers.CharField(help_text="时间戳")
    context = serializers.DictField(help_text="评分上下文")
    weights = serializers.DictField(help_text="使用的权重")
    assets = AssetScoreSerializer(many=True, help_text="资产评分列表")
    message = serializers.CharField(required=False, allow_null=True, help_text="消息")


class WeightConfigSerializer(serializers.Serializer):
    """
    权重配置序列化器
    """
    name = serializers.CharField(help_text="配置名称")
    description = serializers.CharField(required=False, allow_null=True, help_text="描述")
    weights = serializers.DictField(help_text="权重配置")
    asset_type = serializers.CharField(required=False, allow_null=True, help_text="资产类型")
    market_condition = serializers.CharField(required=False, allow_null=True, help_text="市场状态")
    is_active = serializers.BooleanField(help_text="是否激活")
    priority = serializers.IntegerField(help_text="优先级")


class WeightConfigsResponseSerializer(serializers.Serializer):
    """
    权重配置列表响应序列化器
    """
    configs = serializers.DictField(
        child=WeightConfigSerializer(),
        help_text="配置字典（键为配置名）"
    )
    active = serializers.CharField(required=False, allow_null=True, help_text="当前激活的配置")


class ScoreContextSerializer(serializers.Serializer):
    """
    评分上下文序列化器
    """
    current_regime = serializers.ChoiceField(
        choices=["Recovery", "Overheat", "Stagflation", "Deflation"],
        required=True,
        help_text="当前 Regime"
    )

    policy_level = serializers.ChoiceField(
        choices=["P0", "P1", "P2", "P3"],
        required=True,
        help_text="政策档位"
    )

    sentiment_index = serializers.FloatField(
        required=True,
        min_value=-3.0,
        max_value=3.0,
        help_text="情绪指数"
    )

    score_date = serializers.DateField(required=False, help_text="评分日期")
