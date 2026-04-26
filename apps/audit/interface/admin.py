"""
Django Admin for Audit.
"""

from django.contrib import admin

from apps.audit.models import (
    AttributionReport,
    AuditReport,
    ExperienceSummary,
    IndicatorPerformanceModel,
    IndicatorThresholdConfigModel,
    LossAnalysis,
    ValidationSummaryModel,
)


@admin.register(AuditReport)
class AuditReportAdmin(admin.ModelAdmin):
    """Admin interface for AuditReport"""

    list_display = [
        "period_start",
        "period_end",
        "total_pnl",
        "regime_timing_pnl",
        "asset_selection_pnl",
    ]
    list_filter = ["period_start", "period_end"]
    date_hierarchy = "period_start"
    readonly_fields = ["created_at"]


@admin.register(AttributionReport)
class AttributionReportAdmin(admin.ModelAdmin):
    """Admin interface for AttributionReport"""

    list_display = [
        "id",
        "backtest",
        "period_start",
        "period_end",
        "total_pnl",
        "regime_timing_pnl",
        "asset_selection_pnl",
        "regime_accuracy",
        "created_at",
    ]
    list_filter = ["period_start", "period_end", "regime_predicted", "created_at"]
    search_fields = ["backtest__strategy_name"]
    readonly_fields = [
        "regime_timing_pnl",
        "asset_selection_pnl",
        "interaction_pnl",
        "total_pnl",
        "regime_accuracy",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "period_start"


@admin.register(LossAnalysis)
class LossAnalysisAdmin(admin.ModelAdmin):
    """Admin interface for LossAnalysis"""

    list_display = ["report", "loss_source", "impact", "impact_percentage", "created_at"]
    list_filter = ["loss_source", "created_at"]
    search_fields = ["report__backtest__strategy_name", "description"]
    readonly_fields = ["impact_percentage", "created_at"]


@admin.register(ExperienceSummary)
class ExperienceSummaryAdmin(admin.ModelAdmin):
    """Admin interface for ExperienceSummary"""

    list_display = ["report", "priority", "is_applied", "applied_at", "created_at"]
    list_filter = ["priority", "is_applied", "applied_at", "created_at"]
    search_fields = ["lesson", "recommendation", "report__backtest__strategy_name"]
    readonly_fields = ["created_at"]


# ============ 指标表现评估相关 Admin ============


@admin.register(IndicatorThresholdConfigModel)
class IndicatorThresholdConfigModelAdmin(admin.ModelAdmin):
    """Admin interface for IndicatorThresholdConfigModel"""

    list_display = [
        "indicator_code",
        "indicator_name",
        "category",
        "level_low",
        "level_high",
        "base_weight",
        "is_active",
    ]
    list_filter = ["category", "is_active"]
    search_fields = ["indicator_code", "indicator_name", "description"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = (
        ("基本信息", {"fields": ("indicator_code", "indicator_name", "category", "description")}),
        ("阈值配置", {"fields": ("level_low", "level_high")}),
        ("权重配置", {"fields": ("base_weight", "min_weight", "max_weight")}),
        (
            "验证阈值",
            {
                "fields": (
                    "decay_threshold",
                    "decay_penalty",
                    "improvement_threshold",
                    "improvement_bonus",
                )
            },
        ),
        (
            "高级配置",
            {
                "fields": ("action_thresholds", "validation_periods", "is_active"),
                "classes": ("collapse",),
            },
        ),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(IndicatorPerformanceModel)
class IndicatorPerformanceModelAdmin(admin.ModelAdmin):
    """Admin interface for IndicatorPerformanceModel"""

    list_display = [
        "indicator_code",
        "evaluation_period_end",
        "f1_score",
        "stability_score",
        "recommended_action",
        "recommended_weight",
        "created_at",
    ]
    list_filter = ["indicator_code", "recommended_action", "evaluation_period_end"]
    search_fields = ["indicator_code"]
    readonly_fields = [
        "evaluation_period_start",
        "evaluation_period_end",
        "true_positive_count",
        "false_positive_count",
        "true_negative_count",
        "false_negative_count",
        "precision",
        "recall",
        "f1_score",
        "accuracy",
        "lead_time_mean",
        "lead_time_std",
        "pre_2015_correlation",
        "post_2015_correlation",
        "stability_score",
        "decay_rate",
        "signal_strength",
        "recommended_action",
        "recommended_weight",
        "confidence_level",
        "created_at",
    ]

    fieldsets = (
        (
            "基本信息",
            {"fields": ("indicator_code", "evaluation_period_start", "evaluation_period_end")},
        ),
        (
            "混淆矩阵",
            {
                "fields": (
                    "true_positive_count",
                    "false_positive_count",
                    "true_negative_count",
                    "false_negative_count",
                )
            },
        ),
        ("统计指标", {"fields": ("precision", "recall", "f1_score", "accuracy")}),
        ("领先时间", {"fields": ("lead_time_mean", "lead_time_std")}),
        (
            "稳定性分析",
            {"fields": ("pre_2015_correlation", "post_2015_correlation", "stability_score")},
        ),
        ("信号特征", {"fields": ("decay_rate", "signal_strength")}),
        ("建议", {"fields": ("recommended_action", "recommended_weight", "confidence_level")}),
        ("元数据", {"fields": ("created_at",)}),
    )


@admin.register(ValidationSummaryModel)
class ValidationSummaryModelAdmin(admin.ModelAdmin):
    """Admin interface for ValidationSummaryModel"""

    list_display = [
        "validation_run_id",
        "run_date",
        "total_indicators",
        "approved_indicators",
        "rejected_indicators",
        "pending_indicators",
        "avg_f1_score",
        "avg_stability_score",
        "status",
        "is_shadow_mode",
    ]
    list_filter = ["status", "is_shadow_mode", "run_date"]
    search_fields = ["validation_run_id", "overall_recommendation"]
    readonly_fields = [
        "validation_run_id",
        "run_date",
        "evaluation_period_start",
        "evaluation_period_end",
        "total_indicators",
        "approved_indicators",
        "rejected_indicators",
        "pending_indicators",
        "avg_f1_score",
        "avg_stability_score",
        "overall_recommendation",
        "status",
        "is_shadow_mode",
        "error_message",
    ]

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "validation_run_id",
                    "run_date",
                    "evaluation_period_start",
                    "evaluation_period_end",
                )
            },
        ),
        (
            "验证结果",
            {
                "fields": (
                    "total_indicators",
                    "approved_indicators",
                    "rejected_indicators",
                    "pending_indicators",
                )
            },
        ),
        ("统计摘要", {"fields": ("avg_f1_score", "avg_stability_score")}),
        ("总体建议", {"fields": ("overall_recommendation",)}),
        ("状态", {"fields": ("status", "is_shadow_mode", "error_message")}),
    )
