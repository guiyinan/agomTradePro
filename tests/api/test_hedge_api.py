from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.hedge.infrastructure.models import HedgePairModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="hedge_user",
        password="testpass123",
        email="hedge@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def staff_client(api_client, db):
    staff_user = get_user_model().objects.create_user(
        username="hedge_admin",
        password="testpass123",
        is_staff=True,
    )
    api_client.force_authenticate(user=staff_user)
    return api_client


@pytest.fixture
def hedge_pair(db):
    return HedgePairModel.objects.create(
        name="股债对冲",
        long_asset="510300",
        hedge_asset="511260",
        hedge_method="beta",
    )


@pytest.mark.django_db
def test_pair_catalog_and_detail_return_persisted_contract(
    authenticated_client,
    hedge_pair,
):
    list_response = authenticated_client.get("/api/hedge/pairs/")
    detail_response = authenticated_client.get(f"/api/hedge/pairs/{hedge_pair.id}/")

    assert list_response.status_code == 200
    list_payload = list_response.json()
    rows = list_payload.get("results", list_payload)
    assert any(row["name"] == "股债对冲" for row in rows)

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["name"] == "股债对冲"
    assert detail_payload["hedge_method"] == "beta"


@pytest.mark.django_db
def test_active_alerts_return_canonical_list(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_recent_alerts_payload",
        return_value=[
            {
                "id": 9,
                "pair_name": "股债对冲",
                "severity": "warning",
                "is_resolved": False,
            }
        ],
    ) as mock_alerts:
        response = authenticated_client.get("/api/hedge/alerts/active/?days=7")

    assert response.status_code == 200
    assert response.json()[0]["severity"] == "warning"
    mock_alerts.assert_called_once_with(days=7)


@pytest.mark.django_db
def test_latest_snapshots_return_persisted_state_contract(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_latest_snapshots_payload",
        return_value=[
            {
                "pair_name": "股债对冲",
                "trade_date": "2026-07-10",
                "hedge_effectiveness": 0.72,
            }
        ],
    ) as mock_snapshots:
        response = authenticated_client.get("/api/hedge/snapshots/latest/")

    assert response.status_code == 200
    assert response.json()[0]["hedge_effectiveness"] == 0.72
    mock_snapshots.assert_called_once_with()


@pytest.mark.django_db
def test_latest_snapshots_fail_closed_when_persisted_state_is_stale(
    authenticated_client,
    hedge_pair,
):
    """The endpoint must expose source age and block stale hedge decisions."""

    from datetime import date

    from apps.hedge.infrastructure.models import HedgePortfolioSnapshotModel

    HedgePortfolioSnapshotModel.objects.create(
        pair=hedge_pair,
        trade_date=date(2020, 1, 2),
        long_weight=0.6,
        hedge_weight=0.4,
        hedge_ratio=0.7,
        current_correlation=-0.6,
        hedge_effectiveness=0.8,
    )

    response = authenticated_client.get("/api/hedge/snapshots/latest/")

    assert response.status_code == 200
    row = response.json()["results"][0]
    assert row["observed_at"] == "2020-01-02"
    assert row["freshness_status"] == "stale"
    assert row["staleness_days"] > 1
    assert row["is_stale"] is True
    assert row["must_not_use_for_decision"] is True
    assert row["blocked_reason"] == "hedge_snapshot_stale"


@pytest.mark.django_db
def test_pairs_correlation_matrix_uses_asset_codes_and_window_days(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_matrix_payload",
        return_value={
            "asset_codes": ["510300", "511260"],
            "window_days": 30,
            "matrix": [[1.0, -0.42], [-0.42, 1.0]],
        },
    ) as mock_matrix:
        response = authenticated_client.post(
            "/api/hedge/pairs/correlation_matrix/",
            {"asset_codes": ["510300", "511260"], "window_days": 30},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_codes"] == ["510300", "511260"]
    assert payload["window_days"] == 30
    assert payload["matrix"] == [[1.0, -0.42], [-0.42, 1.0]]
    mock_matrix.assert_called_once_with(asset_codes=["510300", "511260"], window_days=30)


@pytest.mark.django_db
def test_actions_correlation_matrix_is_pure_calculation(authenticated_client):
    from apps.hedge.infrastructure.models import (
        CorrelationHistoryModel,
        HedgeAlertModel,
        HedgePortfolioSnapshotModel,
    )

    class _ReadOnlyPrices:
        def get_asset_prices(
            self,
            asset_code,
            end_date,
            days,
            *,
            cache_result=True,
        ):
            assert cache_result is False
            base = 10.0 if asset_code == "510300" else 20.0
            return [base + index for index in range(days)]

    tracked_models = (
        CorrelationHistoryModel,
        HedgeAlertModel,
        HedgePortfolioSnapshotModel,
    )
    before = {model: model.objects.count() for model in tracked_models}

    with patch(
        "apps.hedge.infrastructure.services.get_hedge_adapter",
        return_value=_ReadOnlyPrices(),
    ):
        response = authenticated_client.post(
            "/api/hedge/actions/get_correlation_matrix/",
            {"asset_codes": ["510300", "511260"], "window_days": 30},
            format="json",
        )

    after = {model: model.objects.count() for model in tracked_models}
    assert response.status_code == 200
    assert response.json()["asset_codes"] == ["510300", "511260"]
    assert response.json()["window_days"] == 30
    assert response.json()["matrix"]["510300"]["510300"] == 1.0
    assert after == before


@pytest.mark.django_db
def test_pair_effectiveness_is_authenticated_pure_calculation(
    authenticated_client,
    hedge_pair,
):
    from apps.hedge.infrastructure.models import (
        CorrelationHistoryModel,
        HedgeAlertModel,
        HedgePerformanceModel,
        HedgePortfolioSnapshotModel,
    )

    class _ReadOnlyPrices:
        def get_asset_prices(
            self,
            asset_code,
            end_date,
            days,
            *,
            cache_result=True,
        ):
            assert cache_result is False
            if asset_code == "510300":
                return [100.0 + index for index in range(days)]
            return [200.0 - index for index in range(days)]

    tracked_models = (
        CorrelationHistoryModel,
        HedgeAlertModel,
        HedgePerformanceModel,
        HedgePortfolioSnapshotModel,
    )
    before = {model: model._default_manager.count() for model in tracked_models}

    with patch(
        "apps.hedge.infrastructure.services.get_hedge_adapter",
        return_value=_ReadOnlyPrices(),
    ):
        response = authenticated_client.post(
            f"/api/hedge/pairs/{hedge_pair.id}/check_effectiveness/",
            {},
            format="json",
        )

    after = {model: model._default_manager.count() for model in tracked_models}
    assert response.status_code == 200
    assert response.json()["pair_name"] == hedge_pair.name
    assert response.json()["effectiveness"] >= 0.95
    assert after == before


@pytest.mark.django_db
def test_pair_effectiveness_rejects_unauthenticated_access(api_client, hedge_pair):
    response = api_client.post(
        f"/api/hedge/pairs/{hedge_pair.id}/check_effectiveness/",
        {},
        format="json",
    )

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_actions_check_hedge_ratio_requires_pair_name(authenticated_client):
    response = authenticated_client.post("/api/hedge/actions/check_hedge_ratio/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"] == "pair_name is required"


@pytest.mark.django_db
def test_actions_check_hedge_ratio_returns_not_found_for_unknown_pair(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_hedge_ratio_payload",
        return_value=None,
    ) as mock_ratio:
        response = authenticated_client.post(
            "/api/hedge/actions/check_hedge_ratio/",
            {"pair_name": "missing-pair"},
            format="json",
        )

    assert response.status_code == 404
    assert response.json()["error"] == "Hedge pair not found: missing-pair"
    mock_ratio.assert_called_once_with(pair_name="missing-pair")


@pytest.mark.django_db
def test_actions_calculate_correlation_returns_metric_payload(authenticated_client):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_metric_payload",
        return_value={
            "asset1": "510300",
            "asset2": "511260",
            "calc_date": "2026-04-02",
            "window_days": 45,
            "correlation": -0.6382,
            "covariance": -0.1294,
            "beta": 0.7421,
            "correlation_trend": "down",
            "correlation_ma": -0.6011,
            "alert": "correlation weakening",
            "alert_type": "correlation_breakdown",
        },
    ) as mock_calc:
        response = authenticated_client.post(
            "/api/hedge/actions/calculate_correlation/",
            {"asset1": "510300", "asset2": "511260", "window_days": 45},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset1"] == "510300"
    assert payload["asset2"] == "511260"
    assert payload["window_days"] == 45
    assert payload["correlation"] == -0.6382
    assert payload["beta"] == 0.7421
    assert payload["alert_type"] == "correlation_breakdown"
    mock_calc.assert_called_once_with(asset1="510300", asset2="511260", window_days=45)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/hedge/pairs/",
            {
                "name": "unauthorized pair",
                "long_asset": "510300",
                "hedge_asset": "511260",
                "hedge_method": "beta",
            },
        ),
        ("/api/hedge/snapshots/update_all/", {}),
        ("/api/hedge/alerts/monitor/", {}),
    ],
)
def test_regular_user_cannot_mutate_hedge_state(
    authenticated_client,
    path,
    payload,
):
    response = authenticated_client.post(path, payload, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_staff_can_run_hedge_monitor(staff_client):
    with patch(
        "apps.hedge.interface.views.interface_services.monitor_hedge_pairs_payload",
        return_value={"generated_alerts": 2, "alerts": []},
    ) as monitor:
        response = staff_client.post("/api/hedge/alerts/monitor/", {}, format="json")

    assert response.status_code == 200
    assert response.json()["generated_alerts"] == 2
    monitor.assert_called_once_with()


@pytest.mark.django_db
def test_correlation_matrix_rejects_unbounded_asset_list_before_service(
    authenticated_client,
):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_matrix_payload"
    ) as matrix:
        response = authenticated_client.post(
            "/api/hedge/actions/get_correlation_matrix/",
            {
                "asset_codes": [f"ASSET{index}" for index in range(51)],
                "window_days": 60,
            },
            format="json",
        )

    assert response.status_code == 400
    matrix.assert_not_called()


@pytest.mark.django_db
def test_pairwise_correlation_rejects_same_asset_and_oversized_window(
    authenticated_client,
):
    with patch(
        "apps.hedge.interface.views.interface_services.get_correlation_metric_payload"
    ) as calculate:
        same_asset = authenticated_client.post(
            "/api/hedge/actions/calculate_correlation/",
            {"asset1": "510300", "asset2": "510300", "window_days": 60},
            format="json",
        )
        oversized = authenticated_client.post(
            "/api/hedge/actions/calculate_correlation/",
            {"asset1": "510300", "asset2": "511260", "window_days": 5001},
            format="json",
        )

    assert same_asset.status_code == 400
    assert oversized.status_code == 400
    calculate.assert_not_called()


@pytest.mark.django_db
def test_active_alerts_reject_invalid_days_instead_of_silent_default(
    authenticated_client,
):
    with patch("apps.hedge.interface.views.interface_services.get_recent_alerts_payload") as alerts:
        response = authenticated_client.get("/api/hedge/alerts/active/?days=0")

    assert response.status_code == 400
    alerts.assert_not_called()


@pytest.mark.django_db
def test_hedge_html_write_endpoint_requires_staff(client, auth_user):
    client.force_login(auth_user)

    response = client.post("/hedge/portfolios/update/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
