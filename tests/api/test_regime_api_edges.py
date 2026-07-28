from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.regime.infrastructure.models import RegimeLog, RegimeThresholdConfig


@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username="regime-edge", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_regime_interface_resolves_current_provider_at_call_time(monkeypatch):
    """A temporary resolver patch must not be captured during lazy module import."""

    from apps.regime.application import current_regime, interface_services

    observed_at = date(2026, 7, 27)
    monkeypatch.setattr(
        current_regime,
        "resolve_current_regime",
        lambda *, as_of_date: SimpleNamespace(
            observed_at=as_of_date,
            dominant_regime="Recovery",
            confidence=0.8,
            growth_momentum_z=0.4,
            inflation_momentum_z=-0.2,
            distribution={"Recovery": 0.8},
            data_source="test",
            growth_level="up",
            inflation_level="down",
            growth_indicator="PMI",
            inflation_indicator="CPI",
            growth_value=50.3,
            inflation_value=0.1,
            is_fallback=False,
            warnings=[],
        ),
    )

    payload = interface_services.get_regime_current_payload(as_of_date=observed_at)

    assert payload["data"]["observed_at"] == observed_at
    assert payload["data"]["dominant_regime"] == "Recovery"


@pytest.mark.django_db
def test_regime_navigator_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/regime/navigator/?as_of_date=2026/04/02")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "Invalid as_of_date" in payload["error"]


@pytest.mark.django_db
def test_regime_action_invalid_date_returns_400(authenticated_client):
    response = authenticated_client.get("/api/regime/action/?as_of_date=2026/04/02")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "Invalid as_of_date" in payload["error"]


@pytest.mark.django_db
def test_regime_history_returns_canonical_envelope(authenticated_client):
    history_payload = {
        "success": True,
        "count": 1,
        "data": [
            {
                "id": 7,
                "observed_at": "2026-07-09",
                "dominant_regime": "Recovery",
                "confidence": 0.82,
                "growth_momentum_z": 0.5,
                "inflation_momentum_z": -0.2,
                "distribution": {"Recovery": 0.82},
                "created_at": "2026-07-09T08:00:00+08:00",
            }
        ],
    }

    with patch(
        "apps.regime.interface.api_views.get_regime_history_payload",
        return_value=history_payload,
    ) as mocked:
        response = authenticated_client.get(
            "/api/regime/history/?start_date=2026-07-01&end_date=2026-07-10&limit=1"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["data"][0]["dominant_regime"] == "Recovery"
    mocked.assert_called_once()


@pytest.mark.django_db
def test_regime_history_page_parameter_returns_distinct_slices(authenticated_client):
    for index in range(3):
        RegimeLog.objects.create(
            observed_at=date(2026, 7, 10) - timedelta(days=index),
            dominant_regime="Recovery",
            confidence=0.8,
            growth_momentum_z=0.3 + index,
            inflation_momentum_z=-0.2,
            distribution={"Recovery": 0.8, "Deflation": 0.2},
        )

    first_page = authenticated_client.get("/api/regime/history/?page=1&limit=2")
    second_page = authenticated_client.get("/api/regime/history/?page=2&limit=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_payload = first_page.json()
    second_payload = second_page.json()
    assert [item["id"] for item in first_payload["data"]] != [
        item["id"] for item in second_payload["data"]
    ]
    assert first_payload["total"] == 3
    assert first_payload["page"] == 1
    assert first_payload["total_pages"] == 2
    assert second_payload["page"] == 2
    assert second_payload["count"] == 1


@pytest.mark.django_db
def test_regime_history_rejects_invalid_page_with_public_400_contract(authenticated_client):
    response = authenticated_client.get("/api/regime/history/?page=abc")

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is False
    assert "page" in payload["error"]
    assert "500" not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_regime_calculate_marks_missing_trend_z_scores_unavailable(authenticated_client):
    v2_response = SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            confidence=0.25,
            distribution={"Recovery": 1.0},
            trend_indicators=[],
        ),
        warnings=[],
        error=None,
        raw_data={},
    )
    with patch(
        "apps.regime.application.interface_services.CalculateRegimeV2UseCase.execute",
        return_value=v2_response,
    ):
        response = authenticated_client.post(
            "/api/regime/calculate/",
            {"as_of_date": "2026-07-20"},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["growth_momentum_z"] is None
    assert payload["snapshot"]["inflation_momentum_z"] is None
    assert any("PMI" in warning and "不可用" in warning for warning in payload["warnings"])
    assert any("CPI" in warning and "不可用" in warning for warning in payload["warnings"])


@pytest.mark.django_db
def test_regime_distribution_returns_canonical_envelope(authenticated_client):
    distribution_payload = {
        "success": True,
        "total": 4,
        "distribution": [
            {
                "dominant_regime": "Recovery",
                "count": 2,
                "percentage": 50.0,
            },
            {
                "dominant_regime": "Overheat",
                "count": 1,
                "percentage": 25.0,
            },
            {
                "dominant_regime": "Deflation",
                "count": 1,
                "percentage": 25.0,
            },
        ],
    }

    with patch(
        "apps.regime.interface.api_views.get_regime_distribution_payload",
        return_value=distribution_payload,
    ) as mocked:
        response = authenticated_client.get(
            "/api/regime/distribution/?start_date=2026-07-01&end_date=2026-07-10"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload == distribution_payload
    mocked.assert_called_once_with(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 10),
    )


@pytest.mark.django_db
def test_regime_distribution_rejects_invalid_date_before_application(
    authenticated_client,
):
    response = authenticated_client.get("/api/regime/distribution/?start_date=not-a-date")

    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json()["success"] is False


@pytest.mark.django_db
def test_regime_calculate_is_strict_persisted_only_pure_compute(authenticated_client):
    as_of_date = date(2026, 7, 10)
    for code, name in (
        ("CN_PMI", "采购经理指数"),
        ("CN_CPI_NATIONAL_YOY", "全国 CPI 同比"),
    ):
        IndicatorCatalogModel.objects.update_or_create(
            code=code,
            defaults={
                "name_cn": name,
                "default_unit": "%",
                "default_period_type": "M",
                "extra": {"series_semantics": "index_level" if code == "CN_PMI" else "yoy_rate"},
            },
        )

    for months_ago, pmi, cpi in (
        (2, 49.5, 2.4),
        (1, 50.1, 2.1),
        (0, 50.8, 1.8),
    ):
        reporting_period = as_of_date - timedelta(days=30 * months_ago)
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=reporting_period,
            value=Decimal(str(pmi)),
            unit="指数",
            source="akshare",
            published_at=reporting_period,
        )
        MacroFactModel.objects.create(
            indicator_code="CN_CPI_NATIONAL_YOY",
            reporting_period=reporting_period,
            value=Decimal(str(cpi)),
            unit="%",
            source="akshare",
            published_at=reporting_period,
        )

    before_counts = {
        "regime_logs": RegimeLog.objects.count(),
        "threshold_configs": RegimeThresholdConfig.objects.count(),
        "indicator_catalog": IndicatorCatalogModel.objects.count(),
        "macro_facts": MacroFactModel.objects.count(),
    }
    request_data = {
        "as_of_date": as_of_date,
        "use_pit": True,
        "growth_indicator": "PMI",
        "inflation_indicator": "CPI",
        "data_source": "akshare",
    }

    from apps.regime.application.interface_services import calculate_regime_payload

    with patch("apps.regime.application.interface_services.cache.set") as cache_set:
        direct_payload = calculate_regime_payload(data=request_data)

    assert direct_payload["success"] is True
    cache_set.assert_not_called()

    with (
        patch(
            "apps.regime.infrastructure.repositories.DjangoRegimeRepository.save_snapshot",
            side_effect=AssertionError("pure calculation must not persist RegimeLog"),
        ),
        patch(
            "apps.regime.application.repository_provider.build_macro_sync_task_gateway",
            side_effect=AssertionError("pure calculation must not trigger macro sync"),
        ),
    ):
        response = authenticated_client.post(
            "/api/regime/calculate/",
            {
                **request_data,
                "as_of_date": as_of_date.isoformat(),
            },
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["snapshot"]["observed_at"] == as_of_date.isoformat()
    assert payload["snapshot"]["dominant_regime"] in {
        "Recovery",
        "Overheat",
        "Stagflation",
        "Deflation",
    }
    assert payload["raw_data"]["growth"][-1]["value"] == 50.8
    assert payload["raw_data"]["inflation"][-1]["value"] == 1.8
    assert {
        "regime_logs": RegimeLog.objects.count(),
        "threshold_configs": RegimeThresholdConfig.objects.count(),
        "indicator_catalog": IndicatorCatalogModel.objects.count(),
        "macro_facts": MacroFactModel.objects.count(),
    } == before_counts


@pytest.mark.django_db
def test_regime_current_exposes_latest_macro_values_and_directions(authenticated_client):
    as_of_date = date.today()
    for code, name, unit in (
        ("CN_PMI", "采购经理指数", "指数"),
        ("CN_CPI_NATIONAL_YOY", "全国 CPI 同比", "%"),
    ):
        IndicatorCatalogModel.objects.update_or_create(
            code=code,
            defaults={
                "name_cn": name,
                "default_unit": unit,
                "default_period_type": "M",
            },
        )
    for days_ago, pmi, cpi in ((60, 49.8, 0.3), (30, 50.1, 0.2), (0, 50.3, 0.1)):
        reporting_period = as_of_date - timedelta(days=days_ago)
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=reporting_period,
            value=Decimal(str(pmi)),
            unit="指数",
            source="akshare",
            published_at=reporting_period,
        )
        MacroFactModel.objects.create(
            indicator_code="CN_CPI_NATIONAL_YOY",
            reporting_period=reporting_period,
            value=Decimal(str(cpi)),
            unit="%",
            source="akshare",
            published_at=reporting_period,
        )

    response = authenticated_client.get("/api/regime/current/")

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["growth_level"] == "up"
    assert data["inflation_level"] == "down"
    assert data["growth_indicator"] == "PMI"
    assert data["inflation_indicator"] == "CPI"
    assert data["growth_value"] == pytest.approx(50.3)
    assert data["inflation_value"] == pytest.approx(0.1)
    assert data["growth_momentum_z"] != 0.0
    assert data["inflation_momentum_z"] != 0.0


@pytest.mark.django_db
def test_read_only_token_can_call_regime_pure_compute() -> None:
    user = User.objects.create_user(username="regime-readonly-compute", password="pass")
    _, raw_key = UserAccessTokenModel.create_token(
        user=user,
        name="readonly-regime",
        access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {raw_key}")

    response = client.post("/api/regime/calculate/", {}, format="json")

    assert response.status_code != 403


@pytest.mark.django_db
def test_regime_calculate_rejects_unknown_fields(authenticated_client):
    response = authenticated_client.post(
        "/api/regime/calculate/",
        {"use_kalman": True},
        format="json",
    )

    assert response.status_code == 400
    assert "Unknown fields: use_kalman" in str(response.json())
