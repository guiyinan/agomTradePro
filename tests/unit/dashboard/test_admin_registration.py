"""Dashboard Admin discovery and typing regressions."""

from __future__ import annotations

from django.contrib import admin

from apps.dashboard.admin import (
    DashboardAlertAdmin,
    DashboardCardAdmin,
    DashboardConfigAdmin,
    DashboardSnapshotAdmin,
    DashboardUserConfigAdmin,
)
from apps.dashboard.infrastructure.models import (
    DashboardAlertModel,
    DashboardCardModel,
    DashboardConfigModel,
    DashboardSnapshotModel,
    DashboardUserConfigModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_dashboard_models_use_the_canonical_root_admin_entrypoint() -> None:
    """All Dashboard models are discoverable and registered exactly once."""

    expected = {
        DashboardConfigModel: DashboardConfigAdmin,
        DashboardUserConfigModel: DashboardUserConfigAdmin,
        DashboardCardModel: DashboardCardAdmin,
        DashboardAlertModel: DashboardAlertAdmin,
        DashboardSnapshotModel: DashboardSnapshotAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


def test_dashboard_snapshot_admin_is_immutable() -> None:
    """Operators cannot create or mutate captured snapshots through Admin."""

    snapshot_admin = admin.site._registry[DashboardSnapshotModel]
    assert snapshot_admin.has_add_permission(None) is False
    assert snapshot_admin.has_change_permission(None) is False
