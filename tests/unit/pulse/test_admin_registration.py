"""Pulse Admin discovery, immutability, and numeric validation regressions."""

from __future__ import annotations

import math

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError

from apps.pulse.interface.admin import (
    NavigatorAssetConfigAdmin,
    NavigatorAssetConfigAdminForm,
    PulseIndicatorConfigAdmin,
    PulseIndicatorConfigAdminForm,
    PulseLogAdmin,
)
from apps.pulse.models import NavigatorAssetConfigModel, PulseIndicatorConfigModel, PulseLog
from shared.infrastructure.django_admin import TypedModelAdmin, TypedModelForm


def test_pulse_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery exposes all Pulse runtime governance models."""

    expected = {
        PulseLog: PulseLogAdmin,
        PulseIndicatorConfigModel: PulseIndicatorConfigAdmin,
        NavigatorAssetConfigModel: NavigatorAssetConfigAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)
    assert issubclass(PulseIndicatorConfigAdminForm, TypedModelForm)
    assert issubclass(NavigatorAssetConfigAdminForm, TypedModelForm)


def test_pulse_log_admin_is_fully_immutable() -> None:
    """Calculated Pulse evidence cannot be fabricated, changed, or deleted."""

    pulse_admin = admin.site._registry[PulseLog]
    assert pulse_admin.has_add_permission(None) is False
    assert pulse_admin.has_change_permission(None) is False
    assert pulse_admin.has_delete_permission(None) is False


@pytest.mark.parametrize("weight", [0.0, -1.0, float("nan"), float("inf"), True])
def test_indicator_weight_form_rejects_non_positive_or_non_finite_values(weight: object) -> None:
    """Invalid weights cannot enter runtime config through changelist or change forms."""

    form = PulseIndicatorConfigAdminForm()
    form.cleaned_data = {"weight": weight}
    with pytest.raises(ValidationError):
        form.clean_weight()


@pytest.mark.parametrize("risk_budget", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_navigator_form_rejects_out_of_range_risk_budget(risk_budget: object) -> None:
    """Navigator risk budget remains a finite normalized ratio."""

    form = NavigatorAssetConfigAdminForm()
    form.cleaned_data = {"risk_budget": risk_budget}
    with pytest.raises(ValidationError):
        form.clean_risk_budget()


def test_pulse_admin_forms_accept_valid_numeric_boundaries() -> None:
    """Valid positive weights and normalized risk endpoints remain accepted."""

    indicator_form = PulseIndicatorConfigAdminForm()
    indicator_form.cleaned_data = {"weight": 2.5}
    assert math.isclose(indicator_form.clean_weight(), 2.5)
    navigator_form = NavigatorAssetConfigAdminForm()
    navigator_form.cleaned_data = {"risk_budget": 1.0}
    assert math.isclose(navigator_form.clean_risk_budget(), 1.0)
