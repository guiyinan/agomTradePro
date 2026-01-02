"""
Serializers for Audit API.
"""

from rest_framework import serializers


class LossAnalysisSerializer(serializers.Serializer):
    """损失分析序列化器"""
    id = serializers.IntegerField()
    loss_source = serializers.CharField()
    loss_source_display = serializers.CharField()
    impact = serializers.FloatField()
    impact_percentage = serializers.FloatField()
    description = serializers.CharField()
    improvement_suggestion = serializers.CharField(allow_blank=True)


class ExperienceSummarySerializer(serializers.Serializer):
    """经验总结序列化器"""
    id = serializers.IntegerField()
    lesson = serializers.CharField()
    recommendation = serializers.CharField()
    priority = serializers.CharField()
    is_applied = serializers.BooleanField()
    applied_at = serializers.CharField(allow_null=True)


class AttributionReportSerializer(serializers.Serializer):
    """归因报告序列化器"""
    id = serializers.IntegerField()
    backtest_id = serializers.IntegerField()
    period_start = serializers.CharField()
    period_end = serializers.CharField()
    regime_timing_pnl = serializers.FloatField()
    asset_selection_pnl = serializers.FloatField()
    interaction_pnl = serializers.FloatField()
    total_pnl = serializers.FloatField()
    regime_accuracy = serializers.FloatField()
    regime_predicted = serializers.CharField()
    regime_actual = serializers.CharField(allow_null=True)
    created_at = serializers.CharField()

    # 关联数据
    loss_analyses = LossAnalysisSerializer(many=True, required=False)
    experience_summaries = ExperienceSummarySerializer(many=True, required=False)


class GenerateAttributionReportRequestSerializer(serializers.Serializer):
    """生成归因报告请求序列化器"""
    backtest_id = serializers.IntegerField(required=True)


class GenerateAttributionReportResponseSerializer(serializers.Serializer):
    """生成归因报告响应序列化器"""
    success = serializers.BooleanField()
    report_id = serializers.IntegerField(allow_null=True)
    error = serializers.CharField(allow_null=True, required=False)
