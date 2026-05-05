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
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
    PriceBarModel,
    ProviderConfigModel,
    PublisherCatalogModel,
    QuoteSnapshotModel,
)


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


@pytest.fixture
def admin_client(api_client, auth_user):
    auth_user.is_staff = True
    auth_user.is_superuser = True
    auth_user.save(update_fields=["is_staff", "is_superuser"])
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_data_center_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/data-center/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["providers"] == "/api/data-center/providers/"
    assert payload["endpoints"]["publishers"] == "/api/data-center/publishers/"
    assert payload["endpoints"]["indicators"] == "/api/data-center/indicators/"
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
def test_data_center_macro_series_reads_from_fact_table(authenticated_client):
    current_period = timezone.localdate().replace(day=1)
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_PMI",
        defaults={
            "name_cn": "制造业PMI",
            "default_period_type": "M",
            "category": "growth",
            "is_active": True,
            "extra": {
                "provenance_class": "official",
                "publisher": "国家统计局/中国物流与采购联合会",
                "publisher_code": "NBS",
                "publisher_codes": ["NBS", "CFLP"],
                "access_channel": "akshare",
            },
        },
    )
    IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code="CN_PMI",
        source_type="",
        original_unit="指数",
        defaults={
            "dimension_key": "index",
            "storage_unit": "指数",
            "display_unit": "指数",
            "multiplier_to_storage": 1.0,
            "is_active": True,
            "priority": 10,
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        value="50.900000",
        unit="指数",
        reporting_period=current_period,
        published_at=current_period + timedelta(days=1),
        source="akshare",
        revision_number=1,
        quality="valid",
        extra={"original_unit": "指数", "period_type": "M"},
    )

    response = authenticated_client.get("/api/data-center/macro/series/?indicator_code=CN_PMI")

    assert response.status_code == 200
    payload = response.json()
    assert payload["indicator_code"] == "CN_PMI"
    assert payload["name_cn"] == "制造业PMI"
    assert payload["total"] == 1
    assert payload["data_source"] == "data_center_fact"
    assert payload["data"][0]["value"] == 50.9
    assert payload["data"][0]["display_value"] == 50.9
    assert payload["data"][0]["display_unit"] == "指数"
    assert payload["data"][0]["original_unit"] == "指数"
    assert payload["data"][0]["quality"] == "valid"
    assert payload["must_not_use_for_decision"] is False
    assert payload["provenance_class"] == "official"
    assert payload["provenance_label"] == "官方数据"
    assert payload["publisher"] == "国家统计局/中国物流与采购联合会"
    assert payload["publisher_code"] == "NBS"
    assert payload["publisher_codes"] == ["NBS", "CFLP"]
    assert payload["access_channel"] == "akshare"
    assert payload["data"][0]["provenance_class"] == "official"
    assert payload["contract"]["provenance_class"] == "official"


@pytest.mark.django_db
def test_data_center_macro_series_marks_derived_series_as_research_only(authenticated_client):
    current_period = timezone.localdate().replace(day=1)
    IndicatorCatalogModel.objects.update_or_create(
        code="CN_SOCIAL_FINANCING_YOY",
        defaults={
            "name_cn": "社融同比",
            "default_period_type": "M",
            "category": "liquidity",
            "is_active": True,
            "extra": {
                "provenance_class": "derived",
                "publisher": "系统派生",
                "publisher_code": "SYSTEM_DERIVED",
                "publisher_codes": ["SYSTEM_DERIVED"],
                "access_channel": "data_center",
                "derivation_method": (
                    "same-month social financing flow year-over-year growth "
                    "with prior_flow_value > 0 guardrail"
                ),
                "upstream_indicator_codes": ["CN_SOCIAL_FINANCING"],
                "decision_grade_enabled": False,
            },
        },
    )
    IndicatorUnitRuleModel.objects.update_or_create(
        indicator_code="CN_SOCIAL_FINANCING_YOY",
        source_type="",
        original_unit="%",
        defaults={
            "dimension_key": "ratio",
            "storage_unit": "%",
            "display_unit": "%",
            "multiplier_to_storage": 1.0,
            "is_active": True,
            "priority": 10,
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_SOCIAL_FINANCING_YOY",
        value="25.000000",
        unit="%",
        reporting_period=current_period,
        published_at=current_period + timedelta(days=1),
        source="data_center",
        revision_number=1,
        quality="valid",
        extra={"original_unit": "%", "period_type": "M"},
    )

    response = authenticated_client.get(
        "/api/data-center/macro/series/?indicator_code=CN_SOCIAL_FINANCING_YOY"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_grade"] == "research_only"
    assert payload["must_not_use_for_decision"] is True
    assert "系统衍生数据" in payload["blocked_reason"]
    assert payload["provenance_class"] == "derived"
    assert payload["provenance_label"] == "系统衍生"
    assert payload["publisher"] == "系统派生"
    assert payload["publisher_code"] == "SYSTEM_DERIVED"
    assert payload["publisher_codes"] == ["SYSTEM_DERIVED"]
    assert payload["access_channel"] == "data_center"
    assert payload["upstream_indicator_codes"] == ["CN_SOCIAL_FINANCING"]
    assert payload["is_derived"] is True
    assert payload["data"][0]["decision_grade"] == "research_only"
    assert payload["data"][0]["is_derived"] is True


@pytest.mark.django_db
def test_legacy_macro_api_routes_are_removed(authenticated_client):
    legacy_path = "/api" + "/macro/"
    response = authenticated_client.get(legacy_path)

    assert response.status_code == 404


@pytest.mark.django_db
def test_publisher_catalog_crud_contract(admin_client):
    create_response = admin_client.post(
        "/api/data-center/publishers/",
        data={
            "code": "TEST_PUBLISHER",
            "canonical_name": "测试发布机构",
            "publisher_class": "other",
            "aliases": ["测试机构别名"],
            "description": "测试用 publisher",
        },
        format="json",
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["code"] == "TEST_PUBLISHER"
    assert "测试机构别名" in payload["aliases"]

    list_response = admin_client.get("/api/data-center/publishers/")
    assert list_response.status_code == 200
    assert any(item["code"] == "TEST_PUBLISHER" for item in list_response.json()["results"])

    patch_response = admin_client.patch(
        "/api/data-center/publishers/TEST_PUBLISHER/",
        data={"description": "已更新测试机构"},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["description"] == "已更新测试机构"

    delete_response = admin_client.delete("/api/data-center/publishers/TEST_PUBLISHER/")
    assert delete_response.status_code == 204
    assert PublisherCatalogModel.objects.filter(code="TEST_PUBLISHER").exists() is False


@pytest.mark.django_db
def test_indicator_catalog_crud_contract(admin_client):
    create_response = admin_client.post(
        "/api/data-center/indicators/",
        data={
            "code": "CN_TEST_LEVEL",
            "name_cn": "测试总量指标",
            "name_en": "Test Level Indicator",
            "description": "用于 CRUD 契约测试",
            "category": "growth",
            "default_period_type": "M",
            "is_active": True,
            "extra": {"publication_lag_days": 7},
        },
        format="json",
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["code"] == "CN_TEST_LEVEL"
    assert payload["extra"]["publication_lag_days"] == 7

    list_response = admin_client.get("/api/data-center/indicators/")
    assert list_response.status_code == 200
    assert any(item["code"] == "CN_TEST_LEVEL" for item in list_response.json()["results"])

    patch_response = admin_client.patch(
        "/api/data-center/indicators/CN_TEST_LEVEL/",
        data={"description": "已更新说明文案"},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["description"] == "已更新说明文案"

    delete_response = admin_client.delete("/api/data-center/indicators/CN_TEST_LEVEL/")
    assert delete_response.status_code == 204
    assert IndicatorCatalogModel.objects.filter(code="CN_TEST_LEVEL").exists() is False


@pytest.mark.django_db
def test_indicator_unit_rule_crud_contract(admin_client):
    IndicatorCatalogModel.objects.create(
        code="CN_TEST_GDP",
        name_cn="测试 GDP",
        default_period_type="Q",
        category="growth",
        is_active=True,
    )

    create_response = admin_client.post(
        "/api/data-center/indicators/CN_TEST_GDP/unit-rules/",
        data={
            "source_type": "akshare",
            "dimension_key": "currency",
            "original_unit": "亿元",
            "storage_unit": "元",
            "display_unit": "亿元",
            "multiplier_to_storage": 100000000.0,
            "is_active": True,
            "priority": 20,
            "description": "GDP 亿元转元",
        },
        format="json",
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    rule_id = payload["id"]
    assert payload["indicator_code"] == "CN_TEST_GDP"
    assert payload["display_unit"] == "亿元"

    list_response = admin_client.get("/api/data-center/indicators/CN_TEST_GDP/unit-rules/")
    assert list_response.status_code == 200
    assert list_response.json()["results"][0]["id"] == rule_id

    patch_response = admin_client.patch(
        f"/api/data-center/indicators/CN_TEST_GDP/unit-rules/{rule_id}/",
        data={"description": "GDP 默认展示单位规则"},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["description"] == "GDP 默认展示单位规则"

    delete_response = admin_client.delete(
        f"/api/data-center/indicators/CN_TEST_GDP/unit-rules/{rule_id}/"
    )
    assert delete_response.status_code == 204
    assert IndicatorUnitRuleModel.objects.filter(id=rule_id).exists() is False


@pytest.mark.django_db
def test_indicator_unit_rule_rejects_unknown_indicator(admin_client):
    response = admin_client.post(
        "/api/data-center/indicators/CN_UNKNOWN/unit-rules/",
        data={
            "source_type": "",
            "dimension_key": "index",
            "original_unit": "指数",
            "storage_unit": "指数",
            "display_unit": "指数",
            "multiplier_to_storage": 1.0,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "Unknown indicator code" in response.json()["detail"]


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
