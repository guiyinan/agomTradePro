"""
板块分析模块 - API 序列化器

遵循项目架构约束：
- 使用 DRF Serializer
- 只做输入验证和输出格式化
"""

from rest_framework import serializers
from datetime import date

from ..application.use_cases import (
    AnalyzeSectorRotationRequest,
    SectorRotationResult
)
from ..domain.entities import SectorScore


class SectorScoreSerializer(serializers.Serializer):
    """板块评分序列化器"""
    rank = serializers.IntegerField()
    sector_code = serializers.CharField(max_length=10)
    sector_name = serializers.CharField(max_length=50)
    total_score = serializers.FloatField()
    momentum_score = serializers.FloatField()
    relative_strength_score = serializers.FloatField()
    regime_fit_score = serializers.FloatField()


class AnalyzeSectorRotationRequestSerializer(serializers.Serializer):
    """分析板块轮动请求序列化器"""
    regime = serializers.CharField(
        max_length=20,
        required=False,
        allow_null=True,
        help_text="Regime 名称（Recovery/Overheat/Stagflation/Deflation），不填则自动获取最新"
    )
    lookback_days = serializers.IntegerField(
        default=20,
        min_value=5,
        max_value=120,
        help_text="回看天数"
    )
    momentum_weight = serializers.FloatField(
        default=0.3,
        min_value=0.0,
        max_value=1.0,
        help_text="动量评分权重"
    )
    rs_weight = serializers.FloatField(
        default=0.4,
        min_value=0.0,
        max_value=1.0,
        help_text="相对强弱评分权重"
    )
    regime_weight = serializers.FloatField(
        default=0.3,
        min_value=0.0,
        max_value=1.0,
        help_text="Regime 适配度权重"
    )
    level = serializers.ChoiceField(
        choices=['SW1', 'SW2', 'SW3'],
        default='SW1',
        help_text="板块级别"
    )
    top_n = serializers.IntegerField(
        default=10,
        min_value=1,
        max_value=50,
        help_text="返回前 N 个板块"
    )

    def validate(self, data):
        """验证权重总和为 1"""
        momentum_weight = data.get('momentum_weight', 0.3)
        rs_weight = data.get('rs_weight', 0.4)
        regime_weight = data.get('regime_weight', 0.3)

        total_weight = momentum_weight + rs_weight + regime_weight
        if abs(total_weight - 1.0) > 0.01:
            raise serializers.ValidationError(
                f"权重总和必须为 1.0，当前为 {total_weight}"
            )

        return data

    def to_use_case_request(self) -> AnalyzeSectorRotationRequest:
        """转换为用例请求对象"""
        return AnalyzeSectorRotationRequest(
            regime=self.validated_data.get('regime'),
            lookback_days=self.validated_data.get('lookback_days', 20),
            momentum_weight=self.validated_data.get('momentum_weight', 0.3),
            rs_weight=self.validated_data.get('rs_weight', 0.4),
            regime_weight=self.validated_data.get('regime_weight', 0.3),
            level=self.validated_data.get('level', 'SW1'),
            top_n=self.validated_data.get('top_n', 10)
        )


class SectorRotationResultSerializer(serializers.Serializer):
    """板块轮动分析结果序列化器"""
    success = serializers.BooleanField()
    regime = serializers.CharField(max_length=20, allow_null=True)
    analysis_date = serializers.DateField()
    top_sectors = SectorScoreSerializer(many=True)
    error = serializers.CharField(allow_null=True, required=False)
    status = serializers.CharField(max_length=20, required=False)
    data_source = serializers.CharField(max_length=20, required=False)
    warning_message = serializers.CharField(allow_null=True, required=False)


class UpdateSectorDataRequestSerializer(serializers.Serializer):
    """更新板块数据请求序列化器"""
    level = serializers.ChoiceField(
        choices=['SW1', 'SW2', 'SW3'],
        default='SW1',
        help_text="板块级别"
    )
    start_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="开始日期"
    )
    end_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="结束日期"
    )
    force_update = serializers.BooleanField(
        default=False,
        help_text="是否强制更新"
    )
