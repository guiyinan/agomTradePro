import math

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.http import HttpRequest

from apps.pulse.models import (
    NavigatorAssetConfigModel,
    PulseIndicatorConfigModel,
    PulseLog,
)
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm


def _finite_float(
    value: object,
    *,
    field_name: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    """Validate one Admin numeric boundary without accepting booleans or NaN."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError({field_name: "必须是有效数字"})
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValidationError({field_name: f"必须大于等于 {minimum}"})
    if maximum is not None and result > maximum:
        raise ValidationError({field_name: f"必须小于等于 {maximum}"})
    return result


class PulseIndicatorConfigAdminForm(TypedModelForm[PulseIndicatorConfigModel]):
    """Validate Pulse indicator weights before publishing runtime configuration."""

    class Meta:
        model = PulseIndicatorConfigModel
        fields = "__all__"

    def clean_weight(self) -> float:
        """Require a finite positive indicator weight."""

        return _finite_float(
            self.cleaned_data.get("weight"),
            field_name="weight",
            minimum=0.000000001,
        )


class NavigatorAssetConfigAdminForm(TypedModelForm[NavigatorAssetConfigModel]):
    """Validate Navigator risk budgets at the Admin publication boundary."""

    class Meta:
        model = NavigatorAssetConfigModel
        fields = "__all__"

    def clean_risk_budget(self) -> float:
        """Require a finite normalized risk budget."""

        return _finite_float(
            self.cleaned_data.get("risk_budget"),
            field_name="risk_budget",
            minimum=0.0,
            maximum=1.0,
        )


@admin.register(PulseLog)
class PulseLogAdmin(TypedModelAdmin[PulseLog]):
    list_display = [
        "observed_at",
        "regime_context",
        "composite_score",
        "regime_strength",
        "transition_warning",
        "data_source",
        "created_at",
    ]
    list_filter = ["regime_context", "regime_strength", "transition_warning", "data_source"]
    search_fields = ["regime_context"]
    readonly_fields = [field.name for field in PulseLog._meta.fields]
    ordering = ["-observed_at"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent operators from fabricating calculated Pulse snapshots."""

        del request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: PulseLog | None = None,
    ) -> bool:
        """Keep calculated Pulse snapshots immutable."""

        del request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: PulseLog | None = None,
    ) -> bool:
        """Prevent deleting calculated Pulse evidence through Admin."""

        del request, obj
        return False


@admin.register(PulseIndicatorConfigModel)
class PulseIndicatorConfigAdmin(TypedModelAdmin[PulseIndicatorConfigModel]):
    form = PulseIndicatorConfigAdminForm
    list_display = [
        "indicator_code",
        "indicator_name",
        "dimension",
        "frequency",
        "signal_type",
        "weight",
        "is_active",
    ]
    list_filter = ["dimension", "frequency", "signal_type", "is_active"]
    search_fields = ["indicator_code", "indicator_name"]
    ordering = ["dimension", "indicator_code"]


@admin.register(NavigatorAssetConfigModel)
class NavigatorAssetConfigAdmin(TypedModelAdmin[NavigatorAssetConfigModel]):
    form = NavigatorAssetConfigAdminForm
    list_display = [
        "regime_name",
        "risk_budget",
        "is_active",
        "updated_at",
    ]
    list_filter = ["regime_name", "is_active"]
    ordering = ["regime_name"]
