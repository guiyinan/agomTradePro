from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    CapitalFlowFactModel,
    PriceBarModel,
    ProviderConfigModel,
    QuoteSnapshotModel,
)
from apps.macro.infrastructure.models import MacroIndicator as LegacyMacroIndicatorModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="market_data_api_user",
        password="testpass123",
        email="market-data@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_data_center_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/data-center/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/data-center/providers/"
    assert payload["endpoints"]["price_quotes"] == "/api/data-center/prices/quotes/"


@pytest.mark.django_db
def test_data_center_quotes_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/prices/quotes/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_data_center_capital_flows_require_asset_code(authenticated_client):
    response = authenticated_client.get("/api/data-center/capital-flows/")

    assert response.status_code == 400
    assert "asset_code" in response.json()["detail"]


@pytest.mark.django_db
def test_legacy_market_data_api_routes_are_removed(authenticated_client):
    response = authenticated_client.get("/api/market-data/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_data_center_macro_series_blocks_legacy_fallback_by_default(authenticated_client):
    LegacyMacroIndicatorModel.objects.create(
        code="CN_PMI",
        value=50.9,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2025, 3, 1),
        period_type="M",
        published_at=date(2025, 3, 2),
        source="akshare",
    )

    response = authenticated_client.get("/api/data-center/macro/series/?indicator_code=CN_PMI")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["legacy_fallback_available"] is True
    assert payload["legacy_fallback_used"] is False
    assert payload["must_not_use_for_decision"] is True
    assert payload["freshness_status"] == "legacy_blocked"


@pytest.mark.django_db
def test_data_center_macro_series_can_explicitly_enable_legacy_fallback(authenticated_client):
    LegacyMacroIndicatorModel.objects.create(
        code="CN_PMI",
        value=50.9,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2025, 3, 1),
        period_type="M",
        published_at=date(2025, 3, 2),
        source="akshare",
    )

    response = authenticated_client.get(
        "/api/data-center/macro/series/?indicator_code=CN_PMI&allow_legacy_fallback=true"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["data"][0]["value"] == 50.9
    assert payload["data"][0]["quality"] == "legacy"
    assert payload["legacy_fallback_used"] is True
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
def test_data_center_quotes_fall_back_to_realtime_use_case(authenticated_client, mocker):
    fresh_timestamp = (timezone.now() - timedelta(minutes=5)).isoformat()
    mocker.patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase.get_latest_prices",
        return_value=[
            {
                "asset_code": "510300.SH",
                "asset_type": "etf",
                "price": 3.91,
                "change": 0.02,
                "change_pct": 0.51,
                "volume": 123456,
                "timestamp": fresh_timestamp,
                "source": "akshare",
            }
        ],
    )

    response = authenticated_client.get("/api/data-center/prices/quotes/?asset_code=510300.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_code"] == "510300.SH"
    assert payload["current_price"] == 3.91
    assert payload["source"] == "akshare"
    assert payload["freshness_status"] == "fresh"
    assert payload["must_not_use_for_decision"] is False
    assert payload["contract"]["is_stale"] is False


@pytest.mark.django_db
def test_data_center_quotes_resolve_alias_to_canonical_asset(authenticated_client):
    asset = AssetMasterModel.objects.create(
        code="300502.SZ",
        name="新易盛",
        short_name="新易盛",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300502",
    )
    QuoteSnapshotModel.objects.create(
        asset_code="300502.SZ",
        snapshot_at=datetime(2026, 4, 12, 9, 35, tzinfo=dt_timezone.utc),
        current_price="92.35",
        prev_close="91.10",
        volume="12345.00",
        amount="1139815.75",
        source="test",
    )

    response = authenticated_client.get("/api/data-center/prices/quotes/?asset_code=300502")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_code"] == "300502.SZ"
    assert payload["current_price"] == 92.35


@pytest.mark.django_db
def test_data_center_quotes_expose_freshness_metadata(authenticated_client):
    snapshot_at = timezone.now() - timedelta(minutes=15)
    QuoteSnapshotModel.objects.create(
        asset_code="510300.SH",
        snapshot_at=snapshot_at,
        current_price="3.95",
        prev_close="3.90",
        volume="12345.00",
        amount="48777.75",
        source="test",
    )

    response = authenticated_client.get("/api/data-center/prices/quotes/?asset_code=510300.SH")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_code"] == "510300.SH"
    assert payload["freshness_status"] == "fresh"
    assert payload["must_not_use_for_decision"] is False
    assert payload["contract"]["max_age_hours"] == 4.0


@pytest.mark.django_db
def test_data_center_quotes_strict_freshness_blocks_stale_snapshot(
    authenticated_client,
    mocker,
):
    snapshot_at = timezone.now() - timedelta(hours=6)
    QuoteSnapshotModel.objects.create(
        asset_code="510300.SH",
        snapshot_at=snapshot_at,
        current_price="3.95",
        prev_close="3.90",
        volume="12345.00",
        amount="48777.75",
        source="test",
    )
    mocker.patch(
        "apps.realtime.application.price_polling_service.PricePollingUseCase.get_latest_prices",
        return_value=[],
    )

    response = authenticated_client.get(
        "/api/data-center/prices/quotes/?asset_code=510300.SH&strict_freshness=true&max_age_hours=1"
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["must_not_use_for_decision"] is True
    assert payload["freshness_status"] == "stale"
    assert payload["contract"]["is_stale"] is True
    assert "strict_freshness" in payload["detail"]


@pytest.mark.django_db
def test_provider_status_enriches_last_success_from_persisted_telemetry(
    authenticated_client,
    monkeypatch,
    auth_user,
):
    auth_user.is_staff = True
    auth_user.is_superuser = True
    auth_user.save(update_fields=["is_staff", "is_superuser"])

    ProviderConfigModel.objects.create(
        name="tushare-main",
        source_type="tushare",
        is_active=True,
        priority=1,
        extra_config={
            "provider_last_success_at": "2026-04-21T09:00:00+00:00",
            "provider_avg_latency_ms": 88.8,
            "health_metrics": {
                "macro": {
                    "last_success_at": "2026-04-21T09:00:00+00:00",
                    "avg_latency_ms": 88.8,
                    "consecutive_failures": 0,
                }
            },
        },
    )

    class _Snapshot:
        provider_name = "tushare-main"

        def to_dict(self):
            return {
                "provider_name": "tushare-main",
                "capability": "macro",
                "status": "healthy",
                "consecutive_failures": 0,
                "last_success_at": None,
                "avg_latency_ms": None,
            }

    class _Registry:
        def get_all_statuses(self):
            return [_Snapshot()]

    monkeypatch.setattr("apps.data_center.interface.api_views.get_registry", lambda: _Registry())

    response = authenticated_client.get("/api/data-center/providers/status/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["last_success_at"] == "2026-04-21T09:00:00+00:00"
    assert payload["results"][0]["avg_latency_ms"] == 88.8


@pytest.mark.django_db
def test_data_center_capital_flows_resolve_alias_to_canonical_asset(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300502.SZ",
        name="新易盛",
        short_name="新易盛",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300502",
    )
    CapitalFlowFactModel.objects.create(
        asset_code="300502.SZ",
        flow_date=today,
        main_net="5600000.00",
        retail_net="-5600000.00",
        super_large_net="2200000.00",
        large_net="1800000.00",
        medium_net="900000.00",
        small_net="-4900000.00",
        source="test",
    )

    response = authenticated_client.get(
        f"/api/data-center/capital-flows/?asset_code=300502&start={today.isoformat()}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1


@pytest.mark.django_db
def test_data_center_price_history_prefers_exact_code_over_alias_candidate(
    authenticated_client,
):
    asset = AssetMasterModel.objects.create(
        code="000300.SZ",
        name="沪深300旧映射",
        short_name="沪深300旧映射",
        asset_type="index",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="000300.SH",
    )
    PriceBarModel.objects.create(
        asset_code="000300.SZ",
        bar_date=date(2026, 4, 3),
        open="4500.0",
        high="4520.0",
        low="4480.0",
        close="4510.0",
        source="legacy",
    )
    PriceBarModel.objects.create(
        asset_code="000300.SH",
        bar_date=date(2026, 4, 21),
        open="4750.0",
        high="4770.0",
        low="4730.0",
        close="4768.0",
        source="AKShare Public",
    )

    response = authenticated_client.get(
        "/api/data-center/prices/history/"
        "?asset_code=000300.SH&start=2026-04-01&end=2026-04-21&limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["data"][0]["asset_code"] == "000300.SH"
    assert payload["data"][0]["bar_date"] == "2026-04-21"


@pytest.mark.django_db
def test_decision_reliability_repair_api_returns_report(
    authenticated_client,
    auth_user,
    monkeypatch,
):
    auth_user.is_staff = True
    auth_user.is_superuser = True
    auth_user.save(update_fields=["is_staff", "is_superuser"])

    class _Report:
        def to_dict(self):
            return {
                "target_date": "2026-04-21",
                "portfolio_id": 366,
                "macro_status": {"status": "ready", "must_not_use_for_decision": False},
                "quote_status": {"status": "ready", "must_not_use_for_decision": False},
                "pulse_status": {"status": "ready", "must_not_use_for_decision": False},
                "alpha_status": {"status": "ready", "must_not_use_for_decision": False},
                "must_not_use_for_decision": False,
                "blocked_reasons": [],
            }

    class _UseCase:
        def execute(self, request):
            assert request.target_date.isoformat() == "2026-04-21"
            assert request.portfolio_id == 366
            assert request.asset_codes == ["510300.SH"]
            return _Report()

    monkeypatch.setattr(
        "apps.data_center.interface.api_views._make_decision_repair_use_case",
        lambda user: _UseCase(),
    )

    response = authenticated_client.post(
        "/api/data-center/decision-reliability/repair/",
        {
            "target_date": "2026-04-21",
            "portfolio_id": 366,
            "asset_codes": ["510300.SH"],
            "strict": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["must_not_use_for_decision"] is False
