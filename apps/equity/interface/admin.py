"""Typed Django Admin configuration for Equity data and scoring weights."""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse

from apps.equity.application.repository_provider import (
    get_equity_scoring_weight_config_repository,
)
from apps.equity.models import (
    ScoringWeightConfigModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


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
