"""
模拟盘交易模块 Admin 后台

Django Admin 配置：
- 账户管理
- 持仓管理
- 交易记录管理
- 费率配置管理
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import URLPattern, URLResolver
from django.utils.html import format_html

from apps.simulated_trading.application.interface_services import (
    build_admin_dashboard_context,
    has_complete_closed_trade_costs,
    has_current_position_valuation,
)
from apps.simulated_trading.application.trade_admin_queries import (
    get_admin_read_only_trade_ids,
)
from apps.simulated_trading.models import (
    AccountBenchmarkComponentModel,
    AccountPositionValuationSnapshotModel,
    DailyInspectionNotificationConfigModel,
    DailyInspectionReportModel,
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
    UnifiedAccountCashFlowModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm

if TYPE_CHECKING:
    DailyInspectionReportAdminBase = admin.ModelAdmin[DailyInspectionReportModel]
    DailyInspectionNotificationConfigAdminBase = admin.ModelAdmin[
        DailyInspectionNotificationConfigModel
    ]
    AccountBenchmarkComponentAdminBase = admin.ModelAdmin[AccountBenchmarkComponentModel]
    UnifiedAccountCashFlowAdminBase = admin.ModelAdmin[UnifiedAccountCashFlowModel]
    AccountPositionValuationSnapshotAdminBase = admin.ModelAdmin[
        AccountPositionValuationSnapshotModel
    ]
else:
    DailyInspectionReportAdminBase = admin.ModelAdmin
    DailyInspectionNotificationConfigAdminBase = admin.ModelAdmin
    AccountBenchmarkComponentAdminBase = admin.ModelAdmin
    UnifiedAccountCashFlowAdminBase = admin.ModelAdmin
    AccountPositionValuationSnapshotAdminBase = admin.ModelAdmin


class FeeConfigAdminForm(TypedModelForm[FeeConfigModel]):
    """Legacy FeeConfig editor; strict V2 policy metadata is never form-written."""

    class Meta:
        model = FeeConfigModel
        fields = (
            "config_name",
            "asset_type",
            "commission_rate_buy",
            "commission_rate_sell",
            "min_commission",
            "stamp_duty_rate",
            "transfer_fee_rate",
            "min_transfer_fee",
            "slippage_rate",
            "is_default",
            "is_active",
            "description",
        )


@admin.register(FeeConfigModel)
class FeeConfigAdmin(TypedModelAdmin[FeeConfigModel]):
    """费率配置管理"""

    list_display = [
        "id",
        "config_name",
        "asset_type",
        "commission_rate_buy_display",
        "commission_rate_sell_display",
        "stamp_duty_rate_display",
        "is_active",
        "fee_policy_id",
        "fee_policy_version",
        "fee_policy_effective_from",
        "fee_policy_valid_until",
        "created_at",
    ]
    list_filter = ["asset_type", "is_active"]
    search_fields = ["config_name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]
    form = FeeConfigAdminForm

    strict_policy_readonly_fields = (
        "fee_policy_id",
        "fee_policy_version",
        "fee_policy_account_scope",
        "fee_policy_effective_from",
        "fee_policy_valid_until",
        "fee_policy_transaction_cases",
        "fee_policy_content_hash",
    )

    fieldsets = (
        ("基础信息", {"fields": ("config_name", "asset_type", "description")}),
        ("佣金费率", {"fields": ("commission_rate_buy", "commission_rate_sell", "min_commission")}),
        (
            "印花税与过户费",
            {"fields": ("stamp_duty_rate", "transfer_fee_rate", "min_transfer_fee")},
        ),
        ("滑点", {"fields": ("slippage_rate",)}),
        ("状态", {"fields": ("is_active",)}),
        (
            "严格版本策略（由 create_simulated_fee_policy_v2 管理，后台只读）",
            {
                "fields": (
                    "fee_policy_id",
                    "fee_policy_version",
                    "fee_policy_account_scope",
                    "fee_policy_effective_from",
                    "fee_policy_valid_until",
                    "fee_policy_transaction_cases",
                    "fee_policy_content_hash",
                )
            },
        ),
        ("元信息", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(
        self,
        request: HttpRequest,
        obj: FeeConfigModel | None = None,
    ) -> tuple[str, ...]:
        """Keep strict rows entirely read-only and hide write authority in the form."""

        if obj is not None and obj.fee_policy_id is not None:
            return tuple(field.name for field in FeeConfigModel._meta.fields)
        return tuple(
            dict.fromkeys(
                (*super().get_readonly_fields(request, obj), *self.strict_policy_readonly_fields)
            )
        )

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: FeeConfigModel | None = None,
    ) -> bool:
        """Allow legacy cleanup while protecting immutable strict policy versions."""

        if obj is not None and obj.fee_policy_id is not None:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(
        self,
        request: HttpRequest,
        obj: FeeConfigModel,
        form: forms.ModelForm[FeeConfigModel],
        change: bool,
    ) -> None:
        """Require a persisted authenticated operator and preserve strict-row immutability."""

        if not request.user.is_authenticated or request.user.pk is None:
            raise PermissionDenied("费率配置写入要求已认证且具有持久身份的操作员")
        if obj.fee_policy_id is not None:
            raise PermissionDenied("严格 FeeConfig 版本只能通过应用管理命令创建")
        super().save_model(request, obj, form, change)

    @admin.display(description="买入费率")
    def commission_rate_buy_display(self, obj: FeeConfigModel) -> str:
        """买入费率显示"""
        return f"{obj.commission_rate_buy * 100:g}%"

    @admin.display(description="卖出费率")
    def commission_rate_sell_display(self, obj: FeeConfigModel) -> str:
        """卖出费率显示"""
        return f"{obj.commission_rate_sell * 100:g}%"

    @admin.display(description="印花税率")
    def stamp_duty_rate_display(self, obj: FeeConfigModel) -> str:
        """印花税率显示"""
        return f"{obj.stamp_duty_rate * 100:g}%"


@admin.register(SimulatedAccountModel)
class SimulatedAccountAdmin(TypedModelAdmin[SimulatedAccountModel]):
    """模拟账户管理"""

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Create ledger records through the owning application use cases."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: SimulatedAccountModel | None = None
    ) -> bool:
        """Keep whole-row ORM edits from bypassing account locks and order holds."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: SimulatedAccountModel | None = None
    ) -> bool:
        """Require the application lifecycle to validate ledger deletion."""
        return False

    list_display = [
        "id",
        "account_name",
        "account_type_display",
        "initial_capital_display",
        "total_value_display",
        "total_return_display",
        "sharpe_ratio_display",
        "total_trades",
        "win_rate_display",
        "is_active",
        "auto_trading_enabled",
        "start_date",
    ]
    list_filter = ["account_type", "is_active", "auto_trading_enabled", "start_date"]
    search_fields = ["account_name"]
    readonly_fields = [
        "id",
        "start_date",
        "cash_reconciliation_status_display",
        "current_cash_display",
        "current_market_value_display",
        "total_value_display",
        "total_trades",
        "winning_trades",
        "total_return_display",
        "annual_return_display",
        "max_drawdown_display",
        "sharpe_ratio_display",
        "win_rate_display",
        "last_trade_date",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("基础信息", {"fields": ("account_name", "account_type", "initial_capital", "start_date")}),
        (
            "资金状态",
            {
                "fields": (
                    "cash_reconciliation_status_display",
                    "current_cash_display",
                    "current_market_value_display",
                    "total_value_display",
                )
            },
        ),
        (
            "交易配置",
            {
                "fields": (
                    "max_position_pct",
                    "stop_loss_pct",
                    ("commission_rate", "slippage_rate"),
                )
            },
        ),
        ("自动交易", {"fields": ("is_active", "auto_trading_enabled")}),
        (
            "绩效指标",
            {
                "fields": (
                    "total_return_display",
                    "annual_return_display",
                    "max_drawdown_display",
                    "sharpe_ratio_display",
                    "win_rate_display",
                )
            },
        ),
        (
            "交易统计",
            {
                "fields": (
                    "total_trades",
                    "winning_trades",
                    "last_trade_date",
                )
            },
        ),
        ("元信息", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="账户类型")
    def account_type_display(self, obj: SimulatedAccountModel) -> str:
        """账户类型显示"""
        return obj.get_account_type_display()

    @admin.display(description="初始资金")
    def initial_capital_display(self, obj: SimulatedAccountModel) -> str:
        """初始资金显示"""
        return f"¥{obj.initial_capital:,.2f}"

    def _has_current_valuation(self, obj: SimulatedAccountModel) -> bool:
        """Return whether all current positions have a usable reference mark."""
        if obj.pk is None:
            return False
        return has_current_position_valuation(obj.pk)

    def _has_complete_closed_trade_costs(self, obj: SimulatedAccountModel) -> bool:
        """Return whether every executed sell has complete basis and fee evidence."""
        if obj.pk is None:
            return False
        return has_complete_closed_trade_costs(obj.pk)

    @admin.display(description="现金核验状态")
    def cash_reconciliation_status_display(self, obj: SimulatedAccountModel) -> str:
        """Show whether stored cash has a complete evidence source."""
        if obj.cash_known is True:
            return "已核实"
        return f"未核实（{obj.cash_reconciliation_status}）"

    @admin.display(description="当前现金")
    def current_cash_display(self, obj: SimulatedAccountModel) -> str:
        """Hide the stored numeric placeholder when cash is unverified."""
        if obj.cash_known is not True:
            return "未核实"
        return f"¥{obj.current_cash:,.2f}"

    @admin.display(description="当前持仓市值")
    def current_market_value_display(self, obj: SimulatedAccountModel) -> str:
        """Hide the aggregate when any current position lacks a known mark."""
        if not self._has_current_valuation(obj):
            return "未核实"
        return f"¥{obj.current_market_value:,.2f}"

    @admin.display(description="总资产")
    def total_value_display(self, obj: SimulatedAccountModel) -> str:
        """总资产显示"""
        if obj.cash_known is not True or not self._has_current_valuation(obj):
            return "未核实"
        total_value = obj.total_value or 0
        color = "green" if total_value >= (obj.initial_capital or 0) else "red"
        amount_text = f"{float(total_value):,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>', color, amount_text
        )

    @admin.display(description="总收益率")
    def total_return_display(self, obj: SimulatedAccountModel) -> str:
        """总收益率显示"""
        if obj.cash_known is not True or not self._has_current_valuation(obj):
            return "未核实"
        if obj.total_return is None:
            return "-"
        color = "green" if obj.total_return >= 0 else "red"
        pct_text = f"{obj.total_return:+.2f}%"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, pct_text)

    @admin.display(description="年化收益率")
    def annual_return_display(self, obj: SimulatedAccountModel) -> str:
        """Hide a potentially stale performance value when account value is unknown."""
        if obj.cash_known is not True or not self._has_current_valuation(obj):
            return "未核实"
        return "-" if obj.annual_return is None else f"{obj.annual_return:+.2f}%"

    @admin.display(description="最大回撤")
    def max_drawdown_display(self, obj: SimulatedAccountModel) -> str:
        """Hide a potentially stale drawdown when account value is unknown."""
        if obj.cash_known is not True or not self._has_current_valuation(obj):
            return "未核实"
        return "-" if obj.max_drawdown is None else f"{obj.max_drawdown:.2f}%"

    @admin.display(description="夏普比率")
    def sharpe_ratio_display(self, obj: SimulatedAccountModel) -> str:
        """夏普比率显示"""
        if (
            obj.cash_known is not True
            or not self._has_current_valuation(obj)
            or not self._has_complete_closed_trade_costs(obj)
        ):
            return "未核实"
        if obj.sharpe_ratio is None:
            return "-"
        color = "green" if obj.sharpe_ratio >= 1.0 else "orange" if obj.sharpe_ratio >= 0 else "red"
        value_text = f"{obj.sharpe_ratio:.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>', color, value_text
        )

    @admin.display(description="胜率")
    def win_rate_display(self, obj: SimulatedAccountModel) -> str:
        """胜率显示"""
        if (
            obj.cash_known is not True
            or not self._has_current_valuation(obj)
            or not self._has_complete_closed_trade_costs(obj)
        ):
            return "未核实"
        if obj.win_rate is None:
            return "-"
        color = "green" if obj.win_rate >= 50 else "red"
        pct_text = f"{obj.win_rate:.1f}%"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, pct_text)


@admin.register(PositionModel)
class SimulatedPositionAdmin(TypedModelAdmin[PositionModel]):
    """持仓管理"""

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Create ledger records through the owning application use cases."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: PositionModel | None = None) -> bool:
        """Keep whole-row ORM edits from bypassing account locks and order holds."""
        return False

    def has_delete_permission(self, request: HttpRequest, obj: PositionModel | None = None) -> bool:
        """Require the application lifecycle to validate ledger deletion."""
        return False

    list_display = [
        "id",
        "account_link",
        "asset_code",
        "asset_name",
        "asset_type",
        "quantity",
        "available_quantity_known",
        "avg_cost_display",
        "current_price_display",
        "market_value_display",
        "unrealized_pnl_display",
        "unrealized_pnl_pct_display",
        "first_buy_date",
        "first_buy_date_known",
        "last_update_date",
    ]
    list_filter = [
        "asset_type",
        "available_quantity_known",
        "first_buy_date",
        "first_buy_date_known",
        "last_update_date",
    ]
    search_fields = ["asset_code", "asset_name", "account__account_name"]
    readonly_fields = [
        "id",
        "available_quantity_known",
        "first_buy_date_known",
        "last_update_date",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            "基础信息",
            {
                "fields": (
                    "account",
                    "asset_code",
                    "asset_name",
                    "asset_type",
                )
            },
        ),
        (
            "持仓数量",
            {"fields": ("quantity", "available_quantity", "available_quantity_known")},
        ),
        (
            "成本与价格",
            {
                "fields": (
                    "avg_cost",
                    "total_cost",
                    "current_price",
                )
            },
        ),
        (
            "市值与盈亏",
            {
                "fields": (
                    "market_value",
                    "unrealized_pnl",
                    "unrealized_pnl_pct",
                )
            },
        ),
        (
            "交易信息",
            {
                "fields": (
                    "signal_id",
                    "entry_reason",
                    "first_buy_date",
                    "first_buy_date_known",
                    "last_update_date",
                )
            },
        ),
        ("元信息", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="账户")
    def account_link(self, obj: PositionModel) -> str:
        """账户链接"""
        from django.urls import reverse

        url = reverse("admin:simulated_trading_simulatedaccountmodel_change", args=[obj.account_id])
        return format_html('<a href="{}">{}</a>', url, obj.account.account_name)

    @admin.display(description="平均成本")
    def avg_cost_display(self, obj: PositionModel) -> str:
        """平均成本显示"""
        if obj.cost_basis_known is None:
            return "成本未知"
        if obj.cost_basis_known is False:
            return "成本不完整"
        return f"¥{obj.avg_cost:.2f}"

    @admin.display(description="当前价格")
    def current_price_display(self, obj: PositionModel) -> str:
        """当前价格显示"""
        if obj.valuation_known is not True:
            return "未核实"
        return f"¥{obj.current_price:.2f}"

    @admin.display(description="市值")
    def market_value_display(self, obj: PositionModel) -> str:
        """市值显示"""
        if obj.valuation_known is not True:
            return "未核实"
        return f"¥{obj.market_value:,.2f}"

    @admin.display(description="浮盈")
    def unrealized_pnl_display(self, obj: PositionModel) -> str:
        """浮盈显示"""
        if obj.valuation_known is not True or obj.cost_basis_known is not True:
            return "成本或估值未核实"
        color = "green" if obj.unrealized_pnl >= 0 else "red"
        pnl_text = f"{obj.unrealized_pnl:+,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>', color, pnl_text
        )

    @admin.display(description="浮盈率")
    def unrealized_pnl_pct_display(self, obj: PositionModel) -> str:
        """浮盈率显示"""
        if obj.valuation_known is not True or obj.cost_basis_known is not True:
            return "成本或估值未核实"
        color = "green" if obj.unrealized_pnl_pct >= 0 else "red"
        pct_text = f"{obj.unrealized_pnl_pct:+.2f}%"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, pct_text)


@admin.register(SimulatedTradeModel)
class SimulatedTradeAdmin(TypedModelAdmin[SimulatedTradeModel]):
    """交易记录管理"""

    list_display = [
        "id",
        "account_link",
        "asset_code",
        "asset_name",
        "action_display",
        "quantity",
        "price_display",
        "amount_display",
        "total_cost_display",
        "realized_pnl_display",
        "realized_pnl_pct_display",
        "execution_date",
        "execution_time",
        "status_display",
    ]
    list_filter = ["action", "asset_type", "status", "execution_date"]
    search_fields = ["asset_code", "asset_name", "account__account_name", "reason"]
    readonly_fields = [
        "id",
        "amount",
        "commission",
        "slippage",
        "total_cost",
        "realized_pnl",
        "realized_pnl_pct",
        "order_date",
        "execution_date",
        "execution_time",
        "created_at",
    ]
    date_hierarchy = "execution_date"

    fieldsets = (
        (
            "基础信息",
            {
                "fields": (
                    "account",
                    "asset_code",
                    "asset_name",
                    "asset_type",
                )
            },
        ),
        (
            "交易详情",
            {
                "fields": (
                    "action",
                    "quantity",
                    "price",
                    "amount",
                )
            },
        ),
        (
            "费用",
            {
                "fields": (
                    "commission",
                    "slippage",
                    "total_cost",
                )
            },
        ),
        (
            "盈亏",
            {
                "fields": (
                    "realized_pnl",
                    "realized_pnl_pct",
                )
            },
        ),
        ("交易原因", {"fields": ("reason", "signal_id")}),
        (
            "时间",
            {
                "fields": (
                    "order_date",
                    "execution_date",
                    "execution_time",
                )
            },
        ),
        ("状态", {"fields": ("status",)}),
        ("元信息", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def _has_append_only_fill_history(self, obj: SimulatedTradeModel | None) -> bool:
        """Whether a persisted Trade carries a V4 marker or any immutable receipt."""

        if obj is None or type(obj.pk) is not int or obj.pk <= 0:
            return False
        if type(obj.settlement_plan_binding_version) is int and (
            obj.settlement_plan_binding_version == 4
        ):
            return True
        return obj.pk in get_admin_read_only_trade_ids((obj.pk,))

    def get_readonly_fields(
        self, request: HttpRequest, obj: SimulatedTradeModel | None = None
    ) -> tuple[str, ...]:
        """Display all stored fields as read-only when a fill identity exists."""

        if self._has_append_only_fill_history(obj):
            return tuple(field.name for field in self.model._meta.concrete_fields)
        return tuple(super().get_readonly_fields(request, obj))

    def has_change_permission(
        self, request: HttpRequest, obj: SimulatedTradeModel | None = None
    ) -> bool:
        """Keep fill-backed rows viewable while denying Admin changes."""

        if self._has_append_only_fill_history(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(
        self, request: HttpRequest, obj: SimulatedTradeModel | None = None
    ) -> bool:
        """Retain V4 and receipt-backed rows as immutable audit history."""

        if self._has_append_only_fill_history(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(
        self, request: HttpRequest, queryset: QuerySet[SimulatedTradeModel]
    ) -> None:
        """Require an authorized operator and delete only checked Trade IDs."""

        if not request.user.is_authenticated or request.user.pk is None:
            raise PermissionDenied("交易记录删除要求已认证且具有持久身份的用户")
        if not self.has_delete_permission(request):
            raise PermissionDenied("当前用户没有删除交易记录的权限")
        trade_ids = tuple(int(trade_id) for trade_id in queryset.values_list("pk", flat=True))
        if get_admin_read_only_trade_ids(trade_ids):
            raise PermissionDenied
        checked_queryset = queryset.filter(pk__in=trade_ids)
        super().delete_queryset(request, checked_queryset)

    @admin.display(description="账户")
    def account_link(self, obj: SimulatedTradeModel) -> str:
        """账户链接"""
        from django.urls import reverse

        url = reverse("admin:simulated_trading_simulatedaccountmodel_change", args=[obj.account_id])
        return format_html('<a href="{}">{}</a>', url, obj.account.account_name)

    @admin.display(description="方向")
    def action_display(self, obj: SimulatedTradeModel) -> str:
        """交易方向显示"""
        color = "red" if obj.action == "buy" else "green"
        label = "买入" if obj.action == "buy" else "卖出"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, label)

    @admin.display(description="价格")
    def price_display(self, obj: SimulatedTradeModel) -> str:
        """价格显示"""
        return f"¥{obj.price:.2f}"

    @admin.display(description="金额")
    def amount_display(self, obj: SimulatedTradeModel) -> str:
        """金额显示"""
        return f"¥{obj.amount:,.2f}"

    @admin.display(description="总费用")
    def total_cost_display(self, obj: SimulatedTradeModel) -> str:
        """总费用显示"""
        return f"¥{obj.total_cost:.2f}"

    @admin.display(description="已实现盈亏")
    def realized_pnl_display(self, obj: SimulatedTradeModel) -> str:
        """已实现盈亏显示"""
        if obj.cost_basis_known is not True or obj.fee_amounts_known is not True:
            return "成本或费用未核实"
        if obj.realized_pnl is None:
            return "-"
        color = "green" if obj.realized_pnl >= 0 else "red"
        pnl_text = f"{obj.realized_pnl:+,.2f}"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{}</span>', color, pnl_text
        )

    @admin.display(description="盈亏率")
    def realized_pnl_pct_display(self, obj: SimulatedTradeModel) -> str:
        """已实现盈亏率显示"""
        if obj.realized_pnl_pct is None:
            return "-"
        color = "green" if obj.realized_pnl_pct >= 0 else "red"
        pct_text = f"{obj.realized_pnl_pct:+.2f}%"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, pct_text)

    @admin.display(description="状态")
    def status_display(self, obj: SimulatedTradeModel) -> str:
        """状态显示"""
        status_map = {
            "pending": "orange",
            "executed": "green",
            "cancelled": "red",
            "failed": "red",
        }
        color = status_map.get(obj.status, "gray")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>', color, obj.get_status_display()
        )


@admin.register(DailyInspectionReportModel)
class DailyInspectionReportAdmin(DailyInspectionReportAdminBase):
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
class DailyInspectionNotificationConfigAdmin(DailyInspectionNotificationConfigAdminBase):
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

    site_header = "AgomTradePro 模拟盘交易管理"
    site_title = "模拟盘管理"
    index_title = "欢迎使用模拟盘交易管理系统"

    def get_urls(self) -> list[URLPattern | URLResolver]:
        from django.urls import path

        urls = super().get_urls()
        custom_urls: list[URLPattern | URLResolver] = [
            path("dashboard/", self.admin_view(dashboard_view), name="dashboard"),
        ]
        return custom_urls + urls


def dashboard_view(request: HttpRequest) -> HttpResponse:
    """模拟盘仪表盘视图"""
    from django.shortcuts import render

    context = {
        "title": "模拟盘仪表盘",
        "site_header": SimulatedTradingAdminSite.site_header,
    }
    context.update(build_admin_dashboard_context())

    return render(request, "admin/simulated_trading/dashboard.html", context)


@admin.register(AccountBenchmarkComponentModel)
class AccountBenchmarkComponentAdmin(AccountBenchmarkComponentAdminBase):
    """账户基准成分管理"""

    list_display = [
        "id",
        "account",
        "benchmark_code",
        "weight_display",
        "display_name",
        "sort_order",
        "is_active",
        "updated_at",
    ]
    list_filter = ["is_active"]
    search_fields = ["account__account_name", "benchmark_code", "display_name"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        ("基础信息", {"fields": ("account", "benchmark_code", "display_name")}),
        ("配置", {"fields": ("weight", "sort_order", "is_active")}),
        ("元信息", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="权重")
    def weight_display(self, obj: AccountBenchmarkComponentModel) -> str:
        return f"{obj.weight:.1%}"


@admin.register(UnifiedAccountCashFlowModel)
class UnifiedAccountCashFlowAdmin(UnifiedAccountCashFlowAdminBase):
    """统一账户现金流管理（只读）"""

    list_display = [
        "id",
        "account",
        "flow_type",
        "amount_display",
        "flow_date",
        "source_app",
        "source_id",
        "created_at",
    ]
    list_filter = ["flow_type", "source_app", "flow_date"]
    search_fields = ["account__account_name", "source_id", "notes"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "flow_date"

    @admin.display(description="金额")
    def amount_display(self, obj: UnifiedAccountCashFlowModel) -> str:
        val = float(obj.amount)
        color = "green" if val >= 0 else "red"
        return format_html(
            '<span style="color: {}; font-weight: bold;">¥{:,.2f}</span>', color, val
        )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # 只读，通过业务逻辑写入


@admin.register(AccountPositionValuationSnapshotModel)
class AccountPositionValuationSnapshotAdmin(AccountPositionValuationSnapshotAdminBase):
    """持仓时点估值快照管理（只读）"""

    list_display = [
        "id",
        "account",
        "record_date",
        "asset_code",
        "asset_name",
        "quantity",
        "close_price_display",
        "market_value_display",
        "unrealized_pnl_display",
    ]
    list_filter = ["record_date", "asset_type"]
    search_fields = ["account__account_name", "asset_code", "asset_name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    date_hierarchy = "record_date"

    @admin.display(description="收盘价")
    def close_price_display(self, obj: AccountPositionValuationSnapshotModel) -> str:
        return f"¥{float(obj.close_price):.4f}"

    @admin.display(description="市值")
    def market_value_display(self, obj: AccountPositionValuationSnapshotModel) -> str:
        return f"¥{float(obj.market_value):,.2f}"

    @admin.display(description="浮盈")
    def unrealized_pnl_display(self, obj: AccountPositionValuationSnapshotModel) -> str:
        val = float(obj.unrealized_pnl)
        color = "green" if val >= 0 else "red"
        return format_html('<span style="color: {};">¥{:+,.2f}</span>', color, val)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # 只读，通过业务逻辑写入


# 创建专用 Admin 站点实例
simulated_trading_admin = SimulatedTradingAdminSite(name="simulated_trading_admin")


@admin.register(SimulatedOrderReservationModel)
class SimulatedOrderReservationAdmin(TypedModelAdmin[SimulatedOrderReservationModel]):
    """Inspect accepted commitments without manually changing their resource state."""

    list_display = (
        "id",
        "account",
        "idempotency_key",
        "security_id",
        "side",
        "quantity",
        "cash_reserved",
        "shares_reserved",
        "status",
        "reserved_at",
    )
    list_filter = ("status", "side")
    search_fields = ("idempotency_key", "security_id", "asset_code")

    def get_readonly_fields(
        self, request: HttpRequest, obj: SimulatedOrderReservationModel | None = None
    ) -> tuple[str, ...]:
        """Display every stored field as audit evidence."""
        return tuple(field.name for field in self.model._meta.concrete_fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Admit commitments only through the account-locking application use case."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: SimulatedOrderReservationModel | None = None
    ) -> bool:
        """Require transactional lifecycle operations for every hold transition."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: SimulatedOrderReservationModel | None = None
    ) -> bool:
        """Retain original order keys and resource audit after terminal states."""
        return False
