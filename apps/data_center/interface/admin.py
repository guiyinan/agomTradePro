"""
Data Center — Django Admin Registration
"""

from typing import Any

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.data_center.application.interface_services import (
    can_create_provider_settings,
    load_provider_settings_payload,
)
from apps.data_center.models import (
    DataOwnerRegistrationModel,
    DataProviderSettingsModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    ProductionCoverageUniverseConfigModel,
    ProviderConfigModel,
    PublisherCatalogModel,
    ReconciliationEvidenceModel,
)
from shared.config.tushare import (
    TUSHARE_REQUEST_MODE_SDK_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    TUSHARE_REQUEST_MODE_VALUES,
)
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm

_TUSHARE_REQUEST_MODE_LABELS: dict[str, str] = {
    TUSHARE_REQUEST_MODE_SDK_PATH: "标准 Tushare",
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY: "统一中继",
}


class ProviderConfigAdminForm(TypedModelForm[ProviderConfigModel]):
    """Prevent stored provider credentials from being rendered back to browsers."""

    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the existing API key.",
    )
    api_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to keep the existing API secret.",
    )
    tushare_request_mode = forms.ChoiceField(
        required=False,
        label="Tushare 连接方式",
        choices=[
            (TUSHARE_REQUEST_MODE_SDK_PATH, "标准 Tushare"),
            (TUSHARE_REQUEST_MODE_UNIFIED_RELAY, "统一中继"),
        ],
        help_text="统一中继使用上方服务地址和 API Key；标准方式保持官方 SDK 调用。",
    )

    class Meta:
        model = ProviderConfigModel
        fields = "__all__"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        extra_config = self.instance.extra_config if self.instance is not None else {}
        raw_mode = (extra_config or {}).get("tushare_request_mode")
        initial_mode = (
            raw_mode if raw_mode in TUSHARE_REQUEST_MODE_VALUES else TUSHARE_REQUEST_MODE_SDK_PATH
        )
        self.initial["tushare_request_mode"] = initial_mode

    def clean_api_key(self) -> str:
        """Preserve an existing API key when the masked input stays blank."""

        value = self.cleaned_data.get("api_key")
        if isinstance(value, str) and value:
            return value
        return self.instance.api_key if self.instance.pk is not None else ""

    def clean_api_secret(self) -> str:
        """Preserve an existing API secret when the masked input stays blank."""

        value = self.cleaned_data.get("api_secret")
        if isinstance(value, str) and value:
            return value
        return self.instance.api_secret if self.instance.pk is not None else ""

    def clean(self) -> dict[str, Any]:
        """Persist and validate the explicit Tushare transport selection."""

        cleaned_data = super().clean() or {}
        source_type = cleaned_data.get("source_type")
        extra_config = dict(cleaned_data.get("extra_config") or {})
        if source_type != "tushare":
            extra_config.pop("tushare_request_mode", None)
            cleaned_data["extra_config"] = extra_config
            return cleaned_data

        submitted_mode = cleaned_data.get("tushare_request_mode")
        mode = submitted_mode or self.initial.get(
            "tushare_request_mode", TUSHARE_REQUEST_MODE_SDK_PATH
        )
        if mode not in TUSHARE_REQUEST_MODE_VALUES:
            self.add_error("tushare_request_mode", "请选择有效的 Tushare 连接方式。")
            return cleaned_data
        if mode == TUSHARE_REQUEST_MODE_UNIFIED_RELAY and not cleaned_data.get("http_url"):
            self.add_error("http_url", "统一中继连接必须填写服务地址。")

        extra_config["tushare_request_mode"] = mode
        cleaned_data["extra_config"] = extra_config
        return cleaned_data


class DataProviderSettingsAdminForm(TypedModelForm[DataProviderSettingsModel]):
    """Keep all typed provider runtime values out of the legacy singleton form."""

    class Meta:
        model = DataProviderSettingsModel
        fields = ("description",)


@admin.register(ProviderConfigModel)
class ProviderConfigAdmin(TypedModelAdmin[ProviderConfigModel]):
    form = ProviderConfigAdminForm
    list_display = (
        "name",
        "source_type",
        "tushare_connection_mode",
        "is_active",
        "priority",
        "updated_at",
    )
    list_filter = ("source_type", "is_active")
    search_fields = ("name", "description")
    ordering = ("priority", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Identity", {"fields": ("name", "source_type", "is_active", "priority")}),
        (
            "Credentials",
            {
                "fields": (
                    "api_key",
                    "api_secret",
                    "http_url",
                    "tushare_request_mode",
                    "api_endpoint",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Advanced",
            {
                "fields": ("extra_config", "description"),
                "classes": ("collapse",),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="连接方式")
    def tushare_connection_mode(self, obj: ProviderConfigModel) -> str:
        """Display the explicit Tushare transport without exposing credentials."""

        if obj.source_type != "tushare":
            return "—"
        raw_mode = (obj.extra_config or {}).get("tushare_request_mode")
        mode = raw_mode if isinstance(raw_mode, str) else TUSHARE_REQUEST_MODE_SDK_PATH
        return _TUSHARE_REQUEST_MODE_LABELS.get(mode, "未识别")


@admin.register(DataProviderSettingsModel)
class DataProviderSettingsAdmin(TypedModelAdmin[DataProviderSettingsModel]):
    form = DataProviderSettingsAdminForm
    list_display = (
        "typed_default_source",
        "typed_failover_enabled",
        "typed_failover_tolerance",
        "updated_at",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "typed_failover_enabled",
        "typed_failover_tolerance",
        "typed_default_source",
        "runtime_config_notice",
    )

    fieldsets = (
        (None, {"fields": ("description",)}),
        (
            "Config Center 运行时配置",
            {
                "fields": (
                    "typed_default_source",
                    "typed_failover_enabled",
                    "typed_failover_tolerance",
                    "runtime_config_notice",
                ),
                "description": "Provider source、failover 开关和容差已迁移到 Config Center typed runtime profile；此 Admin 仅保留只读摘要。",
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require model permission and allow only one singleton row."""

        return super().has_add_permission(request) and can_create_provider_settings()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DataProviderSettingsModel | None = None,
    ) -> bool:
        """Keep the global provider settings singleton non-deletable."""

        return False

    @admin.display(description="Typed failover")
    def typed_failover_enabled(self, obj: DataProviderSettingsModel) -> str:
        """Display the active typed failover switch without enabling legacy writes."""

        payload = load_provider_settings_payload()
        return "启用" if bool(payload.get("enable_failover")) else "停用"

    @admin.display(description="Typed default source")
    def typed_default_source(self, obj: DataProviderSettingsModel) -> str:
        """Display the active typed provider source without enabling legacy writes."""

        payload = load_provider_settings_payload()
        labels = dict(DataProviderSettingsModel.DEFAULT_SOURCE_CHOICES)
        value = str(payload.get("default_source") or "")
        return labels.get(value, "未知")

    @admin.display(description="Typed tolerance")
    def typed_failover_tolerance(self, obj: DataProviderSettingsModel) -> str:
        """Display the active typed failover tolerance."""

        payload = load_provider_settings_payload()
        try:
            return f"{float(payload.get('failover_tolerance', 0.0)):.2%}"
        except (TypeError, ValueError):
            return "未知"

    @admin.display(description="运行时配置入口")
    def runtime_config_notice(self, obj: DataProviderSettingsModel) -> str:
        """Explain where typed failover settings are managed."""

        return "请使用 Config Center/TUI 系统设置页面管理 typed runtime profile。"


@admin.register(ProductionCoverageUniverseConfigModel)
class ProductionCoverageUniverseConfigAdmin(TypedModelAdmin[ProductionCoverageUniverseConfigModel]):
    list_display = (
        "universe_id",
        "asset_type",
        "include_inactive",
        "min_active_asset_count",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require model permission and allow only one singleton row."""

        return (
            super().has_add_permission(request)
            and not ProductionCoverageUniverseConfigModel.objects.exists()
        )

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ProductionCoverageUniverseConfigModel | None = None,
    ) -> bool:
        """Keep the production coverage singleton non-deletable."""

        return False


@admin.register(IndicatorCatalogModel)
class IndicatorCatalogAdmin(TypedModelAdmin[IndicatorCatalogModel]):
    list_display = ("code", "name_cn", "category", "default_period_type", "is_active")
    list_filter = ("category", "default_period_type", "is_active")
    search_fields = ("code", "name_cn", "name_en", "description")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PublisherCatalogModel)
class PublisherCatalogAdmin(TypedModelAdmin[PublisherCatalogModel]):
    list_display = ("code", "canonical_name", "publisher_class", "is_active")
    list_filter = ("publisher_class", "is_active")
    search_fields = ("code", "canonical_name", "canonical_name_en", "description")
    ordering = ("code",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(IndicatorUnitRuleModel)
class IndicatorUnitRuleAdmin(TypedModelAdmin[IndicatorUnitRuleModel]):
    list_display = (
        "indicator_code",
        "source_type",
        "original_unit",
        "storage_unit",
        "display_unit",
        "dimension_key",
        "priority",
        "is_active",
    )
    list_filter = ("source_type", "dimension_key", "is_active")
    search_fields = ("indicator_code", "original_unit", "storage_unit", "display_unit")
    ordering = ("indicator_code", "-priority", "source_type", "original_unit")
    readonly_fields = ("created_at", "updated_at")


@admin.register(DatasetContractModel)
class DatasetContractAdmin(TypedModelAdmin[DatasetContractModel]):
    """Expose versioned contracts without allowing ad-hoc admin edits."""

    list_display = (
        "dataset_key",
        "contract_version",
        "schema_version",
        "owner",
        "decision_critical",
        "active",
        "updated_at",
    )
    list_filter = ("decision_critical", "active", "owner")
    search_fields = ("dataset_key", "owner", "comparable_group")
    readonly_fields = (
        "dataset_key",
        "contract_version",
        "schema_version",
        "owner",
        "frequency",
        "decision_critical",
        "fields",
        "freshness_seconds",
        "comparable_group",
        "active",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require catalog bootstrap/Application ownership for new rows."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DatasetContractModel | None = None,
    ) -> bool:
        """Prevent destructive edits from the admin surface."""

        return False


@admin.register(DatasetProviderBindingModel)
class DatasetProviderBindingAdmin(TypedModelAdmin[DatasetProviderBindingModel]):
    """Expose provider routing evidence as read-only governance data."""

    list_display = (
        "dataset_key",
        "provider",
        "capability",
        "priority",
        "validator_key",
        "enabled",
        "updated_at",
    )
    list_filter = ("enabled", "provider", "capability")
    search_fields = ("dataset_key", "provider", "capability", "validator_key")
    readonly_fields = tuple(field.name for field in DatasetProviderBindingModel._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require catalog bootstrap/Application ownership for new rows."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DatasetProviderBindingModel | None = None,
    ) -> bool:
        """Prevent destructive edits from the admin surface."""

        return False


@admin.register(DatasetPublicationPolicyModel)
class DatasetPublicationPolicyAdmin(TypedModelAdmin[DatasetPublicationPolicyModel]):
    """Expose publication gates as read-only governance data."""

    list_display = (
        "dataset_key",
        "contract_version",
        "minimum_coverage_ratio",
        "allow_partial",
        "conflict_action",
        "retention_days",
        "active",
    )
    list_filter = ("allow_partial", "conflict_action", "active")
    search_fields = ("dataset_key", "contract_version", "conflict_action")
    readonly_fields = tuple(field.name for field in DatasetPublicationPolicyModel._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require catalog bootstrap/Application ownership for new rows."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DatasetPublicationPolicyModel | None = None,
    ) -> bool:
        """Prevent destructive edits from the admin surface."""

        return False


@admin.register(DataOwnerRegistrationModel)
class DataOwnerRegistrationAdmin(TypedModelAdmin[DataOwnerRegistrationModel]):
    """Expose ownership and acceptance accountability as read-only data."""

    list_display = (
        "dataset_key",
        "data_platform_owner",
        "business_owner",
        "acceptance_owner",
        "active",
        "updated_at",
    )
    list_filter = ("active", "business_owner", "acceptance_owner")
    search_fields = ("dataset_key", "data_platform_owner", "business_owner", "acceptance_owner")
    readonly_fields = tuple(field.name for field in DataOwnerRegistrationModel._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require catalog bootstrap/Application ownership for new rows."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: DataOwnerRegistrationModel | None = None,
    ) -> bool:
        """Prevent destructive edits from the admin surface."""

        return False


@admin.register(ReconciliationEvidenceModel)
class ReconciliationEvidenceAdmin(TypedModelAdmin[ReconciliationEvidenceModel]):
    """Expose shadow comparison evidence without permitting mutation."""

    list_display = (
        "dataset_key",
        "is_clean",
        "observed_at",
        "legacy_snapshot_hash",
        "canonical_snapshot_hash",
    )
    list_filter = ("dataset_key", "is_clean")
    search_fields = (
        "dataset_key",
        "legacy_snapshot_hash",
        "canonical_snapshot_hash",
    )
    readonly_fields = tuple(field.name for field in ReconciliationEvidenceModel._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Require the reconciliation Application Port for new evidence."""

        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ReconciliationEvidenceModel | None = None,
    ) -> bool:
        """Prevent destructive removal of shadow evidence."""

        return False
