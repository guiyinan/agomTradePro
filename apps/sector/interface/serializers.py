"""
板块分析模块 - API 序列化器

遵循项目架构约束：
- 使用 DRF Serializer
- 只做输入验证和输出格式化
"""

import math
from collections.abc import Mapping
from datetime import date
from typing import Any, cast

from rest_framework import serializers

from apps.regime.domain.services_v2 import RegimeType

from ..application.use_cases import AnalyzeSectorRotationRequest
from ..domain.services import validate_rotation_weights


class StrictFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject fields outside the published Sector API contract."""

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


class FiniteWeightField(serializers.FloatField):
    """Weight field that rejects booleans, NaN, and infinities."""

    def to_internal_value(self, data: Any) -> float:
        """Return one finite weight in the configured field range."""

        if isinstance(data, bool):
            self.fail("invalid")
        value = super().to_internal_value(data)
        if not math.isfinite(value):
            raise serializers.ValidationError("A finite number is required.")
        return value


def _validate_date_range(data: dict[str, Any]) -> dict[str, Any]:
    """Reject update windows whose end precedes their start."""

    start_date = cast(date | None, data.get("start_date"))
    end_date = cast(date | None, data.get("end_date"))
    if start_date is not None and end_date is not None and start_date > end_date:
        raise serializers.ValidationError(
            {"end_date": ["Must be greater than or equal to start_date."]}
        )
    return data


class SectorScoreSerializer(serializers.Serializer[Any]):
    """板块评分序列化器"""

    rank = serializers.IntegerField()
    sector_code = serializers.CharField(max_length=10)
    sector_name = serializers.CharField(max_length=50)
    total_score = serializers.FloatField()
    momentum_score = serializers.FloatField()
    relative_strength_score = serializers.FloatField()
    regime_fit_score = serializers.FloatField()


class AnalyzeSectorRotationRequestSerializer(StrictFieldsSerializer):
    """分析板块轮动请求序列化器"""

    regime = serializers.ChoiceField(
        choices=[regime.value for regime in RegimeType],
        required=False,
        allow_null=True,
        help_text="Regime 名称（Recovery/Overheat/Stagflation/Deflation），不填则自动获取最新",
    )
    lookback_days = serializers.IntegerField(
        default=20, min_value=5, max_value=120, help_text="回看天数"
    )
    momentum_weight = FiniteWeightField(
        default=0.3, min_value=0.0, max_value=1.0, help_text="动量评分权重"
    )
    rs_weight = FiniteWeightField(
        default=0.4, min_value=0.0, max_value=1.0, help_text="相对强弱评分权重"
    )
    regime_weight = FiniteWeightField(
        default=0.3, min_value=0.0, max_value=1.0, help_text="Regime 适配度权重"
    )
    level = serializers.ChoiceField(
        choices=["SW1", "SW2", "SW3"], default="SW1", help_text="板块级别"
    )
    top_n = serializers.IntegerField(
        default=10, min_value=1, max_value=50, help_text="返回前 N 个板块"
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """验证权重总和为 1"""

        try:
            validate_rotation_weights(
                data.get("momentum_weight", 0.3),
                data.get("rs_weight", 0.4),
                data.get("regime_weight", 0.3),
            )
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        return data

    def to_use_case_request(self) -> AnalyzeSectorRotationRequest:
        """转换为用例请求对象"""
        return AnalyzeSectorRotationRequest(
            regime=self.validated_data.get("regime"),
            lookback_days=self.validated_data.get("lookback_days", 20),
            momentum_weight=self.validated_data.get("momentum_weight", 0.3),
            rs_weight=self.validated_data.get("rs_weight", 0.4),
            regime_weight=self.validated_data.get("regime_weight", 0.3),
            level=self.validated_data.get("level", "SW1"),
            top_n=self.validated_data.get("top_n", 10),
        )


class SectorRotationQuerySerializer(StrictFieldsSerializer):
    """Strict query contract for persisted sector rotation reads."""

    regime = serializers.ChoiceField(
        choices=[regime.value for regime in RegimeType],
        required=False,
        allow_null=True,
        help_text="Regime 名称；不填时读取最新持久化快照",
    )
    lookback_days = serializers.IntegerField(default=20, min_value=5, max_value=120)
    level = serializers.ChoiceField(choices=["SW1", "SW2", "SW3"], default="SW1")
    top_n = serializers.IntegerField(default=10, min_value=1, max_value=50)

    def to_use_case_request(self) -> AnalyzeSectorRotationRequest:
        """Convert validated query parameters into an application request."""

        return AnalyzeSectorRotationRequest(
            regime=self.validated_data.get("regime"),
            lookback_days=self.validated_data["lookback_days"],
            level=self.validated_data["level"],
            top_n=self.validated_data["top_n"],
        )


class SectorScoreQuerySerializer(StrictFieldsSerializer):
    """Validate one-sector score lookup parameters."""

    regime = serializers.ChoiceField(
        choices=[regime.value for regime in RegimeType],
        required=False,
        allow_null=True,
    )
    lookback_days = serializers.IntegerField(default=20, min_value=5, max_value=120)
    level = serializers.ChoiceField(choices=["SW1", "SW2", "SW3"], default="SW1")


class SectorRotationResultSerializer(serializers.Serializer[Any]):
    """板块轮动分析结果序列化器"""

    success = serializers.BooleanField()
    regime = serializers.CharField(max_length=20, allow_null=True)
    analysis_date = serializers.DateField()
    top_sectors = SectorScoreSerializer(many=True)
    error = serializers.CharField(allow_null=True, required=False)
    status = serializers.CharField(max_length=20, required=False)
    data_source = serializers.CharField(max_length=20, required=False)
    warning_message = serializers.CharField(allow_null=True, required=False)
    warning_detail = serializers.CharField(allow_null=True, required=False)
    error_code = serializers.CharField(allow_null=True, required=False)


class UpdateSectorDataRequestSerializer(StrictFieldsSerializer):
    """更新板块数据请求序列化器"""

    level = serializers.ChoiceField(
        choices=["SW1", "SW2", "SW3"],
        default="SW1",
        help_text="板块级别",
    )
    start_date = serializers.DateField(required=False, allow_null=True, help_text="开始日期")
    end_date = serializers.DateField(required=False, allow_null=True, help_text="结束日期")
    force_update = serializers.BooleanField(
        default=False,
        help_text="是否强制更新",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the optional provider update date window."""

        return _validate_date_range(data)
