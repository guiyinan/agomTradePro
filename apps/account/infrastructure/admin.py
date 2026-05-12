"""
Django Admin 配置
"""
import csv
import json

from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.html import format_html

from .models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CapitalFlowModel,
    CurrencyModel,
    DocumentationModel,
    ExchangeRateModel,
    MacroSizingConfigModel,
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    SystemSettingsModel,
    TakeProfitConfigModel,
    TransactionModel,
    UserProfile,
)


@admin.register(DocumentationModel)
class DocumentationAdmin(admin.ModelAdmin):
    """文档管理后台"""

    list_display = ['title', 'category_display', 'slug', 'order', 'is_published', 'updated_at']
    list_filter = ['category', 'is_published', 'created_at', 'updated_at']
    search_fields = ['title', 'slug', 'content', 'summary']
    list_editable = ['order', 'is_published']
    ordering = ['category', 'order', '-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('title', 'slug', 'category')
        }),
        ('内容', {
            'fields': ('summary', 'content')
        }),
        ('设置', {
            'fields': ('order', 'is_published')
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    prepopulated_fields = {'slug': ('title',)}

    actions = ['export_selected_as_json', 'export_selected_as_csv', 'bulk_publish', 'bulk_unpublish']

    def category_display(self, obj):
        """显示分类中文名称"""
        return obj.get_category_display()
    category_display.short_description = '分类'
    category_display.admin_order_field = 'category'

    def export_selected_as_json(self, request, queryset):
        """导出选中文档为 JSON"""
        data = []
        for doc in queryset:
            data.append({
                'title': doc.title,
                'slug': doc.slug,
                'category': doc.category,
                'content': doc.content,
                'summary': doc.summary,
                'order': doc.order,
                'is_published': doc.is_published,
            })

        response = HttpResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename=docs_export_{len(queryset)}.json'
        return response
    export_selected_as_json.short_description = '导出选中文档为 JSON'

    def export_selected_as_csv(self, request, queryset):
        """导出选中文档为 CSV"""
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['标题', 'Slug', '分类', '摘要', '排序', '是否发布', '内容'])

        for doc in queryset:
            writer.writerow([
                doc.title,
                doc.slug,
                doc.get_category_display(),
                doc.summary,
                doc.order,
                doc.is_published,
                doc.content.replace('\n', '\\n'),
            ])

        response = HttpResponse(
            output.getvalue().encode('utf-8-sig'),
            content_type='text/csv; charset=utf-8'
        )
        response['Content-Disposition'] = f'attachment; filename=docs_export_{len(queryset)}.csv'
        return response
    export_selected_as_csv.short_description = '导出选中文档为 CSV'

    def bulk_publish(self, request, queryset):
        """批量发布"""
        updated = queryset.update(is_published=True)
        self.message_user(request, f'成功发布 {updated} 篇文档', messages.SUCCESS)
    bulk_publish.short_description = '批量发布'

    def bulk_unpublish(self, request, queryset):
        """批量取消发布"""
        updated = queryset.update(is_published=False)
        self.message_user(request, f'成功取消发布 {updated} 篇文档', messages.SUCCESS)
    bulk_unpublish.short_description = '批量取消发布'

    def response_add(self, request, obj, post_url_continue=None):
        """添加后返回文档管理页面"""
        return redirect('/admin/docs/manage/')

    def response_change(self, request, obj):
        """修改后返回文档管理页面"""
        return redirect('/admin/docs/manage/')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """用户资料管理"""

    list_display = ['user', 'display_name', 'phone', 'is_verified', 'created_at']
    list_filter = ['is_verified', 'created_at']
    search_fields = ['user__username', 'display_name', 'phone', 'bio']
    readonly_fields = ['user', 'created_at', 'updated_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'display_name', 'phone')
        }),
        ('个人信息', {
            'fields': ('bio', 'avatar_url')
        }),
        ('设置', {
            'fields': ('is_verified', 'preferences')
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================================
# 资产分类管理
# ============================================================

@admin.register(CurrencyModel)
class CurrencyAdmin(admin.ModelAdmin):
    """币种管理"""

    list_display = ['code', 'name', 'symbol', 'is_base', 'is_active', 'precision']
    list_filter = ['is_base', 'is_active']
    search_fields = ['code', 'name']
    list_editable = ['is_base', 'is_active', 'precision']
    ordering = ['-is_base', 'code']

    fieldsets = (
        ('基本信息', {
            'fields': ('code', 'name', 'symbol')
        }),
        ('设置', {
            'fields': ('is_base', 'is_active', 'precision')
        }),
    )


@admin.register(AssetCategoryModel)
class AssetCategoryAdmin(admin.ModelAdmin):
    """资产分类管理"""

    list_display = ['code', 'name', 'parent', 'level', 'path', 'is_active', 'sort_order']
    list_filter = ['level', 'is_active']
    search_fields = ['code', 'name', 'path']
    list_editable = ['is_active', 'sort_order']
    ordering = ['level', 'sort_order']

    fieldsets = (
        ('基本信息', {
            'fields': ('code', 'name', 'parent')
        }),
        ('层级信息', {
            'fields': ('level', 'path', 'sort_order')
        }),
        ('设置', {
            'fields': ('is_active',)
        }),
        ('描述', {
            'fields': ('description',)
        }),
    )

    readonly_fields = ['level', 'path']


@admin.register(ExchangeRateModel)
class ExchangeRateAdmin(admin.ModelAdmin):
    """汇率管理"""

    list_display = ['from_currency', 'to_currency', 'rate', 'effective_date', 'created_at']
    list_filter = ['from_currency', 'to_currency', 'effective_date']
    search_fields = ['from_currency__code', 'to_currency__code']
    date_hierarchy = 'effective_date'
    ordering = ['-effective_date']

    fieldsets = (
        ('汇率信息', {
            'fields': ('from_currency', 'to_currency', 'rate', 'effective_date')
        }),
    )

    readonly_fields = ['created_at']


# ============================================================
# 账户管理
# ============================================================

@admin.register(AccountProfileModel)
class AccountProfileAdmin(admin.ModelAdmin):
    """账户配置管理"""

    list_display = ['user', 'display_name', 'initial_capital', 'risk_tolerance', 'created_at']
    list_filter = ['risk_tolerance', 'created_at']
    search_fields = ['user__username', 'display_name']
    readonly_fields = ['user', 'created_at', 'updated_at']


@admin.register(PortfolioModel)
class PortfolioAdmin(admin.ModelAdmin):
    """投资组合管理"""

    list_display = ['user', 'name', 'base_currency', 'is_active', 'total_value_display', 'total_pnl_pct_display', 'position_count_display', 'created_at']
    list_filter = ['is_active', 'base_currency', 'created_at']
    search_fields = ['user__username', 'name']
    list_editable = ['is_active']
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'name', 'base_currency')
        }),
        ('设置', {
            'fields': ('is_active',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def total_value_display(self, obj):
        return f'{obj.total_value:,.2f}'
    total_value_display.short_description = '总市值'

    def total_pnl_pct_display(self, obj):
        color = 'green' if obj.total_pnl_pct >= 0 else 'red'
        return format_html('<span style="color:{}">{:.2f}%</span>', color, obj.total_pnl_pct)
    total_pnl_pct_display.short_description = '收益率'

    def position_count_display(self, obj):
        return obj.position_count
    position_count_display.short_description = '持仓数'


@admin.register(PositionModel)
class PositionAdmin(admin.ModelAdmin):
    """持仓管理"""

    list_display = ['portfolio', 'asset_code', 'category', 'currency', 'shares', 'avg_cost', 'current_price', 'market_value', 'unrealized_pnl_pct', 'is_closed', 'opened_at']
    list_filter = ['category', 'currency', 'is_closed', 'asset_class', 'region', 'opened_at']
    search_fields = ['asset_code', 'portfolio__name']
    list_editable = ['is_closed', 'current_price']
    ordering = ['-opened_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('portfolio', 'asset_code', 'category', 'currency')
        }),
        ('分类信息', {
            'fields': ('asset_class', 'region', 'cross_border')
        }),
        ('持仓信息', {
            'fields': ('shares', 'avg_cost', 'current_price')
        }),
        ('状态', {
            'fields': ('is_closed', 'opened_at', 'closed_at')
        }),
        ('来源', {
            'fields': ('source', 'source_id')
        }),
    )

    readonly_fields = ['opened_at', 'created_at', 'updated_at']


@admin.register(TransactionModel)
class TransactionAdmin(admin.ModelAdmin):
    """交易记录管理"""

    list_display = ['portfolio', 'asset_code', 'action', 'shares', 'price', 'notional', 'traded_at', 'created_at']
    list_filter = ['action', 'traded_at', 'created_at']
    search_fields = ['asset_code', 'portfolio__name']
    date_hierarchy = 'traded_at'
    ordering = ['-traded_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('portfolio', 'position', 'asset_code', 'action')
        }),
        ('交易信息', {
            'fields': ('shares', 'price', 'notional', 'commission')
        }),
        ('其他', {
            'fields': ('traded_at', 'notes')
        }),
    )

    readonly_fields = ['created_at']


@admin.register(CapitalFlowModel)
class CapitalFlowAdmin(admin.ModelAdmin):
    """资金流水管理"""

    list_display = ['portfolio', 'flow_type_display', 'amount', 'flow_date', 'created_at']
    list_filter = ['flow_type', 'flow_date', 'created_at']
    search_fields = ['portfolio__name', 'notes']
    date_hierarchy = 'flow_date'
    ordering = ['-flow_date']

    fieldsets = (
        ('基本信息', {
            'fields': ('portfolio', 'flow_type', 'amount')
        }),
        ('其他', {
            'fields': ('flow_date', 'notes')
        }),
    )

    readonly_fields = ['created_at']

    def flow_type_display(self, obj):
        colors = {'deposit': 'green', 'withdrawal': 'red'}
        color = colors.get(obj.flow_type, 'black')
        return format_html('<span style="color:{}">{}</span>', color, obj.get_flow_type_display())
    flow_type_display.short_description = '类型'


@admin.register(AssetMetadataModel)
class AssetMetadataAdmin(admin.ModelAdmin):
    """资产元数据管理"""

    list_display = ['asset_code', 'name', 'asset_class', 'region', 'cross_border', 'style', 'sector', 'created_at']
    list_filter = ['asset_class', 'region', 'cross_border', 'style', 'sector']
    search_fields = ['asset_code', 'name', 'description']
    ordering = ['asset_code']

    fieldsets = (
        ('基本信息', {
            'fields': ('asset_code', 'name', 'description')
        }),
        ('分类信息', {
            'fields': ('asset_class', 'region', 'cross_border')
        }),
        ('详细分类', {
            'fields': ('style', 'sector', 'sub_class')
        }),
    )

    readonly_fields = ['created_at', 'updated_at']


# ============================================================
# Phase 6: 风控体系 - 止损止盈管理
# ============================================================

@admin.register(StopLossConfigModel)
class StopLossConfigAdmin(admin.ModelAdmin):
    """止损配置管理"""

    list_display = ['position', 'stop_loss_type', 'stop_loss_pct_display', 'status', 'highest_price', 'triggered_at']
    list_filter = ['stop_loss_type', 'status', 'activated_at', 'triggered_at']
    search_fields = ['position__asset_code', 'position__portfolio__name']
    list_editable = ['status']
    ordering = ['-activated_at']

    fieldsets = (
        ('关联持仓', {
            'fields': ('position',)
        }),
        ('止损配置', {
            'fields': ('stop_loss_type', 'stop_loss_pct', 'trailing_stop_pct', 'max_holding_days')
        }),
        ('移动止损', {
            'fields': ('highest_price', 'highest_price_updated_at'),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('status', 'activated_at', 'triggered_at')
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    readonly_fields = ['activated_at', 'triggered_at', 'highest_price_updated_at']

    def stop_loss_pct_display(self, obj):
        color = 'red' if obj.stop_loss_pct < 0 else 'green'
        return format_html('<span style="color:{}">{:.2f}%</span>', color, obj.stop_loss_pct * 100)
    stop_loss_pct_display.short_description = '止损比例'


@admin.register(StopLossTriggerModel)
class StopLossTriggerAdmin(admin.ModelAdmin):
    """止损触发记录管理"""

    list_display = ['position', 'trigger_type', 'trigger_price', 'trigger_time', 'pnl', 'pnl_pct_display']
    list_filter = ['trigger_type', 'trigger_time']
    search_fields = ['position__asset_code', 'trigger_reason']
    date_hierarchy = 'trigger_time'
    ordering = ['-trigger_time']

    fieldsets = (
        ('关联持仓', {
            'fields': ('position',)
        }),
        ('触发信息', {
            'fields': ('trigger_type', 'trigger_price', 'trigger_time', 'trigger_reason')
        }),
        ('盈亏', {
            'fields': ('pnl', 'pnl_pct')
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    readonly_fields = ['trigger_time']

    def pnl_pct_display(self, obj):
        color = 'green' if obj.pnl_pct >= 0 else 'red'
        return format_html('<span style="color:{}">{:.2f}%</span>', color, obj.pnl_pct * 100)
    pnl_pct_display.short_description = '盈亏比例'


@admin.register(TakeProfitConfigModel)
class TakeProfitConfigAdmin(admin.ModelAdmin):
    """止盈配置管理"""

    list_display = ['position', 'take_profit_pct_display', 'partial_profit_levels_display', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['position__asset_code', 'position__portfolio__name']
    list_editable = ['is_active']
    ordering = ['-created_at']

    fieldsets = (
        ('关联持仓', {
            'fields': ('position',)
        }),
        ('止盈配置', {
            'fields': ('take_profit_pct', 'partial_profit_levels')
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('备注', {
            'fields': ('notes',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def take_profit_pct_display(self, obj):
        color = 'green'
        return format_html('<span style="color:{}">{:.2f}%</span>', color, obj.take_profit_pct * 100)
    take_profit_pct_display.short_description = '止盈比例'

    def partial_profit_levels_display(self, obj):
        if obj.partial_profit_levels:
            levels = ', '.join(f'{p:.1%}' for p in obj.partial_profit_levels)
            return levels
        return '全部止盈'
    partial_profit_levels_display.short_description = '分批止盈点位'


# ============================================================
# 系统配置管理
# ============================================================

@admin.register(SystemSettingsModel)
class SystemSettingsAdmin(admin.ModelAdmin):
    """系统配置管理（单例模式）"""

    list_display = ['require_user_approval_display', 'auto_approve_first_admin', 'qlib_status', 'updated_at']
    list_display_links = None  # 禁止从列表页进入编辑

    fieldsets = (
        ('用户审批配置', {
            'fields': ('require_user_approval', 'auto_approve_first_admin', 'default_mcp_enabled', 'allow_token_plaintext_view')
        }),
        ('协议内容', {
            'fields': ('user_agreement_content', 'risk_warning_content')
        }),
        ('Qlib 量化配置', {
            'fields': ('qlib_enabled', 'qlib_provider_uri', 'qlib_region', 'qlib_model_path'),
            'description': '配置 Qlib 量化分析数据目录。启用后可进行量化策略训练和预测。'
        }),
        ('其他', {
            'fields': ('notes',)
        }),
        ('元数据', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def has_add_permission(self, request):
        # 禁止添加新记录（单例模式）
        return False

    def has_delete_permission(self, request, obj=None):
        # 禁止删除配置记录
        return False

    def require_user_approval_display(self, obj):
        status = '开启' if obj.require_user_approval else '关闭'
        color = 'green' if obj.require_user_approval else 'orange'
        return format_html('<span style="color:{}">{}</span>', color, status)
    require_user_approval_display.short_description = '审批开关'

    def qlib_status(self, obj):
        if not obj.qlib_enabled:
            return format_html('<span style="color:gray">未启用</span>')
        if obj.is_qlib_configured():
            return format_html('<span style="color:green">已配置 ✓</span>')
        return format_html('<span style="color:red">数据目录不存在</span>')
    qlib_status.short_description = 'Qlib 状态'

    def response_add(self, request, obj, post_url_continue=None):
        """保存后重定向到列表页"""
        self.message_user(request, '系统配置已更新', messages.SUCCESS)
        return redirect('/admin/account/systemsettingsmodel/')

    def response_change(self, request, obj):
        """保存后重定向到列表页"""
        self.message_user(request, '系统配置已更新', messages.SUCCESS)
        return redirect('/admin/account/systemsettingsmodel/')


@admin.register(MacroSizingConfigModel)
class MacroSizingConfigAdmin(admin.ModelAdmin):
    """宏观仓位系数配置管理。"""

    list_display = ["version", "is_active", "warning_factor", "description", "created_at"]
    list_filter = ["is_active", "version", "created_at"]
    readonly_fields = [
        "regime_tiers_json",
        "pulse_tiers_json",
        "drawdown_tiers_json",
        "created_at",
        "updated_at",
    ]
    ordering = ["-version"]
