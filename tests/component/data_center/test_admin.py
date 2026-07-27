"""Data Center Admin security and singleton-permission regression tests."""

from unittest.mock import Mock

import pytest
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from apps.data_center.interface import admin as data_center_admin
from apps.data_center.models import (
    DataProviderSettingsModel,
    ProductionCoverageUniverseConfigModel,
    ProviderConfigModel,
)


def _admin_request(*, has_permission: bool):
    request = RequestFactory().get("/admin/data-center/")
    request.user = Mock(has_perm=Mock(return_value=has_permission))
    return request


def test_provider_credentials_are_not_rendered_back_to_browser():
    """Editing a provider must render empty password inputs, not stored secrets."""

    provider = ProviderConfigModel(
        pk=7,
        name="primary",
        source_type="tushare",
        api_key="stored-api-key",
        api_secret="stored-api-secret",
    )

    form = data_center_admin.ProviderConfigAdminForm(instance=provider)

    assert "stored-api-key" not in str(form["api_key"])
    assert "stored-api-secret" not in str(form["api_secret"])
    assert form.fields["api_key"].widget.render_value is False
    assert form.fields["api_secret"].widget.render_value is False


@pytest.mark.django_db
def test_blank_masked_credentials_preserve_existing_values():
    """Submitting the masked edit form blank must not erase stored credentials."""

    provider = ProviderConfigModel(
        pk=7,
        name="primary",
        source_type="tushare",
        api_key="stored-api-key",
        api_secret="stored-api-secret",
    )
    form = data_center_admin.ProviderConfigAdminForm(
        data={
            "name": "primary",
            "source_type": "tushare",
            "is_active": "on",
            "priority": "100",
            "api_key": "",
            "api_secret": "",
            "http_url": "",
            "api_endpoint": "",
            "extra_config": "{}",
            "description": "",
        },
        instance=provider,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["api_key"] == "stored-api-key"
    assert form.cleaned_data["api_secret"] == "stored-api-secret"


@pytest.mark.parametrize(
    ("admin_class", "model", "singleton_check"),
    [
        (
            data_center_admin.DataProviderSettingsAdmin,
            DataProviderSettingsModel,
            "provider_settings",
        ),
        (
            data_center_admin.ProductionCoverageUniverseConfigAdmin,
            ProductionCoverageUniverseConfigModel,
            "coverage_universe",
        ),
    ],
)
def test_singleton_add_permission_rejects_staff_without_model_permission(
    monkeypatch,
    admin_class,
    model,
    singleton_check,
):
    """Singleton availability must never bypass Django's model permission."""

    if singleton_check == "provider_settings":
        availability = Mock(return_value=True)
        monkeypatch.setattr(data_center_admin, "can_create_provider_settings", availability)
    else:
        availability = Mock(return_value=False)
        monkeypatch.setattr(model.objects, "exists", availability)

    model_admin = admin_class(model, AdminSite())

    assert model_admin.has_add_permission(_admin_request(has_permission=False)) is False
    availability.assert_not_called()


@pytest.mark.parametrize(
    ("admin_class", "model"),
    [
        (data_center_admin.DataProviderSettingsAdmin, DataProviderSettingsModel),
        (
            data_center_admin.ProductionCoverageUniverseConfigAdmin,
            ProductionCoverageUniverseConfigModel,
        ),
    ],
)
def test_singleton_admin_never_allows_delete(admin_class, model):
    """Critical global singleton rows remain non-deletable in Admin."""

    model_admin = admin_class(model, AdminSite())

    assert model_admin.has_delete_permission(_admin_request(has_permission=True)) is False
