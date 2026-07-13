from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.rotation.infrastructure.models import (
    AssetClassModel,
    MomentumScoreModel,
    PortfolioRotationConfigModel,
    RotationConfigModel,
    RotationPortfolioModel,
    RotationSignalModel,
    RotationTemplateModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="rotation_user",
        password="testpass123",
        email="rotation@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def staff_client(api_client, db):
    staff_user = get_user_model().objects.create_user(
        username="rotation_staff",
        password="testpass123",
        is_staff=True,
    )
    api_client.force_authenticate(user=staff_user)
    return api_client


def _list_payload(response) -> list[dict]:
    payload = response.json()
    if isinstance(payload, dict):
        return payload.get("results", payload.get("data", []))
    return payload


def _create_account(user, name: str) -> SimulatedAccountModel:
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name=name,
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )


@pytest.mark.django_db
def test_rotation_api_root_contract(api_client):
    response = api_client.get("/api/rotation/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["assets"] == "/api/rotation/assets/"
    assert payload["endpoints"]["actions"] == "/api/rotation/"


@pytest.mark.django_db
def test_rotation_config_catalog_requires_authentication(api_client):
    response = api_client.get("/api/rotation/configs/")

    assert response.status_code in {401, 403}
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_rotation_config_catalog_is_a_pure_persisted_read(authenticated_client):
    config = RotationConfigModel.objects.create(
        name="动量轮动策略",
        description="持久化轮动配置",
        strategy_type="momentum",
        asset_universe=["510300", "510500"],
        params={"score_method": "weighted"},
        rebalance_frequency="monthly",
        min_weight=0.1,
        max_weight=0.7,
        max_turnover=0.4,
        lookback_period=120,
        momentum_periods=[20, 60],
        top_n=1,
        is_active=True,
    )
    count_before = RotationConfigModel._default_manager.count()

    response = authenticated_client.get("/api/rotation/configs/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    rows = _list_payload(response)
    row = next(item for item in rows if item["id"] == config.id)
    assert row["name"] == "动量轮动策略"
    assert row["strategy_type"] == "momentum"
    assert row["asset_universe"] == ["510300", "510500"]
    assert row["params"] == {"score_method": "weighted"}
    assert row["rebalance_frequency"] == "monthly"
    assert row["top_n"] == 1
    assert RotationConfigModel._default_manager.count() == count_before


@pytest.mark.django_db
def test_rotation_regime_and_template_catalogs_return_canonical_rows(authenticated_client):
    RotationTemplateModel.objects.create(
        key="moderate",
        name="稳健型",
        description="稳健配置",
        regime_allocations={"Recovery": {"510300": 1.0}},
        display_order=1,
        is_active=True,
    )

    regime_response = authenticated_client.get("/api/rotation/regimes/")
    template_response = authenticated_client.get("/api/rotation/templates/")

    assert regime_response.status_code == 200
    regimes = regime_response.json()
    assert regimes
    assert {"key", "label"} <= set(regimes[0])

    assert template_response.status_code == 200
    templates = _list_payload(template_response)
    assert templates[0]["key"] == "moderate"
    assert templates[0]["allocations"] == {"Recovery": {"510300": 1.0}}


@pytest.mark.django_db
def test_rotation_asset_catalog_and_detail_return_persisted_master_data(
    authenticated_client,
):
    AssetClassModel.objects.create(
        code="510300",
        name="沪深300ETF",
        category="equity",
        currency="CNY",
        is_active=True,
    )

    list_response = authenticated_client.get("/api/rotation/assets/")
    detail_response = authenticated_client.get("/api/rotation/assets/510300/")

    assert list_response.status_code == 200
    assets = _list_payload(list_response)
    assert assets[0]["code"] == "510300"
    assert assets[0]["name"] == "沪深300ETF"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["code"] == "510300"
    assert detail["category"] == "equity"
    assert detail["currency"] == "CNY"


@pytest.mark.django_db
def test_rotation_asset_catalog_mutations_require_staff(authenticated_client):
    asset = AssetClassModel.objects.create(
        code="510300",
        name="沪深300ETF",
        category="equity",
        currency="CNY",
        is_active=True,
    )

    create_response = authenticated_client.post(
        "/api/rotation/assets/",
        {
            "code": "510500",
            "name": "中证500ETF",
            "category": "equity",
        },
        format="json",
    )
    update_response = authenticated_client.patch(
        f"/api/rotation/assets/{asset.code}/",
        {"name": "未授权修改"},
        format="json",
    )
    delete_response = authenticated_client.delete(
        f"/api/rotation/assets/{asset.code}/"
    )
    import_response = authenticated_client.post(
        "/api/rotation/assets/import-defaults/",
        {},
        format="json",
    )
    preview_import_response = authenticated_client.get(
        "/api/rotation/assets/import-defaults-preview/"
    )

    assert create_response.status_code == 403
    assert update_response.status_code == 403
    assert delete_response.status_code == 403
    assert import_response.status_code == 403
    assert preview_import_response.status_code == 403
    asset.refresh_from_db()
    assert asset.name == "沪深300ETF"
    assert asset.is_active is True
    assert not AssetClassModel.objects.filter(code="510500").exists()


@pytest.mark.django_db
def test_rotation_staff_can_create_asset_master_data(staff_client):
    response = staff_client.post(
        "/api/rotation/assets/",
        {
            "code": "510300",
            "name": "沪深300ETF",
            "category": "equity",
            "description": "宽基指数资产",
            "underlying_index": "000300.SH",
            "currency": "CNY",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["code"] == "510300"
    assert payload["category"] == "equity"
    asset = AssetClassModel.objects.get(code="510300")
    assert asset.name == "沪深300ETF"
    assert asset.underlying_index == "000300.SH"


@pytest.mark.django_db
def test_rotation_staff_can_partially_update_and_reactivate_asset(staff_client):
    AssetClassModel.objects.create(
        code="510300",
        name="旧名称",
        category="equity",
        currency="CNY",
        is_active=False,
    )

    response = staff_client.patch(
        "/api/rotation/assets/510300/",
        {
            "name": "沪深300ETF",
            "underlying_index": "000300.SH",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == "510300"
    assert payload["name"] == "沪深300ETF"
    assert payload["is_active"] is True
    asset = AssetClassModel.objects.get(code="510300")
    assert asset.underlying_index == "000300.SH"
    assert asset.is_active is True


@pytest.mark.django_db
def test_rotation_staff_delete_soft_deactivates_asset(staff_client):
    asset = AssetClassModel.objects.create(
        code="510300",
        name="沪深300ETF",
        category="equity",
        currency="CNY",
        is_active=True,
    )

    response = staff_client.delete("/api/rotation/assets/510300/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "soft_deleted",
        "code": "510300",
        "is_active": False,
    }
    asset.refresh_from_db()
    assert asset.is_active is False


@pytest.mark.django_db
def test_rotation_staff_previews_and_imports_default_assets(staff_client):
    inactive = AssetClassModel.objects.create(
        code="510300",
        name="旧沪深300名称",
        category="equity",
        currency="CNY",
        is_active=False,
    )
    stale = AssetClassModel.objects.create(
        code="510500",
        name="旧中证500名称",
        category="equity",
        currency="CNY",
        is_active=True,
    )
    AssetClassModel.objects.create(
        code="159915",
        name="创业板ETF",
        category="equity",
        description="跟踪创业板指数，代表新兴成长股",
        underlying_index="399006.SZ",
        currency="CNY",
        is_active=True,
    )
    count_before = AssetClassModel.objects.count()

    preview_response = staff_client.get(
        "/api/rotation/assets/import-defaults-preview/"
    )

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["created"] == 15
    assert preview["reactivated"] == 1
    assert preview["updated"] == 1
    assert preview["unchanged"] == 1
    assert preview["existing"] == 2
    assert preview["total_defaults"] == 18
    actions = {item["code"]: item["action"] for item in preview["items"]}
    assert actions["510300"] == "reactivate"
    assert actions["510500"] == "update"
    assert actions["159915"] == "unchanged"
    assert AssetClassModel.objects.count() == count_before
    inactive.refresh_from_db()
    stale.refresh_from_db()
    assert inactive.name == "旧沪深300名称"
    assert inactive.is_active is False
    assert stale.name == "旧中证500名称"

    import_response = staff_client.post(
        "/api/rotation/assets/import-defaults/",
        {},
        format="json",
    )

    assert import_response.status_code == 200
    assert import_response.json() == {
        "created": 15,
        "reactivated": 1,
        "updated": 1,
        "unchanged": 1,
        "existing": 2,
        "total_defaults": 18,
    }
    assert AssetClassModel.objects.count() == 18
    inactive.refresh_from_db()
    stale.refresh_from_db()
    assert inactive.name == "沪深300ETF"
    assert inactive.is_active is True
    assert stale.name == "中证500ETF"


@pytest.mark.django_db
def test_rotation_account_config_reads_are_user_scoped(
    authenticated_client,
    auth_user,
):
    own_account = _create_account(auth_user, "我的组合")
    own_config = PortfolioRotationConfigModel.objects.create(
        account=own_account,
        risk_tolerance="moderate",
        regime_allocations={"Recovery": {"510300": 1.0}},
        is_enabled=True,
    )
    foreign_user = get_user_model().objects.create_user(
        username="rotation_foreign",
        password="testpass123",
    )
    foreign_account = _create_account(foreign_user, "他人组合")
    PortfolioRotationConfigModel.objects.create(
        account=foreign_account,
        risk_tolerance="aggressive",
        regime_allocations={"Recovery": {"510500": 1.0}},
        is_enabled=True,
    )

    list_response = authenticated_client.get("/api/rotation/account-configs/")
    detail_response = authenticated_client.get(
        f"/api/rotation/account-configs/{own_config.id}/"
    )
    by_account_response = authenticated_client.get(
        f"/api/rotation/account-configs/by-account/{own_account.id}/"
    )

    assert list_response.status_code == 200
    configs = _list_payload(list_response)
    assert [item["id"] for item in configs] == [own_config.id]

    assert detail_response.status_code == 200
    assert detail_response.json()["account"] == own_account.id

    assert by_account_response.status_code == 200
    assert by_account_response.json()["id"] == own_config.id


@pytest.mark.django_db
def test_rotation_compare_requires_asset_codes(authenticated_client):
    response = authenticated_client.post("/api/rotation/compare/", {}, format="json")

    assert response.status_code == 400
    assert response.json()["error"].startswith("asset_codes must be")


@pytest.mark.django_db
def test_rotation_compare_is_pure_compute_without_price_cache_writes(
    authenticated_client,
    monkeypatch,
):
    from apps.rotation.infrastructure.adapters.price_adapter import PriceDataCache

    def fake_prices(*, asset_code, end_date, days_back):
        del end_date, days_back
        offset = 1.0 if asset_code == "510300" else 10.0
        return [offset + float(value) for value in range(181)]

    def reject_cache_write(self, asset_code, end_date, prices):
        del self, asset_code, end_date, prices
        raise AssertionError("rotation asset comparison must not write the price cache")

    monkeypatch.setattr(
        "apps.rotation.infrastructure.adapters.price_adapter."
        "fetch_close_prices_from_data_center",
        fake_prices,
    )
    monkeypatch.setattr(PriceDataCache, "set", reject_cache_write)

    tracked_models = (
        AssetClassModel,
        MomentumScoreModel,
        PortfolioRotationConfigModel,
        RotationConfigModel,
        RotationPortfolioModel,
        RotationSignalModel,
        RotationTemplateModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }

    response = authenticated_client.post(
        "/api/rotation/compare/",
        {
            "asset_codes": ["510300", "511260"],
            "lookback_days": 60,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lookback_days"] == 60
    assert set(payload["assets"]) == {"510300", "511260"}
    assert payload["assets"]["510300"]["ma_signal"] == "bullish"
    after_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }
    assert after_counts == before_counts


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"asset_codes": "510300"},
        {"asset_codes": [""]},
        {"asset_codes": ["510300"], "lookback_days": 0},
        {"asset_codes": ["510300"], "lookback_days": True},
    ],
)
def test_rotation_compare_rejects_invalid_compute_contract(
    authenticated_client,
    payload,
):
    response = authenticated_client.post(
        "/api/rotation/compare/",
        payload,
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_rotation_correlation_is_pure_compute_without_price_cache_writes(
    authenticated_client,
    monkeypatch,
):
    from apps.rotation.infrastructure.adapters.price_adapter import PriceDataCache

    def fake_prices(*, asset_code, end_date, days_back):
        del end_date, days_back
        if asset_code == "510300":
            return [float(value) for value in range(1, 50)]
        return [float(value) for value in range(50, 1, -1)]

    def reject_cache_write(self, asset_code, end_date, prices):
        del self, asset_code, end_date, prices
        raise AssertionError("rotation correlation must not write the price cache")

    monkeypatch.setattr(
        "apps.rotation.infrastructure.adapters.price_adapter."
        "fetch_close_prices_from_data_center",
        fake_prices,
    )
    monkeypatch.setattr(PriceDataCache, "set", reject_cache_write)

    tracked_models = (
        AssetClassModel,
        PortfolioRotationConfigModel,
        RotationConfigModel,
        RotationSignalModel,
        RotationTemplateModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }

    response = authenticated_client.post(
        "/api/rotation/correlation/",
        {
            "asset_codes": ["510300", "511260"],
            "window_days": 20,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assets"] == ["510300", "511260"]
    assert payload["window_days"] == 20
    cross_correlation = payload["correlation_matrix"]["510300"]["511260"]
    assert -1.0 <= cross_correlation <= 1.0
    assert payload["correlation_matrix"]["511260"]["510300"] == pytest.approx(
        cross_correlation
    )
    after_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }
    assert after_counts == before_counts


@pytest.mark.django_db
def test_rotation_generate_signal_returns_404_when_service_returns_none(authenticated_client):
    with patch(
        "apps.rotation.application.interface_services.RotationIntegrationService.generate_rotation_signal",
        return_value=None,
    ):
        response = authenticated_client.post(
            "/api/rotation/generate-signal/",
            {"config_name": "missing-config"},
            format="json",
        )

    assert response.status_code == 404
    assert "missing-config" in response.json()["error"]


@pytest.mark.django_db
def test_rotation_clear_cache_calls_service(authenticated_client):
    with patch(
        "apps.rotation.application.interface_services.RotationIntegrationService.clear_price_cache"
    ) as mock_clear:
        response = authenticated_client.post("/api/rotation/clear-cache/", {}, format="json")

    assert response.status_code == 200
    assert response.json() == {"status": "cache cleared"}
    mock_clear.assert_called_once_with()


@pytest.mark.django_db
def test_rotation_latest_signal_exposes_quality_metadata(authenticated_client):
    config = RotationConfigModel.objects.create(
        name="质量测试轮动",
        strategy_type="momentum",
        asset_universe=["510300", "510500", "159915"],
        top_n=2,
        is_active=True,
    )
    RotationSignalModel.objects.create(
        config=config,
        signal_date="2026-07-04",
        target_allocation={"510300": 1.0},
        momentum_ranking=[["510300", 0.12]],
        expected_return=0.0,
        expected_volatility=0.0,
        action_required="rebalance",
        reason="partial coverage",
    )

    response = authenticated_client.get("/api/rotation/signals/latest/")

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload if item["config_name"] == "质量测试轮动")
    assert row["data_quality"]["status"] == "degraded"
    assert row["data_quality"]["coverage_ratio"] == pytest.approx(1 / 3, abs=0.0001)
    assert row["data_quality"]["metrics_available"] is False
    assert "partial_price_coverage" in row["data_quality"]["warnings"]
    assert "risk_return_metrics_unavailable" in row["data_quality"]["warnings"]
    assert "is_stale" in row
    assert "staleness_days" in row
    assert row["action_required"] == "rebalance"
    assert row["actionable"] is False
    assert row["execution_block_reason"] in {
        "stale_rotation_signal",
        "rotation_data_quality_degraded",
    }


@pytest.mark.django_db
def test_rotation_latest_signal_treats_risk_parity_allocation_as_quality_coverage(
    authenticated_client,
):
    config = RotationConfigModel.objects.create(
        name="风险平价质量测试",
        strategy_type="risk_parity",
        asset_universe=["510300", "510500"],
        top_n=2,
        is_active=True,
    )
    RotationSignalModel.objects.create(
        config=config,
        signal_date=timezone.localdate(),
        target_allocation={"510300": 0.6, "510500": 0.4},
        momentum_ranking=[],
        expected_return=0.08,
        expected_volatility=0.12,
        action_required="rebalance",
        reason="risk parity allocation",
    )

    response = authenticated_client.get("/api/rotation/signals/latest/")

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload if item["config_name"] == "风险平价质量测试")
    assert row["data_quality"]["status"] == "ok"
    assert row["data_quality"]["coverage_ratio"] == 1.0
    assert row["data_quality"]["warnings"] == []
    assert row["actionable"] is True
    assert row["execution_block_reason"] is None
