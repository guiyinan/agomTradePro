"""
资产分析模块 - Interface 层序列化器

使用 Django REST Framework 定义 API 的输入输出序列化器。
"""

import math
from collections.abc import Mapping
from typing import Any, TypeAlias, cast

from rest_framework import serializers

JsonPayload: TypeAlias = dict[str, Any]


class StrictFieldsSerializer(serializers.Serializer[JsonPayload]):
    """Reject undeclared public request fields."""

    def to_internal_value(self, data: Any) -> JsonPayload:
        """Validate the public object shape before normal field parsing."""
        if not isinstance(data, Mapping):
            raise serializers.ValidationError({"non_field_errors": ["Expected an object."]})
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {field: ["Unknown field."] for field in unknown_fields}
            )
        return cast(JsonPayload, super().to_internal_value(data))


class FiniteFloatField(serializers.FloatField):
    """Float field that rejects booleans and non-finite values."""

    def to_internal_value(self, data: Any) -> float:
        if isinstance(data, bool):
            raise serializers.ValidationError("A finite number is required.")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("A finite number is required.")
        return value

    def to_representation(self, value: Any) -> str:
        result = super().to_representation(value)
        if not math.isfinite(float(result)):
            raise serializers.ValidationError("A finite number is required.")
        return result


class ScreenRequestSerializer(StrictFieldsSerializer):
    """多维度筛选请求序列化器。"""

    asset_type = serializers.ChoiceField(
        choices=["fund", "equity", "bond", "commodity", "index", "sector"],
        required=True,
        help_text="资产类型",
    )
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text="过滤条件",
    )
    weights = serializers.DictField(
        child=FiniteFloatField(min_value=0.0, max_value=1.0),
        required=False,
        allow_null=True,
        default=None,
        help_text="自定义权重（可选）",
    )
    max_count = serializers.IntegerField(
        required=False,
        default=30,
        min_value=1,
        max_value=100,
        help_text="最大返回数量",
    )
    regime = serializers.ChoiceField(
        choices=["Recovery", "Overheat", "Stagflation", "Deflation"],
        required=False,
        help_text="Regime 情景覆盖",
    )
    policy_level = serializers.ChoiceField(
        choices=["P0", "P1", "P2", "P3"],
        required=False,
        help_text="政策档位情景覆盖",
    )
    sentiment_index = FiniteFloatField(
        required=False,
        min_value=-3.0,
        max_value=3.0,
        help_text="情绪指数情景覆盖",
    )

    def validate_weights(
        self,
        value: dict[str, float] | None,
    ) -> dict[str, float] | None:
        """Validate the complete scoring weight vector."""
        if value is None:
            return None

        valid_keys = {"regime", "policy", "sentiment", "signal"}
        invalid_keys = sorted(set(value) - valid_keys)
        if invalid_keys:
            raise serializers.ValidationError(f"Unsupported weight keys: {', '.join(invalid_keys)}")
        if set(value) != valid_keys:
            missing_keys = sorted(valid_keys - set(value))
            raise serializers.ValidationError(f"Missing weight keys: {', '.join(missing_keys)}")

        total = math.fsum(value.values())
        if not math.isclose(total, 1.0, abs_tol=0.01):
            raise serializers.ValidationError(f"权重总和必须为1.0，当前为 {total:.4f}")
        return value


class AssetScoreBreakdownSerializer(serializers.Serializer[JsonPayload]):
    """Nested score breakdown emitted by AssetScoreDTO."""

    regime = FiniteFloatField(help_text="Regime 得分")
    policy = FiniteFloatField(help_text="Policy 得分")
    sentiment = FiniteFloatField(help_text="Sentiment 得分")
    signal = FiniteFloatField(help_text="Signal 得分")
    custom = serializers.DictField(
        child=FiniteFloatField(),
        required=False,
        default=dict,
        help_text="自定义得分",
    )
    total = FiniteFloatField(help_text="综合得分")


class AssetScoreSerializer(serializers.Serializer[JsonPayload]):
    """资产评分序列化器。"""

    asset_code = serializers.CharField(help_text="资产代码")
    asset_name = serializers.CharField(help_text="资产名称")
    asset_type = serializers.CharField(help_text="资产类型")
    style: Any = serializers.CharField(required=False, allow_null=True, help_text="风格")
    size = serializers.CharField(required=False, allow_null=True, help_text="规模")
    sector = serializers.CharField(required=False, allow_null=True, help_text="行业")
    scores = AssetScoreBreakdownSerializer(help_text="评分明细")
    total_score = FiniteFloatField(required=False, help_text="综合得分")
    rank = serializers.IntegerField(help_text="排名")
    allocation = serializers.CharField(help_text="推荐比例")
    risk_level = serializers.CharField(help_text="风险等级")


class ScreenResponseSerializer(serializers.Serializer[JsonPayload]):
    """多维度筛选响应序列化器。"""

    success = serializers.BooleanField(help_text="是否成功")
    timestamp = serializers.CharField(help_text="时间戳")
    context: Any = serializers.DictField(help_text="评分上下文")
    weights = serializers.DictField(
        child=FiniteFloatField(),
        help_text="使用的权重",
    )
    assets = AssetScoreSerializer(many=True, help_text="资产评分列表")
    message = serializers.CharField(required=False, allow_null=True, help_text="消息")


class WeightConfigSerializer(serializers.Serializer[JsonPayload]):
    """权重配置序列化器。"""

    name = serializers.CharField(help_text="配置名称")
    description = serializers.CharField(required=False, allow_null=True, help_text="描述")
    weights = serializers.DictField(
        child=FiniteFloatField(),
        help_text="权重配置",
    )
    asset_type = serializers.CharField(required=False, allow_null=True, help_text="资产类型")
    market_condition = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="市场状态",
    )
    is_active = serializers.BooleanField(help_text="是否激活")
    priority = serializers.IntegerField(help_text="优先级")


class WeightConfigsResponseSerializer(serializers.Serializer[JsonPayload]):
    """权重配置列表响应序列化器。"""

    configs = serializers.DictField(
        child=WeightConfigSerializer(),
        help_text="配置字典（键为配置名）",
    )
    active = serializers.CharField(required=False, allow_null=True, help_text="当前激活的配置")


class ScoreContextSerializer(serializers.Serializer[JsonPayload]):
    """评分上下文序列化器。"""

    current_regime = serializers.ChoiceField(
        choices=["Recovery", "Overheat", "Stagflation", "Deflation"],
        required=True,
        help_text="当前 Regime",
    )
    policy_level = serializers.ChoiceField(
        choices=["P0", "P1", "P2", "P3"],
        required=True,
        help_text="政策档位",
    )
    sentiment_index = FiniteFloatField(
        required=True,
        min_value=-3.0,
        max_value=3.0,
        help_text="情绪指数",
    )
    score_date = serializers.DateField(required=False, help_text="评分日期")
