"""
Django Admin for Account Module.

提供 Account 模块所有模型的 Admin 管理界面。
"""
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, F, DecimalField
from decimal import Decimal

from ..infrastructure.models import (
    CurrencyModel,
    AssetCategoryModel,
    AccountProfileModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
    CapitalFlowModel,
    AssetMetadataModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
    SystemSettingsModel,
    DocumentationModel,
    ExchangeRateModel,
    InvestmentRuleModel,
    PortfolioDailySnapshotModel,
)


@admin.register(CurrencyModel)
class CurrencyModelAdmin(admin.ModelAdmin):
    """币种管理"""
    list_display = ['code', 'name', 'symbol', 'is_base', 'is_active', 'precision']
    list_filter = ['is_base', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['-is_base', 'code']


@admin.register(AssetCategoryModel)
class AssetCategoryModelAdmin(admin.ModelAdmin):
    """资产分类管理"""
    list_display = ['code', 'name', 'parent', 'level', 'path', 'is_active', 'sort_order']
    list_filter = ['level', 'is_active']
    search_fields = ['code', 'name', 'path']
    ordering = ['path', 'sort_order']


@admin.register(AccountProfileModel)
class AccountProfileModelAdmin(admin.ModelAdmin):
    """用户账户配置管理"""
    list_display = ['user', 'display_name', 'risk_tolerance', 'initial_capital', 'approval_status_badge', 'created_at']
    list_filter = ['risk_tolerance', 'approval_status', 'user_agreement_accepted']
    search_fields = ['user__username', 'display_name']
    readonly_fields = ['created_at', 'updated_at', 'agreement_accepted_at', 'agreement_ip_address']

    fieldsets = (
        ('基本信息', {
            'fields': ('user', 'display_name', 'initial_capital', 'risk_tolerance')
        }),
        ('波动率控制', {
            'fields': ('target_volatility', 'volatility_tolerance', 'max_volatility_reduction')
        }),
        ('协议确认', {
            'fields': ('user_agreement_accepted', 'risk_warning_acknowledged',
                      'agreement_accepted_at', 'agreement_ip_address')
        }),
        ('审批状态', {
            'fields': ('approval_status', 'approved_at', 'approved_by', 'rejection_reason')
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def approval_status_badge(self, obj):
        """审批状态标签"""
        colors = {
            'pending': '#ffc107',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'auto_approved': '#17a2b8',
        }
        color = colors.get(obj.approval_status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_approval_status_display()
        )
    approval_status_badge.short_description = '审批状态'


@admin.register(PortfolioModel)
class PortfolioModelAdmin(admin.ModelAdmin):
    """投资组合管理"""
    list_display = ['user', 'name', 'base_currency', 'is_active',
                    'total_value_display', 'total_pnl_pct_display', 'position_count']
    list_filter = ['is_active', 'base_currency']
    search_fields = ['user__username', 'name']
    readonly_fields = ['created_at', 'updated_at']

    def total_value_display(self, obj):
        """总市值显示"""
        return f'¥{obj.total_value:,.2f}' if obj.total_value else '¥0.00'
    total_value_display.short_description = '总市值'

    def total_pnl_pct_display(self, obj):
        """总盈亏百分比显示"""
        pct = obj.total_pnl_pct
        color = '#28a745' if pct >= 0 else '#dc3545'
        return format_html(
            '<span style="color: {};">{:+.2f}%</span>',
            color, pct
        )
    total_pnl_pct_display.short_description = '收益率'


@admin.register(PositionModel)
class PositionModelAdmin(admin.ModelAdmin):
    """持仓管理"""
    list_display = ['portfolio', 'asset_code', 'category', 'currency',
                    'shares', 'avg_cost', 'market_value', 'unrealized_pnl_pct_display',
                    'source', 'is_closed']
    list_filter = ['asset_class', 'region', 'cross_border', 'source', 'is_closed']
    search_fields = ['asset_code', 'portfolio__name']
    readonly_fields = ['created_at', 'updated_at', 'opened_at', 'closed_at']
    date_hierarchy = 'opened_at'

    def unrealized_pnl_pct_display(self, obj):
        """盈亏百分比显示"""
        pct = obj.unrealized_pnl_pct
        color = '#28a745' if pct >= 0 else '#dc3545'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:+.2f}%</span>',
            color, pct
        )
    unrealized_pnl_pct_display.short_description = '盈亏%'


@admin.register(TransactionModel)
class TransactionModelAdmin(admin.ModelAdmin):
    """交易记录管理"""
    list_display = ['portfolio', 'action_badge', 'asset_code', 'shares',
                    'price', 'notional', 'commission', 'traded_at']
    list_filter = ['action', 'traded_at']
    search_fields = ['asset_code', 'portfolio__name']
    readonly_fields = ['created_at']
    date_hierarchy = 'traded_at'

    def action_badge(self, obj):
        """交易方向标签"""
        color = '#28a745' if obj.action == 'buy' else '#dc3545'
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_action_display().upper()
        )
    action_badge.short_description = '方向'


@admin.register(CapitalFlowModel)
class CapitalFlowModelAdmin(admin.ModelAdmin):
    """资金流水管理"""
    list_display = ['user', 'portfolio', 'flow_type_badge', 'amount', 'flow_date']
    list_filter = ['flow_type', 'flow_date']
    search_fields = ['user__username']
    readonly_fields = ['created_at']
    date_hierarchy = 'flow_date'

    def flow_type_badge(self, obj):
        """流水类型标签"""
        colors = {
            'deposit': '#28a745',
            'withdraw': '#dc3545',
            'dividend': '#007bff',
            'interest': '#17a2b8',
            'adjustment': '#ffc107',
        }
        color = colors.get(obj.flow_type, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_flow_type_display()
        )
    flow_type_badge.short_description = '类型'


@admin.register(AssetMetadataModel)
class AssetMetadataModelAdmin(admin.ModelAdmin):
    """资产元数据管理"""
    list_display = ['asset_code', 'name', 'asset_class', 'region',
                    'cross_border', 'style', 'sector']
    list_filter = ['asset_class', 'region', 'cross_border', 'style']
    search_fields = ['asset_code', 'name', 'sector']


@admin.register(StopLossConfigModel)
class StopLossConfigModelAdmin(admin.ModelAdmin):
    """止损配置管理"""
    list_display = ['position', 'stop_loss_type', 'stop_loss_pct_display',
                    'status_badge', 'triggered_at']
    list_filter = ['stop_loss_type', 'status']
    readonly_fields = ['activated_at', 'triggered_at', 'highest_price_updated_at',
                       'created_at', 'updated_at']

    def stop_loss_pct_display(self, obj):
        """止损百分比显示"""
        return f'{obj.stop_loss_pct:.2%}'
    stop_loss_pct_display.short_description = '止损幅度'

    def status_badge(self, obj):
        """状态标签"""
        colors = {
            'active': '#28a745',
            'triggered': '#dc3545',
            'cancelled': '#6c757d',
            'expired': '#ffc107',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = '状态'


@admin.register(StopLossTriggerModel)
class StopLossTriggerModelAdmin(admin.ModelAdmin):
    """止损触发记录管理"""
    list_display = ['position', 'trigger_type', 'trigger_price',
                    'trigger_time', 'pnl_pct_display']
    list_filter = ['trigger_type']
    readonly_fields = ['trigger_time', 'created_at']
    date_hierarchy = 'trigger_time'

    def pnl_pct_display(self, obj):
        """盈亏百分比显示"""
        color = '#28a745' if obj.pnl_pct >= 0 else '#dc3545'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:+.2f}%</span>',
            color, obj.pnl_pct
        )
    pnl_pct_display.short_description = '盈亏%'


@admin.register(TakeProfitConfigModel)
class TakeProfitConfigModelAdmin(admin.ModelAdmin):
    """止盈配置管理"""
    list_display = ['position', 'take_profit_pct_display', 'is_active']
    readonly_fields = ['created_at', 'updated_at']

    def take_profit_pct_display(self, obj):
        """止盈百分比显示"""
        return f'+{obj.take_profit_pct:.2%}'
    take_profit_pct_display.short_description = '止盈幅度'


@admin.register(SystemSettingsModel)
class SystemSettingsModelAdmin(admin.ModelAdmin):
    """系统配置管理（单例模式）"""

    def has_add_permission(self, request):
        """禁止手动添加（单例模式）"""
        return not SystemSettingsModel._default_manager.exists()

    def has_delete_permission(self, request, obj=None):
        """禁止删除配置"""
        return False

    list_display = ['require_user_approval', 'auto_approve_first_admin']

    fieldsets = (
        ('用户审批', {
            'fields': ('require_user_approval', 'auto_approve_first_admin')
        }),
        ('协议内容', {
            'fields': ('user_agreement_content', 'risk_warning_content')
        }),
        ('备注', {
            'fields': ('notes',)
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']

    def changelist_view(self, request, extra_context=None):
        """自定义列表页（单例模式）"""
        if SystemSettingsModel._default_manager.exists():
            config = SystemSettingsModel._default_manager.first()
            return super().change_view(
                str(config.pk),
                extra_context=extra_context
            )
        return super().changelist_view(request, extra_context)


@admin.register(DocumentationModel)
class DocumentationModelAdmin(admin.ModelAdmin):
    """文档管理"""
    list_display = ['title', 'slug', 'category', 'order', 'is_published', 'created_at']
    list_filter = ['category', 'is_published']
    search_fields = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ExchangeRateModel)
class ExchangeRateModelAdmin(admin.ModelAdmin):
    """汇率管理"""
    list_display = ['from_currency', 'to_currency', 'rate', 'effective_date']
    list_filter = ['from_currency', 'to_currency']
    search_fields = ['from_currency__code', 'to_currency__code']
    date_hierarchy = 'effective_date'


@admin.register(InvestmentRuleModel)
class InvestmentRuleModelAdmin(admin.ModelAdmin):
    """投资规则管理"""
    list_display = ['name', 'rule_type', 'user', 'priority', 'is_active']
    list_filter = ['rule_type', 'is_active']
    search_fields = ['name', 'advice_template']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PortfolioDailySnapshotModel)
class PortfolioDailySnapshotModelAdmin(admin.ModelAdmin):
    """投资组合日快照管理"""
    list_display = ['portfolio', 'snapshot_date', 'total_value',
                    'cash_balance', 'invested_value', 'position_count']
    list_filter = ['snapshot_date']
    date_hierarchy = 'snapshot_date'
    readonly_fields = ['created_at']

