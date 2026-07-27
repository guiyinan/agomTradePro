"""Typed Django Admin configuration for Equity data and scoring weights."""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse

from apps.equity.application.repository_provider import (
    get_equity_scoring_weight_config_repository,
)
from apps.equity.models import (
    FinancialDataModel,
    ScoringWeightConfigModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


@admin.register(StockInfoModel)
class StockInfoAdmin(TypedModelAdmin[StockInfoModel]):
    """Admin interface for stock master data."""

    list_display = (
        "stock_code",
        "name",
        "sector",
        "market",
        "list_date",
        "is_active",
        "created_at",
    )
    list_filter = ("market", "sector", "is_active")
    search_fields = ("stock_code", "name", "sector")
    date_hierarchy = "list_date"
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("基本信息", {"fields": ("stock_code", "name", "sector", "market", "list_date")}),
        ("状态", {"fields": ("is_active",)}),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(StockDailyModel)
class StockDailyAdmin(TypedModelAdmin[StockDailyModel]):
    """Admin interface for daily stock facts."""

    list_display = (
        "stock_code",
        "trade_date",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "change_pct_calculated",
    )
    list_filter = ("trade_date",)
    search_fields = ("stock_code",)
    date_hierarchy = "trade_date"
    readonly_fields = ("created_at",)
    fieldsets = (
        ("基本信息", {"fields": ("stock_code", "trade_date")}),
        ("价格数据", {"fields": ("open", "high", "low", "close")}),
        ("成交数据", {"fields": ("volume", "amount", "turnover_rate")}),
        (
            "技术指标",
            {
                "fields": ("ma5", "ma20", "ma60", "macd", "macd_signal", "macd_hist", "rsi"),
                "classes": ("collapse",),
            },
        ),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    @admin.display(description="涨跌幅(%)")
    def change_pct_calculated(self, obj: StockDailyModel) -> Decimal | str:
        """Return the open-to-close percentage when the open price is non-zero."""

        if obj.open != 0:
            return round((obj.close - obj.open) / obj.open * 100, 2)
        return "-"


@admin.register(FinancialDataModel)
class FinancialDataAdmin(TypedModelAdmin[FinancialDataModel]):
    """Admin interface for point-in-time financial facts."""

    list_display = (
        "stock_code",
        "report_date",
        "report_type",
        "revenue",
        "net_profit",
        "roe",
        "debt_ratio",
        "revenue_growth",
        "net_profit_growth",
    )
    list_filter = ("report_type", "report_date")
    search_fields = ("stock_code",)
    date_hierarchy = "report_date"
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("基本信息", {"fields": ("stock_code", "report_date", "report_type")}),
        ("利润表", {"fields": ("revenue", "net_profit", "revenue_growth", "net_profit_growth")}),
        ("资产负债表", {"fields": ("total_assets", "total_liabilities", "equity")}),
        ("财务指标", {"fields": ("roe", "roa", "debt_ratio")}),
        (
            "元数据",
            {"fields": ("publish_date", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@admin.register(ValuationModel)
class ValuationAdmin(TypedModelAdmin[ValuationModel]):
    """Admin interface for valuation facts."""

    list_display = (
        "stock_code",
        "trade_date",
        "pe_ttm",
        "pb",
        "total_mv_display",
        "circ_mv_display",
        "dividend_yield",
    )
    list_filter = ("trade_date",)
    search_fields = ("stock_code",)
    date_hierarchy = "trade_date"
    readonly_fields = ("created_at",)
    fieldsets = (
        ("基本信息", {"fields": ("stock_code", "trade_date")}),
        ("估值指标", {"fields": ("pe", "pe_ttm", "pb", "ps", "dividend_yield")}),
        ("市值", {"fields": ("total_mv", "circ_mv")}),
        ("时间戳", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    @admin.display(description="总市值")
    def total_mv_display(self, obj: ValuationModel) -> str:
        """Format total market value stored in yuan."""

        return self._format_market_value(obj.total_mv)

    @admin.display(description="流通市值")
    def circ_mv_display(self, obj: ValuationModel) -> str:
        """Format circulating market value stored in yuan."""

        return self._format_market_value(obj.circ_mv)

    @staticmethod
    def _format_market_value(value: Decimal) -> str:
        """Format a yuan-denominated market value without changing its storage unit."""

        if value >= Decimal("100000000000"):
            return f"{value / Decimal('100000000'):.1f}亿"
        return f"{value / Decimal('10000'):.0f}万"


@admin.register(ScoringWeightConfigModel)
class ScoringWeightConfigAdmin(TypedModelAdmin[ScoringWeightConfigModel]):
    """Publish immutable active weights from editable inactive candidates."""

    list_display = (
        "name",
        "is_active",
        "total_weight_check",
        "growth_weight",
        "profitability_weight",
        "valuation_weight",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "description")
    readonly_fields = ("is_active", "created_at", "updated_at")
    actions = ("activate_selected_config",)
    fieldsets = (
        ("基本信息", {"fields": ("name", "description", "is_active")}),
        (
            "评分维度权重（总和必须为 1.0）",
            {"fields": ("growth_weight", "profitability_weight", "valuation_weight")},
        ),
        (
            "成长性内部权重（总和必须为 1.0）",
            {"fields": ("revenue_growth_weight", "profit_growth_weight")},
        ),
        ("元数据", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="权重检查")
    def total_weight_check(self, obj: ScoringWeightConfigModel) -> str:
        """Display both configured weight totals."""

        dimension_total = obj.growth_weight + obj.profitability_weight + obj.valuation_weight
        growth_total = obj.revenue_growth_weight + obj.profit_growth_weight
        dimension_status = (
            "✓" if abs(dimension_total - 1.0) < 0.01 else f"✗ ({dimension_total:.2f})"
        )
        growth_status = "✓" if abs(growth_total - 1.0) < 0.01 else f"✗ ({growth_total:.2f})"
        return f"维度: {dimension_status} | 成长性: {growth_status}"

    @admin.action(description="激活选中的单个候选权重")
    def activate_selected_config(
        self,
        request: HttpRequest,
        queryset: QuerySet[ScoringWeightConfigModel],
    ) -> None:
        """Atomically activate exactly one persisted scoring-weight candidate."""

        if (
            not request.user.is_authenticated
            or request.user.pk is None
            or not self.has_change_permission(request)
        ):
            raise PermissionDenied("Scoring-weight activation requires change permission")
        selected = list(queryset.order_by("pk")[:2])
        if len(selected) != 1:
            self.message_user(request, "每次必须且只能选择一个候选权重。", level=messages.ERROR)
            return
        config_id = selected[0].pk
        if not isinstance(config_id, int) or config_id <= 0:
            self.message_user(request, "候选权重缺少有效主键。", level=messages.ERROR)
            return
        activated_name = get_equity_scoring_weight_config_repository().activate_config(config_id)
        self.message_user(request, f"已激活评分权重：{activated_name}", level=messages.SUCCESS)

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: ScoringWeightConfigModel | None = None,
    ) -> bool:
        """Keep active scoring weights immutable until another candidate is activated."""

        if obj is not None and obj.is_active:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ScoringWeightConfigModel | None = None,
    ) -> bool:
        """Prevent deletion of the active scoring-weight configuration."""

        if obj is not None and obj.is_active:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(
        self,
        request: HttpRequest,
        obj: ScoringWeightConfigModel,
        form: forms.ModelForm[ScoringWeightConfigModel],
        change: bool,
    ) -> None:
        """Persist newly created configs as inactive candidates."""

        if not request.user.is_authenticated or request.user.pk is None:
            raise PermissionDenied("A persisted admin user is required")
        if not change:
            obj.is_active = False
        super().save_model(request, obj, form, change)

    def response_add(
        self,
        request: HttpRequest,
        obj: ScoringWeightConfigModel,
        post_url_continue: str | None = None,
    ) -> HttpResponse:
        """Explain the explicit candidate activation workflow after creation."""

        messages.info(
            request,
            "配置已保存为未激活候选。请在列表中选择该配置并执行激活动作。",
        )
        return super().response_add(request, obj, post_url_continue)
