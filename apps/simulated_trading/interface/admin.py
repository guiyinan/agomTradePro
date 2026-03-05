"""
模拟盘交易模块 Admin 后台

Django Admin 配置：
- 账户管理
- 持仓管理
- 交易记录管理
- 费率配置管理
"""
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, Q

from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    PositionModel,
    SimulatedTradeModel,
    FeeConfigModel,
    DailyInspectionReportModel,
    DailyInspectionNotificationConfigModel,
)


@admin.register(FeeConfigModel)
class FeeConfigAdmin(admin.ModelAdmin):
    """费率配置管理"""

    list_display = [
        'id',
        'config_name',
        'asset_type',
        'commission_rate_buy_display',
        'commission_rate_sell_display',
        'stamp_duty_rate_display',
        'is_active',
        'created_at',
    ]
    list_filter = ['asset_type', 'is_active']
    search_fields = ['config_name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']

    fieldsets = (
        ('基础信息', {
            'fields': ('config_name', 'asset_type', 'description')
        }),
        ('佣金费率', {
            'fields': (
                'commission_rate_buy',
                'commission_rate_sell',
                'min_commission'
            )
        }),
        ('印花税与过户费', {
            'fields': (
                'stamp_duty_rate',
                'transfer_fee_rate',
                'min_transfer_fee'
            )
        }),
        ('滑点', {
            'fields': ('slippage_rate',)
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('元信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def commission_rate_buy_display(self, obj):
        """买入费率显示"""
        return f"{obj.commission_rate_buy * 10000:.1f}%%"
    commission_rate_buy_display.short_description = '买入费率'

    def commission_rate_sell_display(self, obj):
        """卖出费率显示"""
        return f"{obj.commission_rate_sell * 10000:.1f}%%"
    commission_rate_sell_display.short_description = '卖出费率'

    def stamp_duty_rate_display(self, obj):
        """印花税率显示"""
        return f"{obj.stamp_duty_rate * 100:.1f}%%"
    stamp_duty_rate_display.short_description = '印花税率'


@admin.register(SimulatedAccountModel)
class SimulatedAccountAdmin(admin.ModelAdmin):
    """模拟账户管理"""

    list_display = [
        'id',
        'account_name',
        'account_type_display',
        'initial_capital_display',
        'total_value_display',
        'total_return_display',
        'sharpe_ratio_display',
        'total_trades',
        'win_rate_display',
        'is_active',
        'auto_trading_enabled',
        'start_date',
    ]
    list_filter = ['account_type', 'is_active', 'auto_trading_enabled', 'start_date']
    search_fields = ['account_name']
    readonly_fields = [
        'id',
        'start_date',
        'current_cash',
        'current_market_value',
        'total_value',
        'total_trades',
        'winning_trades',
        'total_return',
        'annual_return',
        'max_drawdown',
        'sharpe_ratio',
        'win_rate',
        'last_trade_date',
        'created_at',
        'updated_at',
    ]

    fieldsets = (
        ('基础信息', {
            'fields': (
                'account_name',
                'account_type',
                'initial_capital',
                'start_date'
            )
        }),
        ('资金状态', {
            'fields': (
                'current_cash',
                'current_market_value',
                'total_value',
            )
        }),
        ('交易配置', {
            'fields': (
                'max_position_pct',
                'stop_loss_pct',
                ('commission_rate', 'slippage_rate'),
            )
        }),
        ('自动交易', {
            'fields': ('is_active', 'auto_trading_enabled')
        }),
        ('绩效指标', {
            'fields': (
                'total_return',
                'annual_return',
                'max_drawdown',
                'sharpe_ratio',
                'win_rate',
            )
        }),
        ('交易统计', {
            'fields': (
                'total_trades',
                'winning_trades',
                'last_trade_date',
            )
        }),
        ('元信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def account_type_display(self, obj):
        """账户类型显示"""
        return obj.get_account_type_display()
    account_type_display.short_description = '账户类型'

    def initial_capital_display(self, obj):
        """初始资金显示"""
        return f"¥{obj.initial_capital:,.2f}"
    initial_capital_display.short_description = '初始资金'

    def total_value_display(self, obj):
        """总资产显示"""
        total_value = obj.total_value or 0
        color = 'green' if total_value >= (obj.initial_capital or 0) else 'red'
        amount_text = f"{float(total_value):,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>',
            color,
            amount_text
        )
    total_value_display.short_description = '总资产'

    def total_return_display(self, obj):
        """总收益率显示"""
        if obj.total_return is None:
            return '-'
        color = 'green' if obj.total_return >= 0 else 'red'
        pct_text = f"{obj.total_return:+.2f}%"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            pct_text
        )
    total_return_display.short_description = '总收益率'

    def sharpe_ratio_display(self, obj):
        """夏普比率显示"""
        if obj.sharpe_ratio is None:
            return '-'
        color = 'green' if obj.sharpe_ratio >= 1.0 else 'orange' if obj.sharpe_ratio >= 0 else 'red'
        value_text = f"{obj.sharpe_ratio:.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            value_text
        )
    sharpe_ratio_display.short_description = '夏普比率'

    def win_rate_display(self, obj):
        """胜率显示"""
        if obj.win_rate is None:
            return '-'
        color = 'green' if obj.win_rate >= 50 else 'red'
        pct_text = f"{obj.win_rate:.1f}%"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            pct_text
        )
    win_rate_display.short_description = '胜率'


@admin.register(PositionModel)
class SimulatedPositionAdmin(admin.ModelAdmin):
    """持仓管理"""

    list_display = [
        'id',
        'account_link',
        'asset_code',
        'asset_name',
        'asset_type',
        'quantity',
        'avg_cost_display',
        'current_price_display',
        'market_value_display',
        'unrealized_pnl_display',
        'unrealized_pnl_pct_display',
        'first_buy_date',
        'last_update_date',
    ]
    list_filter = ['asset_type', 'first_buy_date', 'last_update_date']
    search_fields = ['asset_code', 'asset_name', 'account__account_name']
    readonly_fields = [
        'id',
        'last_update_date',
        'market_value',
        'unrealized_pnl',
        'unrealized_pnl_pct',
        'created_at',
        'updated_at',
    ]

    fieldsets = (
        ('基础信息', {
            'fields': (
                'account',
                'asset_code',
                'asset_name',
                'asset_type',
            )
        }),
        ('持仓数量', {
            'fields': ('quantity', 'available_quantity')
        }),
        ('成本与价格', {
            'fields': (
                'avg_cost',
                'total_cost',
                'current_price',
            )
        }),
        ('市值与盈亏', {
            'fields': (
                'market_value',
                'unrealized_pnl',
                'unrealized_pnl_pct',
            )
        }),
        ('交易信息', {
            'fields': (
                'signal_id',
                'entry_reason',
                'first_buy_date',
                'last_update_date',
            )
        }),
        ('元信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def account_link(self, obj):
        """账户链接"""
        from django.urls import reverse
        url = reverse('admin:simulated_trading_simulatedaccountmodel_change', args=[obj.account_id])
        return format_html('<a href="{}">{}</a>', url, obj.account.account_name)
    account_link.short_description = '账户'

    def avg_cost_display(self, obj):
        """平均成本显示"""
        return f"¥{obj.avg_cost:.2f}"
    avg_cost_display.short_description = '平均成本'

    def current_price_display(self, obj):
        """当前价格显示"""
        return f"¥{obj.current_price:.2f}"
    current_price_display.short_description = '当前价格'

    def market_value_display(self, obj):
        """市值显示"""
        return f"¥{obj.market_value:,.2f}"
    market_value_display.short_description = '市值'

    def unrealized_pnl_display(self, obj):
        """浮盈显示"""
        color = 'green' if obj.unrealized_pnl >= 0 else 'red'
        pnl_text = f"{obj.unrealized_pnl:+,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>',
            color,
            pnl_text
        )
    unrealized_pnl_display.short_description = '浮盈'

    def unrealized_pnl_pct_display(self, obj):
        """浮盈率显示"""
        color = 'green' if obj.unrealized_pnl_pct >= 0 else 'red'
        pct_text = f"{obj.unrealized_pnl_pct:+.2f}%"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            pct_text
        )
    unrealized_pnl_pct_display.short_description = '浮盈率'


@admin.register(SimulatedTradeModel)
class SimulatedTradeAdmin(admin.ModelAdmin):
    """交易记录管理"""

    list_display = [
        'id',
        'account_link',
        'asset_code',
        'asset_name',
        'action_display',
        'quantity',
        'price_display',
        'amount_display',
        'total_cost_display',
        'realized_pnl_display',
        'realized_pnl_pct_display',
        'execution_date',
        'execution_time',
        'status_display',
    ]
    list_filter = ['action', 'asset_type', 'status', 'execution_date']
    search_fields = ['asset_code', 'asset_name', 'account__account_name', 'reason']
    readonly_fields = [
        'id',
        'amount',
        'commission',
        'slippage',
        'total_cost',
        'realized_pnl',
        'realized_pnl_pct',
        'order_date',
        'execution_date',
        'execution_time',
        'created_at',
    ]
    date_hierarchy = 'execution_date'

    fieldsets = (
        ('基础信息', {
            'fields': (
                'account',
                'asset_code',
                'asset_name',
                'asset_type',
            )
        }),
        ('交易详情', {
            'fields': (
                'action',
                'quantity',
                'price',
                'amount',
            )
        }),
        ('费用', {
            'fields': (
                'commission',
                'slippage',
                'total_cost',
            )
        }),
        ('盈亏', {
            'fields': (
                'realized_pnl',
                'realized_pnl_pct',
            )
        }),
        ('交易原因', {
            'fields': ('reason', 'signal_id')
        }),
        ('时间', {
            'fields': (
                'order_date',
                'execution_date',
                'execution_time',
            )
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('元信息', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def account_link(self, obj):
        """账户链接"""
        from django.urls import reverse
        url = reverse('admin:simulated_trading_simulatedaccountmodel_change', args=[obj.account_id])
        return format_html('<a href="{}">{}</a>', url, obj.account.account_name)
    account_link.short_description = '账户'

    def action_display(self, obj):
        """交易方向显示"""
        color = 'red' if obj.action == 'buy' else 'green'
        label = '买入' if obj.action == 'buy' else '卖出'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            label
        )
    action_display.short_description = '方向'

    def price_display(self, obj):
        """价格显示"""
        return f"¥{obj.price:.2f}"
    price_display.short_description = '价格'

    def amount_display(self, obj):
        """金额显示"""
        return f"¥{obj.amount:,.2f}"
    amount_display.short_description = '金额'

    def total_cost_display(self, obj):
        """总费用显示"""
        return f"¥{obj.total_cost:.2f}"
    total_cost_display.short_description = '总费用'

    def realized_pnl_display(self, obj):
        """已实现盈亏显示"""
        if obj.realized_pnl is None:
            return '-'
        color = 'green' if obj.realized_pnl >= 0 else 'red'
        pnl_text = f"{obj.realized_pnl:+,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>',
            color,
            pnl_text
        )
    realized_pnl_display.short_description = '已实现盈亏'

    def realized_pnl_pct_display(self, obj):
        """已实现盈亏率显示"""
        if obj.realized_pnl_pct is None:
            return '-'
        color = 'green' if obj.realized_pnl_pct >= 0 else 'red'
        pct_text = f"{obj.realized_pnl_pct:+.2f}%"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            pct_text
        )
    realized_pnl_pct_display.short_description = '盈亏率'

    def status_display(self, obj):
        """状态显示"""
        status_map = {
            'pending': 'orange',
            'executed': 'green',
            'cancelled': 'red',
            'failed': 'red',
        }
        color = status_map.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = '状态'


@admin.register(DailyInspectionReportModel)
class DailyInspectionReportAdmin(admin.ModelAdmin):
    """日更巡检报告管理"""

    list_display = [
        "id",
        "inspection_date",
        "account",
        "strategy",
        "status",
        "macro_regime",
        "policy_gear",
        "updated_at",
    ]
    list_filter = ["inspection_date", "status", "macro_regime", "policy_gear"]
    search_fields = ["account__account_name", "strategy__name", "macro_regime", "policy_gear"]
    readonly_fields = ["created_at", "updated_at", "summary", "checks"]


@admin.register(DailyInspectionNotificationConfigModel)
class DailyInspectionNotificationConfigAdmin(admin.ModelAdmin):
    """巡检邮件通知配置管理"""

    list_display = [
        "id",
        "account",
        "is_enabled",
        "notify_on",
        "include_owner_email",
        "updated_at",
    ]
    list_filter = ["is_enabled", "notify_on", "include_owner_email"]
    search_fields = ["account__account_name", "account__user__username"]
    readonly_fields = ["created_at", "updated_at"]


# ============================================================================
# 自定义 Admin Site
# ============================================================================

class SimulatedTradingAdminSite(admin.AdminSite):
    """模拟盘交易专用 Admin 站点"""

    site_header = 'AgomSAAF 模拟盘交易管理'
    site_title = '模拟盘管理'
    index_title = '欢迎使用模拟盘交易管理系统'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('dashboard/', self.admin_view(dashboard_view), name='dashboard'),
        ]
        return custom_urls + urls


def dashboard_view(request):
    """模拟盘仪表盘视图"""
    from django.shortcuts import render
    from datetime import timedelta
    from django.utils import timezone

    # 获取统计数据
    total_accounts = SimulatedAccountModel._default_manager.filter(is_active=True).count()
    total_positions = PositionModel._default_manager.count()
    total_trades = SimulatedTradeModel._default_manager.count()

    # 今日交易统计
    today = timezone.now().date()
    today_trades = SimulatedTradeModel._default_manager.filter(execution_date=today)
    today_buy_count = today_trades.filter(action='buy').count()
    today_sell_count = today_trades.filter(action='sell').count()

    # 资金统计
    total_capital = SimulatedAccountModel._default_manager.filter(
        is_active=True
    ).aggregate(
        total=Sum('total_value')
    )['total'] or 0

    total_pnl = SimulatedTradeModel._default_manager.filter(
        action='sell',
        realized_pnl__isnull=False
    ).aggregate(
        total=Sum('realized_pnl')
    )['total'] or 0

    context = {
        'title': '模拟盘仪表盘',
        'total_accounts': total_accounts,
        'total_positions': total_positions,
        'total_trades': total_trades,
        'today_buy_count': today_buy_count,
        'today_sell_count': today_sell_count,
        'total_capital': total_capital,
        'total_pnl': total_pnl,
        'site_header': SimulatedTradingAdminSite.site_header,
    }

    return render(request, 'admin/simulated_trading/dashboard.html', context)


# 创建专用 Admin 站点实例
simulated_trading_admin = SimulatedTradingAdminSite(name='simulated_trading_admin')

