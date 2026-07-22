from datetime import date
from unittest.mock import patch

import pytest

from apps.hedge.application import interface_services
from apps.hedge.application.dtos import HedgeEffectivenessRequest
from apps.hedge.application.use_cases import (
    CheckHedgeEffectivenessUseCase,
    HedgeUseCaseContext,
)
from apps.hedge.domain.entities import HedgeAlertType, HedgeMethod, HedgePair
from apps.hedge.infrastructure.models import (
    HedgeAlertModel,
    HedgePairModel,
    HedgePerformanceModel,
)
from apps.hedge.infrastructure.services import HedgeIntegrationService


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


@pytest.mark.django_db
def test_alert_page_can_filter_resolved_alerts():
    resolved = HedgeAlertModel.objects.create(
        pair_name="CSI300-10Y",
        alert_date=date.today(),
        alert_type="correlation_breakdown",
        severity="high",
        message="Resolved alert",
        is_resolved=True,
    )
    HedgeAlertModel.objects.create(
        pair_name="CSI300-10Y",
        alert_date=date.today(),
        alert_type="beta_change",
        severity="medium",
        message="Active alert",
        is_resolved=False,
    )

    context = interface_services.get_hedge_alerts_page_context(
        pair_name=None,
        severity=None,
        alert_type=None,
        is_resolved=True,
        filter_pair_name="",
        filter_severity="",
        filter_alert_type="",
        filter_is_resolved="true",
    )

    assert [alert["id"] for alert in context["alerts"]] == [resolved.id]


def test_effectiveness_use_case_reports_unavailable_market_data():
    pair = HedgePair(
        name="CSI300-10Y",
        long_asset="510300",
        hedge_asset="511260",
        hedge_method=HedgeMethod.BETA,
        target_long_weight=0.7,
    )
    context = HedgeUseCaseContext(
        calc_date=date.today(),
        hedge_pairs=[pair],
        get_asset_prices=lambda _code, _end_date, _days: None,
        get_asset_name=lambda code: code,
        get_hedge_pair=lambda name: pair if name == pair.name else None,
    )

    with pytest.raises(ValueError, match="Unable to calculate hedge effectiveness"):
        CheckHedgeEffectivenessUseCase(context).execute(
            HedgeEffectivenessRequest(pair_name=pair.name)
        )


@pytest.mark.django_db
def test_calculate_performance_persists_the_model_contract():
    HedgePairModel.objects.create(
        name="CSI300-10Y",
        long_asset="510300",
        hedge_asset="511260",
        hedge_method="beta",
        target_long_weight=0.7,
        target_hedge_weight=0.3,
    )

    class _Prices:
        def get_asset_prices(
            self,
            asset_code,
            _end_date,
            days,
            *,
            cache_result=True,
        ):
            del cache_result
            if asset_code == "510300":
                return [100.0 + index for index in range(days)]
            return [200.0 - index for index in range(days)]

    with patch(
        "apps.hedge.infrastructure.services.get_hedge_adapter",
        return_value=_Prices(),
    ):
        result = HedgeIntegrationService().calculate_performance(
            "CSI300-10Y",
            date(2026, 7, 23),
        )

    assert result is not None
    persisted = HedgePerformanceModel.objects.get(pair_name="CSI300-10Y")
    assert persisted.period_end == date(2026, 7, 23)
    assert persisted.total_return == pytest.approx(result.total_return)
    assert persisted.hedge_effectiveness == pytest.approx(result.hedge_effectiveness)


def test_portfolio_returns_tolerate_misaligned_and_zero_price_series():
    with patch(
        "apps.hedge.infrastructure.services.get_hedge_adapter",
        return_value=object(),
    ):
        service = HedgeIntegrationService()

    returns = service._calculate_portfolio_returns(
        long_prices=[0.0, 100.0, 102.0, 103.0],
        hedge_prices=[50.0, 49.0, 48.0],
        long_weight=0.7,
        hedge_weight=0.3,
    )

    assert returns == pytest.approx(
        [((102.0 - 100.0) / 100.0) * 0.7 + ((48.0 - 49.0) / 49.0) * 0.3]
    )


@pytest.mark.django_db
def test_unknown_persisted_alert_type_stays_unknown():
    model = HedgeAlertModel.objects.create(
        pair_name="CSI300-10Y",
        alert_date=date.today(),
        alert_type="future_alert_type",
        severity="medium",
        message="Unknown alert",
    )

    assert model.to_domain().alert_type is HedgeAlertType.UNKNOWN
