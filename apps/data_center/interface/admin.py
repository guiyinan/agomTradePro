"""
Data Center — Django Admin Registration
"""

from django import forms
from django.contrib import admin
from django.http import HttpRequest

from apps.data_center.application.interface_services import can_create_provider_settings
from apps.data_center.models import (
    DataProviderSettingsModel,
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    ProductionCoverageUniverseConfigModel,
    ProviderConfigModel,
    PublisherCatalogModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm


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

    class Meta:
        model = ProviderConfigModel
        fields = "__all__"

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


@admin.register(ProviderConfigModel)
class ProviderConfigAdmin(TypedModelAdmin[ProviderConfigModel]):
    form = ProviderConfigAdminForm
    list_display = ("name", "source_type", "is_active", "priority", "updated_at")
    list_filter = ("source_type", "is_active")
    search_fields = ("name", "description")
    ordering = ("priority", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Identity", {"fields": ("name", "source_type", "is_active", "priority")}),
        (
            "Credentials",
            {
                "fields": ("api_key", "api_secret", "http_url", "api_endpoint"),
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


@admin.register(DataProviderSettingsModel)
class DataProviderSettingsAdmin(TypedModelAdmin[DataProviderSettingsModel]):
    list_display = ("default_source", "enable_failover", "failover_tolerance", "updated_at")
    readonly_fields = ("created_at", "updated_at")

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
