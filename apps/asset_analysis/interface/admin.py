"""
资产分析模块 - Django Admin 配置
"""

from django.contrib import admin

from ..infrastructure.models import (
    AssetAnalysisAlert,
    AssetScoreCache,
    AssetScoringLog,
    WeightConfigModel,
)


@admin.register(WeightConfigModel)
class WeightConfigAdmin(admin.ModelAdmin):
    """权重配置管理"""
    list_display = ['name', 'asset_type', 'market_condition', 'is_active', 'priority', 'created_at']
    list_filter = ['asset_type', 'market_condition', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['-priority', '-created_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'is_active', 'priority')
        }),
        ('权重配置', {
            'fields': (
                'regime_weight',
                'policy_weight',
                'sentiment_weight',
                'signal_weight'
            )
        }),
        ('适用条件', {
            'fields': ('asset_type', 'market_condition')
        }),
        ('元信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AssetScoreCache)
class AssetScoreCacheAdmin(admin.ModelAdmin):
    """资产评分缓存管理"""
    list_display = ['asset_code', 'asset_name', 'asset_type', 'score_date', 'total_score', 'rank', 'created_at']
    list_filter = ['asset_type', 'score_date', 'risk_level']
    search_fields = ['asset_code', 'asset_name']
    ordering = ['-score_date', '-total_score']
    readonly_fields = ['created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('asset_type', 'asset_code', 'asset_name', 'score_date')
        }),
        ('评分上下文', {
            'fields': ('regime', 'policy_level', 'sentiment_index')
        }),
        ('维度得分', {
            'fields': (
                'regime_score',
                'policy_score',
                'sentiment_score',
                'signal_score',
                'total_score'
            )
        }),
        ('结果', {
            'fields': ('rank', 'allocation_percent', 'risk_level')
        }),
        ('自定义得分', {
            'fields': ('custom_scores',)
        }),
        ('元信息', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(AssetScoringLog)
class AssetScoringLogAdmin(admin.ModelAdmin):
    """评分日志管理"""
    list_display = ['id', 'asset_type', 'request_source', 'status', 'total_assets', 'filtered_assets', 'execution_time_ms', 'created_at']
    list_filter = ['asset_type', 'status', 'request_source']
    search_fields = ['request_source']
    ordering = ['-created_at']
    readonly_fields = ['created_at']

    fieldsets = (
        ('请求信息', {
            'fields': ('asset_type', 'request_source', 'user_id')
        }),
        ('评分上下文', {
            'fields': (
                'regime',
                'policy_level',
                'sentiment_index',
                'active_signals_count'
            )
        }),
        ('权重配置', {
            'fields': (
                'weight_config_name',
                'regime_weight',
                'policy_weight',
                'sentiment_weight',
                'signal_weight'
            )
        }),
        ('筛选条件', {
            'fields': ('filters',)
        }),
        ('结果统计', {
            'fields': (
                'total_assets',
                'scored_assets',
                'filtered_assets'
            )
        }),
        ('性能指标', {
            'fields': ('execution_time_ms', 'cache_hit')
        }),
        ('状态', {
            'fields': ('status', 'error_message')
        }),
        ('元信息', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        """禁止手动添加日志"""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止修改日志"""
        return False


@admin.register(AssetAnalysisAlert)
class AssetAnalysisAlertAdmin(admin.ModelAdmin):
    """告警管理"""
    list_display = ['id', 'severity', 'alert_type', 'title', 'asset_type', 'is_resolved', 'created_at']
    list_filter = ['severity', 'alert_type', 'is_resolved', 'asset_type']
    search_fields = ['title', 'message', 'asset_code']
    ordering = ['-created_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('告警信息', {
            'fields': ('severity', 'alert_type', 'title', 'message')
        }),
        ('关联信息', {
            'fields': ('asset_type', 'asset_code')
        }),
        ('详细信息', {
            'fields': ('context', 'stack_trace')
        }),
        ('解决状态', {
            'fields': (
                'is_resolved',
                'resolved_at',
                'resolved_by',
                'resolution_notes'
            )
        }),
        ('元信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_resolved']

    def mark_as_resolved(self, request, queryset):
        """批量标记为已解决"""
        from django.utils import timezone
        count = queryset.update(
            is_resolved=True,
            resolved_at=timezone.now(),
            resolved_by=request.user.id if request.user.is_authenticated else None
        )
        self.message_user(request, f'已标记 {count} 条告警为已解决')
    mark_as_resolved.short_description = '标记为已解决'
