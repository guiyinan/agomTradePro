from unittest.mock import patch

import pytest


@pytest.mark.django_db
def test_factor_catalog_get_endpoints_are_pure_reads(authenticated_client):
    from datetime import date
    from decimal import Decimal

    from apps.factor.infrastructure.models import (
        FactorDefinitionModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
    )

    FactorDefinitionModel._default_manager.create(
        code="factor_read_contract",
        name="Factor read contract",
        category="value",
        description="Pure read evidence",
        data_source="test",
        data_field="value",
        direction="positive",
        is_active=True,
    )
    config = FactorPortfolioConfigModel._default_manager.create(
        name="Factor read config",
        description="Pure read evidence",
        factor_weights={"factor_read_contract": 1.0},
        universe="all_a",
        top_n=20,
        is_active=True,
    )
    FactorPortfolioHoldingModel._default_manager.create(
        config=config,
        trade_date=date(2026, 7, 13),
        stock_code="000001.SZ",
        stock_name="平安银行",
        weight=Decimal("0.0500"),
        factor_score=Decimal("88.5000"),
        rank=1,
        sector="银行",
        factor_scores={"quality": 88.5},
    )
    tracked_models = (
        FactorDefinitionModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }

    definitions_response = authenticated_client.get("/api/factor/all-factors/")
    configs_response = authenticated_client.get("/api/factor/all-configs/")
    portfolio_response = authenticated_client.get(
        "/api/factor/portfolio/",
        {"config_name": config.name},
    )

    assert definitions_response.status_code == 200
    assert configs_response.status_code == 200
    assert portfolio_response.status_code == 200
    assert any(item["code"] == "factor_read_contract" for item in definitions_response.json())
    assert any(item["name"] == "Factor read config" for item in configs_response.json())
    assert portfolio_response.json()["config_name"] == config.name
    assert portfolio_response.json()["holdings"][0]["stock_code"] == "000001.SZ"
    after_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }
    assert after_counts == before_counts


@pytest.mark.django_db
def test_factor_top_stocks_is_pure_compute_without_price_cache_writes(
    authenticated_client,
    monkeypatch,
):
    from datetime import date

    from apps.equity.infrastructure.models import StockInfoModel
    from apps.factor.infrastructure.models import (
        FactorDefinitionModel,
        FactorExposureModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
    )
    from apps.rotation.infrastructure.adapters.price_adapter import PriceDataCache

    FactorDefinitionModel._default_manager.create(
        code="momentum_1m",
        name="One-month momentum",
        category="momentum",
        description="Pure compute contract",
        data_source="data_center",
        data_field="close",
        direction="positive",
        is_active=True,
    )
    for stock_code, name in (
        ("600000.SH", "浦发银行"),
        ("000001.SZ", "平安银行"),
    ):
        StockInfoModel._default_manager.create(
            stock_code=stock_code,
            name=name,
            sector="银行",
            market="SH" if stock_code.endswith(".SH") else "SZ",
            list_date=date(2000, 1, 1),
            is_active=True,
        )

    def fake_prices(*, asset_code, end_date, days_back):
        del end_date, days_back
        if asset_code == "600000.SH":
            return [float(value) for value in range(1, 32)]
        return [10.0 + (value * 0.01) for value in range(31)]

    def reject_cache_write(self, asset_code, end_date, prices):
        del self, asset_code, end_date, prices
        raise AssertionError("factor top-stocks must not write the price cache")

    monkeypatch.setattr(
        "apps.rotation.infrastructure.adapters.price_adapter."
        "fetch_close_prices_from_data_center",
        fake_prices,
    )
    monkeypatch.setattr(PriceDataCache, "set", reject_cache_write)

    tracked_models = (
        FactorDefinitionModel,
        FactorExposureModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
        StockInfoModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }

    response = authenticated_client.post(
        "/api/factor/top-stocks/",
        {
            "factor_preferences": {},
            "top_n": 2,
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_stocks"] == 2
    assert len(payload["stocks"]) == 2
    assert payload["stocks"][0]["stock_code"] == "600000.SH"
    after_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }
    assert after_counts == before_counts


@pytest.mark.django_db
def test_factor_top_stocks_rejects_invalid_compute_contract(authenticated_client):
    response = authenticated_client.post(
        "/api/factor/top-stocks/",
        {
            "factor_preferences": {"momentum": "maximum"},
            "top_n": 0,
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "top_n must be an integer between 1 and 100"


@pytest.mark.django_db
def test_factor_portfolio_contract_rejects_missing_or_unknown_inputs(
    authenticated_client,
):
    create_response = authenticated_client.post(
        "/api/factor/create-portfolio/",
        {},
        format="json",
    )
    read_response = authenticated_client.get("/api/factor/portfolio/")
    unknown_response = authenticated_client.get(
        "/api/factor/portfolio/",
        {"config_name": "balanced", "unknown": True},
    )

    assert create_response.status_code == 400
    assert create_response.json()["error"] == "config_name is required"
    assert read_response.status_code == 400
    assert "config_name" in str(read_response.json())
    assert unknown_response.status_code == 400
    assert "Unknown query parameters: unknown" in str(unknown_response.json())


@pytest.mark.django_db
def test_factor_create_portfolio_maps_value_error_to_400(authenticated_client):
    with patch(
        "apps.factor.interface.views.factor_interface_services.create_factor_portfolio",
        side_effect=ValueError("invalid trade date"),
    ):
        response = authenticated_client.post(
            "/api/factor/create-portfolio/",
            {"config_name": "balanced-factor", "trade_date": "bad-date"},
            format="json",
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid trade date"


@pytest.mark.django_db
def test_factor_explain_stock_is_pure_compute_without_price_cache_writes(
    authenticated_client,
    monkeypatch,
):
    from datetime import date

    from apps.equity.infrastructure.models import StockInfoModel
    from apps.factor.infrastructure.models import (
        FactorDefinitionModel,
        FactorExposureModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
    )
    from apps.rotation.infrastructure.adapters.price_adapter import PriceDataCache

    FactorDefinitionModel._default_manager.create(
        code="momentum_1m",
        name="One-month momentum",
        category="momentum",
        description="Pure explanation contract",
        data_source="data_center",
        data_field="close",
        direction="positive",
        is_active=True,
    )
    StockInfoModel._default_manager.create(
        stock_code="600000.SH",
        name="浦发银行",
        sector="银行",
        market="SH",
        list_date=date(2000, 1, 1),
        is_active=True,
    )

    def fake_prices(*, asset_code, end_date, days_back):
        del asset_code, end_date, days_back
        return [float(value) for value in range(1, 32)]

    def reject_cache_write(self, asset_code, end_date, prices):
        del self, asset_code, end_date, prices
        raise AssertionError("factor stock explanation must not write the price cache")

    monkeypatch.setattr(
        "apps.rotation.infrastructure.adapters.price_adapter."
        "fetch_close_prices_from_data_center",
        fake_prices,
    )
    monkeypatch.setattr(PriceDataCache, "set", reject_cache_write)

    tracked_models = (
        FactorDefinitionModel,
        FactorExposureModel,
        FactorPortfolioConfigModel,
        FactorPortfolioHoldingModel,
        StockInfoModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }

    response = authenticated_client.post(
        "/api/factor/explain-stock/",
        {
            "stock_code": "600000.SH",
            "factor_weights": {"momentum_1m": 1.0},
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stock_code"] == "600000.SH"
    assert payload["stock_name"] == "浦发银行"
    assert "momentum_1m" in payload["factor_breakdown"]
    after_counts = {
        model._meta.label_lower: model._default_manager.count() for model in tracked_models
    }
    assert after_counts == before_counts


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        {"stock_code": "", "factor_weights": {"roe": 1.0}},
        {"stock_code": "600000.SH", "factor_weights": []},
        {"stock_code": "600000.SH", "factor_weights": {"roe": True}},
        {"stock_code": "600000.SH", "factor_weights": {"roe": 2.0}},
        {"stock_code": "600000.SH", "factor_weights": {"roe": 0.0}},
    ],
)
def test_factor_explain_stock_rejects_invalid_compute_contract(
    authenticated_client,
    payload,
):
    response = authenticated_client.post(
        "/api/factor/explain-stock/",
        payload,
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_factor_explain_stock_returns_500_when_service_returns_none(authenticated_client):
    with patch(
        "apps.factor.interface.views.factor_interface_services.explain_stock_score",
        return_value=None,
    ):
        response = authenticated_client.post(
            "/api/factor/explain-stock/",
            {"stock_code": "600519.SH", "factor_weights": {"roe": 0.6, "pe_ttm": -0.4}},
            format="json",
        )

    assert response.status_code == 500
    assert response.json()["error"] == "Failed to explain stock score"
