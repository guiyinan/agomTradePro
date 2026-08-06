"""
Django Admin for Account Module.

提供 Account 模块所有模型的 Admin 管理界面。
"""

from typing import Any, cast

from django import forms
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.utils.html import format_html

from apps.account.application.repository_provider import (
    AccountInterfaceRepository,
    get_account_interface_repository,
    get_backup_delivery_settings,
)
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
from apps.config_center.application.public import (
    config_secret_present,
    update_backup_delivery_settings,
)
from apps.config_center.domain.backup_delivery import (
    BACKUP_ARCHIVE_PASSWORD_SECRET_REF,
    BACKUP_SMTP_PASSWORD_SECRET_REF,
)
from apps.config_center.models import SystemSettingsModel
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm

SYSTEM_SETTINGS_TYPED_RUNTIME_FIELDS = frozenset(
    {
        "market_color_convention",
        "benchmark_code_map",
        "asset_proxy_code_map",
        "require_user_approval",
        "auto_approve_first_admin",
        "default_mcp_enabled",
        "allow_token_plaintext_view",
        "user_agreement_content",
        "risk_warning_content",
        "notes",
        "qlib_enabled",
        "qlib_provider_uri",
        "qlib_region",
        "qlib_model_path",
        "qlib_default_universe",
        "qlib_default_feature_set_id",
        "qlib_default_label_id",
        "qlib_train_queue_name",
        "qlib_infer_queue_name",
        "qlib_allow_auto_activate",
        "alpha_fixed_provider",
        "alpha_pool_mode",
    }
)


def _system_settings_admin_fields() -> tuple[str, ...]:
    """Return only Account-owned fields for the compatibility admin form."""

    return tuple(
        field.name
        for field in SystemSettingsModel._meta.fields
        if field.editable and field.name not in SYSTEM_SETTINGS_TYPED_RUNTIME_FIELDS
    )


def _account_interface_repository() -> AccountInterfaceRepository:
    """Return the lightweight account interface repository."""

    return get_account_interface_repository()


class SystemSettingsAdminForm(TypedModelForm[SystemSettingsModel]):
    backup_password = forms.CharField(
        required=False,
        label="备份压缩密码",
        widget=forms.PasswordInput(render_value=False),
        help_text="留空表示保持当前密码不变；如需清空，请先关闭备份功能后保存。",
    )
    backup_smtp_password = forms.CharField(
        required=False,
        label="SMTP 密码",
        widget=forms.PasswordInput(render_value=False),
        help_text="留空表示保持当前密码不变。",
    )

    class Meta:
        model = SystemSettingsModel
        fields = _system_settings_admin_fields()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if (
            self.instance
            and self.instance.pk
            and (
                self.instance.backup_password_encrypted
                or _secret_present(BACKUP_ARCHIVE_PASSWORD_SECRET_REF)
            )
        ):
            self.fields["backup_password"].help_text = (
                "已设置备份密码。留空表示保持当前密码不变；输入新值会覆盖旧密码。"
            )
        if (
            self.instance
            and self.instance.pk
            and (
                self.instance.backup_smtp_password_encrypted
                or _secret_present(BACKUP_SMTP_PASSWORD_SECRET_REF)
            )
        ):
            self.fields["backup_smtp_password"].help_text = (
                "已设置 SMTP 密码。留空表示保持当前密码不变；输入新值会覆盖旧密码。"
            )

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean() or {}
        raw_password = (cleaned_data.get("backup_password") or "").strip()
        raw_smtp_password = (cleaned_data.get("backup_smtp_password") or "").strip()
        backup_enabled = cleaned_data.get("backup_enabled")
        has_existing_password = bool(
            getattr(self.instance, "backup_password_encrypted", "")
            or _secret_present(BACKUP_ARCHIVE_PASSWORD_SECRET_REF)
        )
        has_existing_smtp_password = bool(
            getattr(self.instance, "backup_smtp_password_encrypted", "")
            or _secret_present(BACKUP_SMTP_PASSWORD_SECRET_REF)
        )
        if backup_enabled and not (raw_password or has_existing_password):
            self.add_error("backup_password", "启用数据库备份邮件时必须设置备份密码。")
        if backup_enabled and not (raw_smtp_password or has_existing_smtp_password):
            self.add_error("backup_smtp_password", "启用数据库备份邮件时必须设置 SMTP 密码。")
        return cleaned_data

    def save(self, commit: bool = True) -> SystemSettingsModel:
        instance = super().save(commit=False)
        raw_password = (self.cleaned_data.get("backup_password") or "").strip()
        raw_smtp_password = (self.cleaned_data.get("backup_smtp_password") or "").strip()
        if not commit:
            return instance

        payload: dict[str, Any] = {
            field_name: getattr(instance, field_name)
            for field_name in (
                "backup_enabled",
                "backup_email",
                "backup_app_base_url",
                "backup_mail_from_email",
                "backup_smtp_host",
                "backup_smtp_port",
                "backup_smtp_username",
                "backup_smtp_use_tls",
                "backup_smtp_use_ssl",
                "backup_interval_days",
                "backup_link_ttl_days",
                "backup_password_hint",
            )
        }
        if raw_password:
            payload["backup_archive_password"] = raw_password
        if raw_smtp_password:
            payload["backup_smtp_password"] = raw_smtp_password
        update_backup_delivery_settings(payload, actor="django-admin")
        self.save_m2m()
        return cast(SystemSettingsModel, get_backup_delivery_settings())


def _secret_present(secret_ref: str) -> bool:
    """Read only presence metadata for a Config Center-owned secret."""

    try:
        return config_secret_present(secret_ref)
    except (RuntimeError, ValueError):
        return False


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
        "commission",
        "traded_at",
    ]
    list_filter = ["action", "traded_at"]
    search_fields = ["asset_code", "portfolio__name"]
    readonly_fields = ["created_at"]
    date_hierarchy = "traded_at"

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


@admin.register(SystemSettingsModel)
class SystemSettingsModelAdmin(TypedModelAdmin[SystemSettingsModel]):
    """系统配置管理（单例模式）"""

    form = SystemSettingsAdminForm

    def get_object(
        self,
        request: HttpRequest,
        object_id: str,
        from_field: str | None = None,
    ) -> SystemSettingsModel | None:
        """Display the Config Center-owned backup policy projection."""

        persisted = super().get_object(request, object_id, from_field=from_field)
        return get_backup_delivery_settings() if persisted is not None else None

    def has_add_permission(self, request: HttpRequest) -> bool:
        """禁止手动添加（单例模式）"""
        return not _account_interface_repository().has_system_settings_singleton()

    def has_delete_permission(
        self, request: HttpRequest, obj: SystemSettingsModel | None = None
    ) -> bool:
        """禁止删除配置"""
        return False

    list_display = [
        "backup_enabled",
        "backup_email",
        "backup_last_sent_at",
    ]

    fieldsets = (
        (
            "数据库备份邮件",
            {
                "fields": (
                    "backup_enabled",
                    "backup_email",
                    "backup_app_base_url",
                    "backup_mail_from_email",
                    "backup_interval_days",
                    "backup_link_ttl_days",
                    "backup_password",
                    "backup_password_hint",
                    "backup_smtp_host",
                    "backup_smtp_port",
                    "backup_smtp_username",
                    "backup_smtp_password",
                    "backup_smtp_use_tls",
                    "backup_smtp_use_ssl",
                    "backup_last_sent_at",
                )
            },
        ),
        (
            "运行时配置",
            {
                "fields": ("runtime_config_notice",),
                "description": "账户准入、MCP/Token 开关、协议内容以及 Qlib/Alpha/市场映射已迁移到 Config Center/TUI；此兼容 Admin 不直接写入运行时 Profile。",
            },
        ),
        ("时间戳", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = [
        "created_at",
        "updated_at",
        "backup_last_sent_at",
        "runtime_config_notice",
    ]

    @admin.display(description="运行时配置入口")
    def runtime_config_notice(self, obj: SystemSettingsModel) -> str:
        """Explain where typed runtime settings are managed."""

        return "请使用 Config Center/TUI 系统设置页面管理 typed runtime profile。"

    def changelist_view(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """自定义列表页（单例模式）"""
        config = _account_interface_repository().get_existing_system_settings()
        if config is not None:
            return super().change_view(request, str(config.pk), extra_context=extra_context)
        return super().changelist_view(request, extra_context)


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
