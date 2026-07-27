"""Asset Analysis Admin discovery, permissions, and transition contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib import admin
from django.core.exceptions import PermissionDenied

from apps.asset_analysis.interface.admin import (
    AssetAnalysisAlertAdmin,
    AssetScoreCacheAdmin,
    AssetScoringLogAdmin,
    WeightConfigAdmin,
)
from apps.asset_analysis.models import (
    AssetAnalysisAlert,
    AssetScoreCache,
    AssetScoringLog,
    WeightConfigModel,
)
from shared.infrastructure.django_admin import TypedModelAdmin


def test_asset_analysis_models_are_registered_once_through_typed_admins() -> None:
    """Django autodiscovery exposes all four Asset Analysis operations models."""

    expected = {
        WeightConfigModel: WeightConfigAdmin,
        AssetScoreCache: AssetScoreCacheAdmin,
        AssetScoringLog: AssetScoringLogAdmin,
        AssetAnalysisAlert: AssetAnalysisAlertAdmin,
    }
    for model, admin_class in expected.items():
        assert admin.site.is_registered(model)
        assert isinstance(admin.site._registry[model], admin_class)
        assert issubclass(admin_class, TypedModelAdmin)


@pytest.mark.django_db
def test_resolve_action_updates_only_unresolved_alerts(django_user_model: type) -> None:
    """Repeated actions preserve the original resolver and timestamp of terminal rows."""

    operator = django_user_model.objects.create_user(username="asset-alert-operator")
    old_timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    resolved = AssetAnalysisAlert.objects.create(
        severity="warning",
        alert_type="data_quality",
        title="resolved",
        message="already handled",
        is_resolved=True,
        resolved_at=old_timestamp,
        resolved_by=999,
    )
    pending = AssetAnalysisAlert.objects.create(
        severity="warning",
        alert_type="data_quality",
        title="pending",
        message="needs review",
    )
    alert_admin = admin.site._registry[AssetAnalysisAlert]
    alert_admin.message_user = Mock()
    request = SimpleNamespace(user=operator)

    alert_admin.mark_as_resolved(
        request,
        AssetAnalysisAlert.objects.filter(pk__in=[resolved.pk, pending.pk]),
    )

    resolved.refresh_from_db()
    pending.refresh_from_db()
    assert resolved.resolved_at == old_timestamp
    assert resolved.resolved_by == 999
    assert pending.is_resolved is True
    assert pending.resolved_by == operator.pk
    alert_admin.message_user.assert_called_once_with(request, "已标记 1 条告警为已解决")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "user",
    [
        SimpleNamespace(is_authenticated=False, pk=None),
        SimpleNamespace(is_authenticated=True, pk=None),
    ],
)
def test_resolve_action_rejects_unpersisted_or_anonymous_operator(user: object) -> None:
    """An alert transition always has a durable authenticated resolver identity."""

    alert_admin = admin.site._registry[AssetAnalysisAlert]
    request = SimpleNamespace(user=user)
    with pytest.raises(PermissionDenied, match="persisted ID"):
        alert_admin.mark_as_resolved(request, AssetAnalysisAlert.objects.none())
