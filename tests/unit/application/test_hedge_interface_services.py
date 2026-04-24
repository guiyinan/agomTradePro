from datetime import date

import pytest

from apps.hedge.application import interface_services
from apps.hedge.infrastructure.models import HedgeAlertModel, HedgePairModel


@pytest.mark.django_db
def test_activate_hedge_pair_updates_model_state():
    pair = HedgePairModel.objects.create(
        name="CSI300-10Y",
        long_asset="510300",
        hedge_asset="511260",
        is_active=False,
    )

    response = interface_services.activate_hedge_pair(pair_id=pair.id)

    pair.refresh_from_db()
    assert response.success is True
    assert pair.is_active is True


@pytest.mark.django_db
def test_resolve_hedge_alert_marks_alert_resolved():
    alert = HedgeAlertModel.objects.create(
        pair_name="CSI300-10Y",
        alert_date=date(2026, 4, 23),
        alert_type="correlation_breakdown",
        severity="high",
        message="Correlation drifted outside threshold",
    )

    response = interface_services.resolve_hedge_alert(alert_id=alert.id)

    alert.refresh_from_db()
    assert response.success is True
    assert alert.is_resolved is True
    assert alert.resolved_at is not None
