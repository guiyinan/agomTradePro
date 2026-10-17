"""
Django Admin for Account Module.

提供 Account 模块所有模型的 Admin 管理界面。
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, TypeAlias, cast

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import router
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.urls.resolvers import URLPattern
from django.utils.html import format_html

from apps.account.application.transaction_cost_use_cases import RecordTransactionCostUseCase
from apps.account.application.transaction_record_use_cases import CreateTransactionUseCase
from apps.account.domain.transaction_cost_calculations import canonical_fee_amount
from apps.account.domain.transaction_record_contracts import CreateTransactionInput
from apps.account.models import (
    AccountProfileModel,
    AssetCategoryModel,
    AssetMetadataModel,
    CapitalFlowModel,
    CurrencyModel,
    DocumentationModel,
    ExchangeRateModel,
    InvestmentRuleModel,
    MacroSizingConfigModel,
    PortfolioDailySnapshotModel,
    PortfolioModel,
    PositionModel,
    StopLossConfigModel,
    StopLossTriggerModel,
    TakeProfitConfigModel,
    TradingCostConfigModel,
    TransactionCostConfigModel,
    TransactionModel,
    UserAccessTokenModel,
)
from core.exceptions import AuthorizationError, InvalidInputError
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm

_AdminFieldSpec: TypeAlias = str | list[str] | tuple[str, ...] | tuple[()]


@admin.register(CurrencyModel)
class CurrencyModelAdmin(TypedModelAdmin[CurrencyModel]):
    """币种管理"""

    list_display = ["code", "name", "symbol", "is_base", "is_active", "precision"]
    list_filter = ["is_base", "is_active"]
    search_fields = ["code", "name"]
    ordering = ["-is_base", "code"]


@admin.register(AssetCategoryModel)
class AssetCategoryModelAdmin(TypedModelAdmin[AssetCategoryModel]):
    """资产分类管理"""

    list_display = ["code", "name", "parent", "level", "path", "is_active", "sort_order"]
    list_filter = ["level", "is_active"]
    search_fields = ["code", "name", "path"]
    ordering = ["path", "sort_order"]


@admin.register(AccountProfileModel)
class AccountProfileModelAdmin(TypedModelAdmin[AccountProfileModel]):
    """用户账户配置管理"""

    list_display = [
        "user",
        "display_name",
        "risk_tolerance",
        "initial_capital",
        "mcp_enabled",
        "approval_status_badge",
        "created_at",
    ]
    list_filter = ["risk_tolerance", "approval_status", "mcp_enabled", "user_agreement_accepted"]
    search_fields = ["user__username", "display_name"]
    readonly_fields = ["created_at", "updated_at", "agreement_accepted_at", "agreement_ip_address"]

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "user",
                    "display_name",
                    "initial_capital",
                    "risk_tolerance",
                    "mcp_enabled",
                )
            },
        ),
        (
            "波动率控制",
            {"fields": ("target_volatility", "volatility_tolerance", "max_volatility_reduction")},
        ),
        (
            "协议确认",
            {
                "fields": (
                    "user_agreement_accepted",
                    "risk_warning_acknowledged",
                    "agreement_accepted_at",
                    "agreement_ip_address",
                )
            },
        ),
        (
            "审批状态",
            {"fields": ("approval_status", "approved_at", "approved_by", "rejection_reason")},
        ),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="审批状态")
    def approval_status_badge(self, obj: AccountProfileModel) -> str:
        """审批状态标签"""
        colors = {
            "pending": "#ffc107",
            "approved": "#28a745",
            "rejected": "#dc3545",
            "auto_approved": "#17a2b8",
        }
        color = colors.get(obj.approval_status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.get_approval_status_display(),
        )


@admin.register(PortfolioModel)
class PortfolioModelAdmin(TypedModelAdmin[PortfolioModel]):
    """投资组合管理"""

    list_display = [
        "user",
        "name",
        "base_currency",
        "is_active",
        "total_value_display",
        "total_pnl_pct_display",
        "position_count",
    ]
    list_filter = ["is_active", "base_currency"]
    search_fields = ["user__username", "name"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="总市值")
    def total_value_display(self, obj: PortfolioModel) -> str:
        """总市值显示"""
        return f"¥{obj.total_value:,.2f}" if obj.total_value else "¥0.00"

    @admin.display(description="收益率")
    def total_pnl_pct_display(self, obj: PortfolioModel) -> str:
        """总盈亏百分比显示"""
        pct = obj.total_pnl_pct
        color = "#28a745" if pct >= 0 else "#dc3545"
        return format_html('<span style="color: {};">{:+.2f}%</span>', color, pct)


@admin.register(PositionModel)
class PositionModelAdmin(TypedModelAdmin[PositionModel]):
    """持仓管理"""

    list_display = [
        "portfolio",
        "asset_code",
        "category",
        "currency",
        "shares",
        "avg_cost",
        "market_value",
        "unrealized_pnl_pct_display",
        "source",
        "is_closed",
    ]
    list_filter = ["asset_class", "region", "cross_border", "source", "is_closed"]
    search_fields = ["asset_code", "portfolio__name"]
    readonly_fields = ["created_at", "updated_at", "opened_at", "closed_at"]
    date_hierarchy = "opened_at"

    @admin.display(description="盈亏%")
    def unrealized_pnl_pct_display(self, obj: PositionModel) -> str:
        """盈亏百分比显示"""
        pct = obj.unrealized_pnl_pct
        color = "#28a745" if pct >= 0 else "#dc3545"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:+.2f}%</span>', color, pct
        )


@admin.register(TransactionModel)
class TransactionModelAdmin(TypedModelAdmin[TransactionModel]):
    """交易记录管理"""

    list_display = [
        "portfolio",
        "action_badge",
        "asset_code",
        "shares",
        "price",
        "notional",
        "actual_fee_display",
        "traded_at",
    ]
    list_filter = ["action", "traded_at"]
    search_fields = ["asset_code", "portfolio__name"]
    readonly_fields = [
        "created_at",
        "notional",
        "actual_fee_display",
        "cost_correction_link",
    ]
    exclude = [
        "commission",
        "slippage",
        "stamp_duty",
        "transfer_fee",
        "commission_known",
        "slippage_known",
        "stamp_duty_known",
        "transfer_fee_known",
        "estimated_cost",
        "estimated_cost_ratio",
        "cost_variance",
        "cost_variance_pct",
    ]
    date_hierarchy = "traded_at"

    def get_form(
        self,
        request: HttpRequest,
        obj: TransactionModel | None = None,
        change: bool = False,
        **kwargs: Any,
    ) -> type[forms.ModelForm[Any]]:
        """Use a narrow Application-backed form for new ledger rows."""
        kwargs["form"] = TransactionAddForm if obj is None else TransactionChangeForm
        return super().get_form(request, obj, change, **kwargs)

    def get_fields(
        self,
        request: HttpRequest,
        obj: TransactionModel | None = None,
    ) -> list[_AdminFieldSpec]:
        """Keep add fields aligned with Application create and preserve other edits."""
        if obj is None:
            fields: list[_AdminFieldSpec] = [
                "portfolio",
                "position",
                "action",
                "asset_code",
                "shares",
                "price",
                "traded_at",
                "notes",
            ]
            return fields
        return list(super().get_fields(request, obj))

    @admin.display(description="实际费用")
    def actual_fee_display(self, obj: TransactionModel) -> str:
        """Show collected amounts without exposing unavailable storage placeholders."""
        components = (
            ("手续费", obj.commission, obj.commission_known),
            ("滑点", obj.slippage, obj.slippage_known),
            ("印花税", obj.stamp_duty, obj.stamp_duty_known),
            ("过户费", obj.transfer_fee, obj.transfer_fee_known),
        )
        formatted = []
        for label, stored, known in components:
            amount = canonical_fee_amount(stored, known)
            formatted.append(
                f"{label} {amount:.2f}" if amount is not None else f"{label} 未知/未采集"
            )
        return " / ".join(formatted)

    @admin.display(description="费用修正")
    def cost_correction_link(self, obj: TransactionModel) -> str:
        """Link to the owner-rechecked actual-cost correction form."""
        if obj.pk is None:
            return "不可用"
        url = reverse(
            f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_correct_costs",
            args=[obj.pk],
        )
        return format_html('<a href="{}">修正已采集费用</a>', url)

    def save_model(
        self,
        request: HttpRequest,
        obj: TransactionModel,
        form: forms.ModelForm[TransactionModel],
        change: bool,
    ) -> None:
        """Create through Application once; preserve Django saves for changes."""
        if change:
            super().save_model(request, obj, form, change)
            return

        user = request.user
        user_id = getattr(user, "pk", None)
        if (
            not getattr(user, "is_authenticated", False)
            or isinstance(user_id, bool)
            or not isinstance(user_id, int)
        ):
            raise PermissionDenied("当前用户无权创建交易记录")

        cleaned = form.cleaned_data
        portfolio = cleaned["portfolio"]
        position = cleaned.get("position")
        command = CreateTransactionInput(
            actor_user_id=user_id,
            portfolio_id=portfolio.pk,
            position_id=position.pk if position is not None else None,
            action=cleaned["action"],
            asset_code=cleaned["asset_code"],
            shares=cleaned["shares"],
            price=cleaned["price"],
            notes=cleaned.get("notes", ""),
            traded_at=cleaned["traded_at"],
        )
        try:
            record = CreateTransactionUseCase().execute(command)
        except AuthorizationError as exc:
            raise PermissionDenied(exc.message) from exc
        except InvalidInputError as exc:
            raise PermissionDenied("交易创建条件已变化，请检查账户和持仓后重试") from exc

        obj.pk = record.id
        obj.portfolio_id = record.portfolio_id
        obj.position_id = record.position_id
        obj.action = record.action
        obj.asset_code = record.asset_code
        obj.shares = record.shares
        obj.price = record.price
        obj.notional = record.notional
        obj.commission = record.commission if record.commission is not None else Decimal("0")
        obj.commission_known = record.commission_known
        obj.slippage = record.slippage if record.slippage is not None else Decimal("0")
        obj.slippage_known = record.slippage_known
        obj.stamp_duty = record.stamp_duty if record.stamp_duty is not None else Decimal("0")
        obj.stamp_duty_known = record.stamp_duty_known
        obj.transfer_fee = record.transfer_fee if record.transfer_fee is not None else Decimal("0")
        obj.transfer_fee_known = record.transfer_fee_known
        obj.traded_at = record.traded_at
        obj.created_at = record.created_at
        obj._state.adding = False
        obj._state.db = router.db_for_write(self.model)

    def get_urls(self) -> list[URLPattern]:
        """Add the single owner-rechecked fee-correction route."""
        opts = self.model._meta
        custom = [
            path(
                "<path:object_id>/correct-costs/",
                self.admin_site.admin_view(self.correct_costs_view),
                name=f"{opts.app_label}_{opts.model_name}_correct_costs",
            )
        ]
        return custom + super().get_urls()

    def correct_costs_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        """Correct supplied actual fees through the locked Application path."""
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        if obj.pk is None:
            raise Http404

        form = TransactionCostCorrectionForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            user = request.user
            user_id = getattr(user, "pk", None)
            if (
                not getattr(user, "is_authenticated", False)
                or isinstance(user_id, bool)
                or not isinstance(user_id, int)
            ):
                raise PermissionDenied("当前用户无权修正交易费用")
            cleaned = form.cleaned_data
            try:
                RecordTransactionCostUseCase().record_actual_cost(
                    actor_user_id=user_id,
                    transaction_id=obj.pk,
                    actual_commission=cleaned["commission"],
                    actual_slippage=cleaned["slippage"],
                    actual_stamp_duty=cleaned["stamp_duty"],
                    actual_transfer_fee=cleaned["transfer_fee"],
                )
            except AuthorizationError as exc:
                raise PermissionDenied(exc.message) from exc
            except InvalidInputError as exc:
                form.add_error(None, exc.message)
            else:
                self.log_change(request, obj, "实际费用已修正")
                messages.success(request, "实际费用已修正")
                url = reverse(
                    f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
                    args=[obj.pk],
                )
                return redirect(url)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": obj,
            "form": form,
            "title": f"修正交易 {obj.id} 的实际费用",
            "current_fees": self.actual_fee_display(obj),
            "change_url": reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
                args=[obj.pk],
            ),
        }
        return render(request, "admin/account/transaction/correct_costs.html", context)

    @admin.display(description="方向")
    def action_badge(self, obj: TransactionModel) -> str:
        """交易方向标签"""
        color = "#28a745" if obj.action == "buy" else "#dc3545"
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.get_action_display().upper(),
        )


class TransactionAddForm(TypedModelForm[TransactionModel]):
    """Narrow add form whose accepted fields are consumed by the create use case."""

    class Meta:
        model = TransactionModel
        fields = [
            "portfolio",
            "position",
            "action",
            "asset_code",
            "shares",
            "price",
            "traded_at",
            "notes",
        ]

    def clean_shares(self) -> float:
        """Match the transaction API's positive finite quantity bounds."""
        value = cast(float, self.cleaned_data["shares"])
        if not math.isfinite(value) or value <= 0 or value > 1_000_000_000_000:
            raise forms.ValidationError("交易数量必须为正有限数且不超过允许范围")
        return value

    def clean_price(self) -> Decimal:
        """Require a positive finite decimal before the Application call."""
        value = cast(Decimal, self.cleaned_data["price"])
        if not value.is_finite() or value <= 0:
            raise forms.ValidationError("交易价格必须为正有限数")
        return value

    def clean(self) -> dict[str, Any]:
        """Preserve the current position association validation in the form."""
        cleaned = cast(dict[str, Any], super().clean())
        allowed_submission_names = tuple(self.fields) + (
            "traded_at_0",
            "traded_at_1",
            "csrfmiddlewaretoken",
            "_save",
            "_addanother",
            "_continue",
            "_popup",
            "_saveasnew",
            "to_field",
            "_changelist_filters",
        )
        submitted_names = tuple(self.data.keys()) + tuple(self.files.keys())
        if any(name not in allowed_submission_names for name in submitted_names):
            self.add_error(None, "提交包含交易创建表单不接受的字段")

        portfolio = cast(PortfolioModel | None, cleaned.get("portfolio"))
        position = cast(PositionModel | None, cleaned.get("position"))
        asset_code = cast(str | None, cleaned.get("asset_code"))
        if position is not None and portfolio is not None:
            if position.portfolio_id != portfolio.pk:
                self.add_error("position", "持仓不属于该投资组合")
            elif position.asset_code != asset_code:
                self.add_error("asset_code", "资产代码与关联持仓不一致")
        shares = cast(float | None, cleaned.get("shares"))
        price = cast(Decimal | None, cleaned.get("price"))
        if shares is not None and price is not None and math.isfinite(shares) and price.is_finite():
            notional_field = TransactionModel._meta.get_field("notional")
            decimal_places = notional_field.decimal_places
            quantum = Decimal("1").scaleb(-decimal_places)
            maximum = Decimal(10) ** (notional_field.max_digits - decimal_places) - quantum
            try:
                notional = (Decimal(str(shares)) * price).quantize(
                    quantum,
                    rounding=ROUND_HALF_UP,
                )
            except InvalidOperation:
                self.add_error(None, "成交金额超出允许范围")
            else:
                if notional > maximum:
                    self.add_error(None, "成交金额超出允许范围")
        return cleaned


class TransactionChangeForm(TypedModelForm[TransactionModel]):
    """Keep other existing editable fields while excluding actual and derived costs."""

    class Meta:
        model = TransactionModel
        exclude = [
            "commission",
            "slippage",
            "stamp_duty",
            "transfer_fee",
            "commission_known",
            "slippage_known",
            "stamp_duty_known",
            "transfer_fee_known",
            "estimated_cost",
            "estimated_cost_ratio",
            "cost_variance",
            "cost_variance_pct",
        ]


class TransactionCostCorrectionForm(TypedModelForm[TransactionModel]):
    """Accept nullable fee corrections, where blank means preserve."""

    class Meta:
        model = TransactionModel
        fields = ["commission", "slippage", "stamp_duty", "transfer_fee"]

    commission = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    slippage = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    stamp_duty = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )
    transfer_fee = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2
    )

    def clean(self) -> dict[str, Any]:
        """Reject an empty patch while leaving each blank component unchanged."""
        cleaned = cast(dict[str, Any], super().clean())
        if all(
            cleaned.get(field) is None
            for field in ("commission", "slippage", "stamp_duty", "transfer_fee")
        ):
            raise forms.ValidationError("至少需要提交一项实际费用")
        return cleaned


@admin.register(CapitalFlowModel)
class CapitalFlowModelAdmin(TypedModelAdmin[CapitalFlowModel]):
    """资金流水管理"""

    list_display = ["user", "portfolio", "flow_type_badge", "amount", "flow_date"]
    list_filter = ["flow_type", "flow_date"]
    search_fields = ["user__username"]
    readonly_fields = ["created_at"]
    date_hierarchy = "flow_date"

    @admin.display(description="类型")
    def flow_type_badge(self, obj: CapitalFlowModel) -> str:
        """流水类型标签"""
        colors = {
            "deposit": "#28a745",
            "withdraw": "#dc3545",
            "dividend": "#007bff",
            "interest": "#17a2b8",
            "adjustment": "#ffc107",
        }
        color = colors.get(obj.flow_type, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.get_flow_type_display(),
        )


@admin.register(AssetMetadataModel)
class AssetMetadataModelAdmin(TypedModelAdmin[AssetMetadataModel]):
    """资产元数据管理"""

    list_display = [
        "asset_code",
        "name",
        "asset_class",
        "region",
        "cross_border",
        "style",
        "sector",
    ]
    list_filter = ["asset_class", "region", "cross_border", "style"]
    search_fields = ["asset_code", "name", "sector"]


@admin.register(StopLossConfigModel)
class StopLossConfigModelAdmin(TypedModelAdmin[StopLossConfigModel]):
    """止损配置管理"""

    list_display = [
        "position",
        "stop_loss_type",
        "stop_loss_pct_display",
        "status_badge",
        "triggered_at",
    ]
    list_filter = ["stop_loss_type", "status"]
    readonly_fields = [
        "activated_at",
        "triggered_at",
        "highest_price_updated_at",
        "created_at",
        "updated_at",
    ]

    @admin.display(description="止损幅度")
    def stop_loss_pct_display(self, obj: StopLossConfigModel) -> str:
        """止损百分比显示"""
        return f"{obj.stop_loss_pct:.2%}"

    @admin.display(description="状态")
    def status_badge(self, obj: StopLossConfigModel) -> str:
        """状态标签"""
        colors = {
            "active": "#28a745",
            "triggered": "#dc3545",
            "cancelled": "#6c757d",
            "expired": "#ffc107",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 8px; border-radius: 4px;">{}</span>',
            color,
            obj.get_status_display(),
        )


@admin.register(StopLossTriggerModel)
class StopLossTriggerModelAdmin(TypedModelAdmin[StopLossTriggerModel]):
    """止损触发记录管理"""

    list_display = ["position", "trigger_type", "trigger_price", "trigger_time", "pnl_pct_display"]
    list_filter = ["trigger_type"]
    readonly_fields = ["trigger_time", "created_at"]
    date_hierarchy = "trigger_time"

    @admin.display(description="盈亏%")
    def pnl_pct_display(self, obj: StopLossTriggerModel) -> str:
        """盈亏百分比显示"""
        color = "#28a745" if obj.pnl_pct >= 0 else "#dc3545"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:+.2f}%</span>', color, obj.pnl_pct
        )


@admin.register(TakeProfitConfigModel)
class TakeProfitConfigModelAdmin(TypedModelAdmin[TakeProfitConfigModel]):
    """止盈配置管理"""

    list_display = ["position", "take_profit_pct_display", "is_active"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="止盈幅度")
    def take_profit_pct_display(self, obj: TakeProfitConfigModel) -> str:
        """止盈百分比显示"""
        return f"+{obj.take_profit_pct:.2%}"


@admin.register(DocumentationModel)
class DocumentationModelAdmin(TypedModelAdmin[DocumentationModel]):
    """文档管理"""

    list_display = ["title", "slug", "category", "order", "is_published", "created_at"]
    list_filter = ["category", "is_published"]
    search_fields = ["title", "slug"]
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ExchangeRateModel)
class ExchangeRateModelAdmin(TypedModelAdmin[ExchangeRateModel]):
    """汇率管理"""

    list_display = ["from_currency", "to_currency", "rate", "effective_date"]
    list_filter = ["from_currency", "to_currency"]
    search_fields = ["from_currency__code", "to_currency__code"]
    date_hierarchy = "effective_date"


@admin.register(InvestmentRuleModel)
class InvestmentRuleModelAdmin(TypedModelAdmin[InvestmentRuleModel]):
    """投资规则管理"""

    list_display = ["name", "rule_type", "user", "priority", "is_active"]
    list_filter = ["rule_type", "is_active"]
    search_fields = ["name", "advice_template"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MacroSizingConfigModel)
class MacroSizingConfigModelAdmin(TypedModelAdmin[MacroSizingConfigModel]):
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


@admin.register(TradingCostConfigModel)
class TradingCostConfigModelAdmin(TypedModelAdmin[TradingCostConfigModel]):
    """Manage portfolio-specific transaction fee configurations."""

    list_display = [
        "portfolio",
        "commission_rate",
        "min_commission",
        "stamp_duty_rate",
        "transfer_fee_rate",
        "is_active",
    ]
    list_filter = ["is_active"]
    search_fields = ["portfolio__name", "portfolio__user__username"]
    ordering = ["portfolio_id"]


@admin.register(TransactionCostConfigModel)
class TransactionCostConfigModelAdmin(TypedModelAdmin[TransactionCostConfigModel]):
    """Manage market and asset-class transaction fee configurations."""

    list_display = [
        "market",
        "asset_class",
        "commission_rate",
        "min_commission",
        "cost_warning_threshold",
        "is_active",
    ]
    list_filter = ["market", "asset_class", "is_active"]
    search_fields = ["market", "asset_class"]
    ordering = ["market", "asset_class"]


@admin.register(PortfolioDailySnapshotModel)
class PortfolioDailySnapshotModelAdmin(TypedModelAdmin[PortfolioDailySnapshotModel]):
    """投资组合日快照管理"""

    list_display = [
        "portfolio",
        "snapshot_date",
        "total_value",
        "cash_balance",
        "invested_value",
        "position_count",
    ]
    list_filter = ["snapshot_date"]
    date_hierarchy = "snapshot_date"
    readonly_fields = ["created_at"]


@admin.register(UserAccessTokenModel)
class UserAccessTokenModelAdmin(TypedModelAdmin[UserAccessTokenModel]):
    list_display = [
        "user",
        "name",
        "access_level",
        "token_preview",
        "is_active",
        "created_by",
        "created_at",
        "last_used_at",
        "revoked_at",
    ]
    list_filter = ["access_level", "is_active", "created_at", "revoked_at"]
    search_fields = ["user__username", "name"]
    readonly_fields = ["token_preview", "created_at", "updated_at", "last_used_at", "revoked_at"]
    exclude = ["key", "key_encrypted"]

    @admin.display(description="Token预览")
    def token_preview(self, obj: UserAccessTokenModel) -> str:
        return obj.preview
