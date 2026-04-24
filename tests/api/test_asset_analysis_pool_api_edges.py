import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.asset_analysis.infrastructure.models import AssetPoolEntry


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="asset_pool_user",
        password="testpass123",
        email="asset-pool@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_asset_pool_summary_contract(authenticated_client):
    response = authenticated_client.get("/api/asset-analysis/pool-summary/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["asset_type"] == "all"
    assert payload["summary"]["investable"] == 0
    assert payload["summary"]["prohibited"] == 0
    assert payload["summary"]["watch"] == 0
    assert payload["summary"]["candidate"] == 0
    assert payload["summary"]["total"] == 0


@pytest.mark.django_db
def test_asset_pool_summary_filters_by_asset_type(authenticated_client):
    AssetPoolEntry.objects.create(
        asset_category="equity",
        asset_code="000001.SH",
        asset_name="Ping An Bank",
        pool_type="investable",
        total_score=81.0,
        regime_score=80.0,
        policy_score=78.0,
        sentiment_score=82.0,
        signal_score=76.0,
        entry_date="2026-04-23",
        risk_level="中风险",
    )
    AssetPoolEntry.objects.create(
        asset_category="fund",
        asset_code="110011",
        asset_name="Example Fund",
        pool_type="watch",
        total_score=55.0,
        regime_score=52.0,
        policy_score=54.0,
        sentiment_score=56.0,
        signal_score=58.0,
        entry_date="2026-04-23",
        risk_level="中风险",
    )

    response = authenticated_client.get("/api/asset-analysis/pool-summary/?asset_type=equity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_type"] == "equity"
    assert payload["summary"]["investable"] == 1
    assert payload["summary"]["watch"] == 0
    assert payload["summary"]["total"] == 1


@pytest.mark.django_db
def test_asset_pool_screen_rejects_unsupported_asset_type(authenticated_client, monkeypatch):
    from apps.asset_analysis.application.interface_services import AssetPoolContextPayload
    from apps.asset_analysis.domain.value_objects import ScoreContext

    monkeypatch.setattr(
        "apps.asset_analysis.interface.pool_views.build_asset_pool_context",
        lambda regime_override=None: AssetPoolContextPayload(
            score_context=ScoreContext(
                current_regime="Recovery",
                policy_level="P1",
                sentiment_index=0.0,
                active_signals=[],
            ),
            current_regime="Recovery",
            policy_level="P1",
            sentiment_index=0.0,
            active_signals=[],
        ),
    )

    response = authenticated_client.post(
        "/api/asset-analysis/screen/bond/",
        {},
        format="json",
    )

    assert response.status_code == 400
    assert "暂不支持 bond 资产类型" in response.json()["error"]
