"""Typed Django Admin entrypoint for Regime logs and threshold governance."""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

from apps.regime.application.interface_services import activate_regime_threshold_config
from apps.regime.models import RegimeIndicatorThreshold, RegimeLog, RegimeThresholdConfig
from shared.infrastructure.django_admin import (
    TypedModelAdmin,
    TypedModelForm,
    TypedTabularInline,
)


class RegimeIndicatorThresholdAdminForm(TypedModelForm[RegimeIndicatorThreshold]):
    """Reject new threshold rows targeting the immutable active config."""

    class Meta:
        model = RegimeIndicatorThreshold
        fields = "__all__"

    def clean_config(self) -> RegimeThresholdConfig:
        """Return an inactive parent configuration for threshold editing."""

        config: object = self.cleaned_data.get("config")
        if not isinstance(config, RegimeThresholdConfig):
            raise ValidationError("请选择有效的候选配置。")
        if config.is_active:
            raise ValidationError("活动配置不可直接修改，请先编辑未激活候选配置。")
        return config


class RegimeIndicatorThresholdInline(
    TypedTabularInline[RegimeIndicatorThreshold, RegimeThresholdConfig]
):
    """Edit candidate configuration thresholds with their parent config."""

    model = RegimeIndicatorThreshold
    extra = 0
    min_num = 2
    fields = (
        "indicator_code",
        "indicator_name",
        "level_low",
        "level_high",
        "description",
    )


@admin.register(RegimeThresholdConfig)
class RegimeThresholdConfigAdmin(TypedModelAdmin[RegimeThresholdConfig]):
    """Govern immutable active thresholds and editable inactive candidates."""

    list_display = (
        "name",
        "status_badge",
        "indicators_count",
        "threshold_summary",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("name",)
    readonly_fields = ("is_active", "created_at", "updated_at")
    actions = ("activate_selected_config",)
    inlines = (RegimeIndicatorThresholdInline,)
    fieldsets = (
        ("基本信息", {"fields": ("name", "is_active")}),
        ("指标阈值（通过下方表格编辑）", {"fields": ()}),
        (
            "系统信息",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[RegimeThresholdConfig]:
        """Prefetch thresholds used by count and summary list columns."""

        return super().get_queryset(request).prefetch_related("thresholds")

    @admin.display(description="状态", ordering="is_active")
    def status_badge(self, obj: RegimeThresholdConfig) -> SafeString:
        """Render an escaped active-state badge."""

        label = "激活中" if obj.is_active else "未激活"
        background = "#22c55e" if obj.is_active else "#94a3b8"
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-size: 12px;">{}</span>',
            background,
            label,
        )

    @admin.display(description="指标数量")
    def indicators_count(self, obj: RegimeThresholdConfig) -> str:
        """Return the number of prefetched threshold rows."""

        return f"{len(obj.thresholds.all())} 个指标"

    @admin.display(description="阈值摘要")
    def threshold_summary(self, obj: RegimeThresholdConfig) -> SafeString:
        """Render escaped threshold values without trusting database content."""

        thresholds = list(obj.thresholds.all())
        if not thresholds:
            return mark_safe("未配置")
        return format_html_join(
            mark_safe("<br>"),
            "{}: 低={}, 高={}",
            (
                (threshold.indicator_code, threshold.level_low, threshold.level_high)
                for threshold in thresholds
            ),
        )

    @admin.action(description="激活选中的单个候选配置")
    def activate_selected_config(
        self,
        request: HttpRequest,
        queryset: QuerySet[RegimeThresholdConfig],
    ) -> None:
        """Activate exactly one candidate through the Application facade."""

        if (
            not request.user.is_authenticated
            or request.user.pk is None
            or not self.has_change_permission(request)
        ):
            raise PermissionDenied("Regime threshold activation requires change permission")
        selected = list(queryset.order_by("pk")[:2])
        if len(selected) != 1:
            self.message_user(request, "每次必须且只能选择一个候选配置。", level=messages.ERROR)
            return
        config_id = selected[0].pk
        if not isinstance(config_id, int) or config_id <= 0:
            self.message_user(request, "候选配置缺少有效主键。", level=messages.ERROR)
            return
        try:
            activated_name = activate_regime_threshold_config(config_id=config_id)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, f"已成功激活配置：{activated_name}", level=messages.SUCCESS)

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: RegimeThresholdConfig | None = None,
    ) -> bool:
        """Keep the active configuration immutable until another candidate is activated."""

        if obj is not None and obj.is_active:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegimeThresholdConfig | None = None,
    ) -> bool:
        """Prevent deletion of the active configuration."""

        if obj is not None and obj.is_active:
            return False
        return super().has_delete_permission(request, obj)

    def save_model(
        self,
        request: HttpRequest,
        obj: RegimeThresholdConfig,
        form: forms.ModelForm[RegimeThresholdConfig],
        change: bool,
    ) -> None:
        """Persist newly created configs as inactive candidates."""

        if not request.user.is_authenticated or request.user.pk is None:
            raise PermissionDenied("A persisted admin user is required")
        if not change:
            obj.is_active = False
        super().save_model(request, obj, form, change)


@admin.register(RegimeIndicatorThreshold)
class RegimeIndicatorThresholdAdmin(TypedModelAdmin[RegimeIndicatorThreshold]):
    """Manage threshold rows while protecting the active configuration."""

    list_display = (
        "indicator_code",
        "indicator_name",
        "config_name",
        "threshold_range",
        "description",
    )
    list_filter = ("config", "indicator_code")
    search_fields = ("indicator_code", "indicator_name", "description")
    form = RegimeIndicatorThresholdAdminForm

    @admin.display(description="配置名称", ordering="config__name")
    def config_name(self, obj: RegimeIndicatorThreshold) -> str:
        """Return the parent configuration name."""

        return str(obj.config.name)

    @admin.display(description="阈值范围")
    def threshold_range(self, obj: RegimeIndicatorThreshold) -> str:
        """Return the configured low-to-high range."""

        return f"{obj.level_low} ~ {obj.level_high}"

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: RegimeIndicatorThreshold | None = None,
    ) -> bool:
        """Prevent direct edits to thresholds used by the active config."""

        if obj is not None and obj.config.is_active:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: RegimeIndicatorThreshold | None = None,
    ) -> bool:
        """Prevent deletion of thresholds used by the active config."""

        if obj is not None and obj.config.is_active:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(RegimeLog)
class RegimeLogAdmin(TypedModelAdmin[RegimeLog]):
    """Read Regime decision logs through a typed Admin surface."""

    list_display = (
        "observed_at",
        "dominant_regime",
        "confidence",
        "growth_momentum_z",
        "inflation_momentum_z",
    )
    list_filter = ("dominant_regime", "observed_at")
    date_hierarchy = "observed_at"
    readonly_fields = ("created_at",)
