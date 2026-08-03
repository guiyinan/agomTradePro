from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    FinancialFactModel,
    PriceBarModel,
    ValuationFactModel,
)
from apps.equity.domain.entities import TechnicalBar
from apps.equity.infrastructure.models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    StockPoolSnapshot,
    ValuationModel,
)
from apps.equity.interface.serializers import ScreenStocksRequestSerializer
from apps.regime.infrastructure.models import RegimeLog
from core.exceptions import DataFetchError


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/equity/screen/", {"unexpected": True}),
        ("post", "/api/equity/dcf/", {"stock_code": "000001.SZ", "unexpected": True}),
        (
            "post",
            "/api/equity/comprehensive-valuation/",
            {"stock_code": "000001.SZ", "unexpected": True},
        ),
        ("get", "/api/equity/technical/000001.SZ/?unexpected=true", None),
        ("get", "/api/equity/intraday/000001.SZ/?unexpected=true", None),
        (
            "get",
            "/api/equity/regime-correlation/000001.SZ/?unexpected=true",
            None,
        ),
    ],
)
def test_equity_analysis_actions_reject_unknown_inputs(
    authenticated_client,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    """Analysis endpoints must not silently discard undeclared input."""

    if method == "post":
        response = authenticated_client.post(path, payload, format="json")
    else:
        response = authenticated_client.get(path)

    assert response.status_code == 400


@pytest.mark.django_db
def test_equity_pool_returns_empty_payload_when_no_pool(authenticated_client):
    regime = SimpleNamespace(dominant_regime="Recovery")

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=[],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value=None,
        ),
        patch(
            "apps.regime.application.current_regime.resolve_current_regime",
            return_value=regime,
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["regime"] == "Recovery"
    assert payload["count"] == 0
    assert payload["stocks"] == []
    assert payload["sector_distribution"] == []


@pytest.mark.django_db
def test_equity_pool_default_read_chain_does_not_persist_business_state(
    authenticated_client,
):
    from django.core.cache import cache

    today = timezone.localdate()
    cache.delete("equity:stock_pool:current")
    cache.delete("equity:stock_pool:meta")
    StockPoolSnapshot.objects.create(
        stock_codes=["000001.SZ"],
        regime="Recovery",
        as_of_date=today,
        is_active=True,
        count=1,
    )
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        sector="银行",
        industry="银行",
        is_active=True,
    )
    FinancialDataModel.objects.create(
        stock_code="000001.SZ",
        report_date=today,
        report_type="4Q",
        revenue=Decimal("1000000"),
        net_profit=Decimal("100000"),
        revenue_growth=8.0,
        net_profit_growth=10.0,
        total_assets=Decimal("5000000"),
        total_liabilities=Decimal("3000000"),
        equity=Decimal("2000000"),
        roe=12.0,
        roa=2.0,
        debt_ratio=60.0,
    )
    ValuationModel.objects.create(
        stock_code="000001.SZ",
        trade_date=today,
        pe=10.0,
        pb=1.2,
        ps=1.0,
        total_mv=Decimal("1000000000"),
        circ_mv=Decimal("800000000"),
    )
    FinancialFactModel.objects.bulk_create(
        [
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=today,
                period_type="annual",
                metric_code=metric_code,
                value=value,
                unit="元" if metric_code not in {"roe", "roa", "debt_ratio"} else "%",
                source="test",
                report_date=today,
            )
            for metric_code, value in {
                "revenue": Decimal("1000000"),
                "net_profit": Decimal("100000"),
                "revenue_growth": Decimal("8"),
                "net_profit_growth": Decimal("10"),
                "total_assets": Decimal("5000000"),
                "total_liabilities": Decimal("3000000"),
                "equity": Decimal("2000000"),
                "roe": Decimal("12"),
                "roa": Decimal("2"),
                "debt_ratio": Decimal("60"),
            }.items()
        ]
    )
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=today,
        pe_ttm=Decimal("10"),
        pb=Decimal("1.2"),
        ps_ttm=Decimal("1"),
        market_cap=Decimal("1000000000"),
        float_market_cap=Decimal("800000000"),
        source="test",
    )
    tracked_models = (
        StockPoolSnapshot,
        StockInfoModel,
        FinancialDataModel,
        ValuationModel,
        FinancialFactModel,
        ValuationFactModel,
        RegimeLog,
    )
    before = {model: model.objects.count() for model in tracked_models}

    response = authenticated_client.get("/api/equity/pool/?mode=historical")

    after = {model: model.objects.count() for model in tracked_models}
    assert response.status_code == 200
    assert response.json()["stocks"] == [
        {
            "code": "000001.SZ",
            "name": "平安银行",
            "sector": "银行",
            "roe": 12.0,
            "pe": 10.0,
            "pb": 1.2,
            "revenue_growth": 8.0,
            "profit_growth": 10.0,
            "score": None,
        }
    ]
    assert response.json()["sector_distribution"] == [{"sector": "银行", "count": 1}]
    assert after == before
    assert cache.get("equity:stock_pool:current") is None
    assert cache.get("equity:stock_pool:meta") is None


@pytest.mark.django_db
def test_equity_pool_keeps_missing_metrics_explicit(authenticated_client):
    today = timezone.localdate()
    StockPoolSnapshot.objects.create(
        stock_codes=["000001.SZ"],
        regime="Recovery",
        as_of_date=today,
        is_active=True,
        count=1,
    )
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        sector="银行",
        industry="银行",
        is_active=True,
    )

    response = authenticated_client.get("/api/equity/pool/?mode=historical")

    assert response.status_code == 200
    payload = response.json()
    assert payload["avg_roe"] is None
    assert payload["avg_pe"] is None
    assert payload["stocks"][0]["roe"] is None
    assert payload["stocks"][0]["pe"] is None
    assert payload["stocks"][0]["pb"] is None
    assert payload["stocks"][0]["score"] is None


@pytest.mark.django_db
def test_equity_published_pool_blocks_stale_publication_before_fact_reads(
    authenticated_client,
):
    stale_publication = {
        "publication_id": "equity-pool-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-08-03"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[stale_publication, stale_publication],
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=AssertionError("blocked pool must not read stock facts"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["stocks"] == []
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "publication_observation_stale"


@pytest.mark.django_db
def test_equity_financial_history_is_persisted_only_and_filters_period_type(
    authenticated_client,
):
    metric_values = {
        "revenue": Decimal("100"),
        "net_profit": Decimal("10"),
        "total_assets": Decimal("500"),
        "total_liabilities": Decimal("300"),
        "equity": Decimal("200"),
        "roe": Decimal("5"),
        "debt_ratio": Decimal("60"),
    }
    quarterly_metric_values = {
        **metric_values,
        "revenue": Decimal("75"),
        "net_profit": Decimal("7"),
        "total_assets": Decimal("480"),
        "total_liabilities": Decimal("290"),
        "equity": Decimal("190"),
        "roe": Decimal("4"),
        "debt_ratio": Decimal("60.4"),
    }
    FinancialFactModel.objects.bulk_create(
        [
            FinancialFactModel(
                asset_code="000001.SZ",
                period_end=period_end,
                period_type=period_type,
                metric_code=metric_code,
                value=value,
                unit="元" if metric_code not in {"roe", "debt_ratio"} else "%",
                source="test",
                report_date=period_end,
            )
            for period_end, period_type, values in (
                ("2025-12-31", "annual", metric_values),
                ("2025-09-30", "quarterly", quarterly_metric_values),
            )
            for metric_code, value in values.items()
        ]
    )

    with patch(
        "apps.data_center.application.on_demand.OnDemandDataCenterService.ensure_financials"
    ) as hydrate:
        response = authenticated_client.get(
            "/api/equity/financials/000001.SZ/?report_type=annual&limit=5"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["period_type"] == "annual"
    assert payload["results"][0]["report_date"] == "2025-12-31"
    hydrate.assert_not_called()


@pytest.mark.django_db
def test_equity_financial_history_rejects_invalid_path_stock_code(authenticated_client):
    response = authenticated_client.get("/api/equity/financials/BAD:CODE/")

    assert response.status_code == 400
    assert "BAD:CODE" not in response.content.decode()


@pytest.mark.django_db
def test_equity_published_financial_history_blocks_stale_publication_before_read(
    authenticated_client,
):
    stale_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }

    with (
        patch(
            "apps.equity.interface.sdk_contract_actions.get_decision_publication_gate",
            return_value=stale_publication,
        ),
        patch(
            "apps.equity.interface.sdk_contract_actions.list_stock_financial_payloads",
            side_effect=AssertionError("blocked publication must not query facts"),
        ),
    ):
        response = authenticated_client.get("/api/equity/financials/000001.SZ/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["results"] == []
    assert payload["count"] == 0
    assert payload["publication_id"] == stale_publication["publication_id"]
    assert payload["blocked_reason"] == "publication_observation_stale"
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
def test_equity_published_financial_history_reads_canonical_facts_only(authenticated_client):
    fresh_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "observed_at": "2026-08-03T07:00:00+00:00",
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
    }
    canonical_payload = {
        "rows": [
            {
                "asset_code": "000001.SZ",
                "period_end": "2025-12-31",
                "period_type": "annual",
                "metric_code": "revenue",
                "value": 100.0,
                "unit": "元",
                "source": "canonical-test",
                "report_date": "2026-03-01",
                "fetched_at": "2026-08-03T07:00:00+00:00",
            },
            {
                "asset_code": "000001.SZ",
                "period_end": "2025-12-31",
                "period_type": "annual",
                "metric_code": "roe",
                "value": 12.5,
                "unit": "%",
                "source": "canonical-test",
                "report_date": "2026-03-01",
                "fetched_at": "2026-08-03T07:00:00+00:00",
            },
        ],
        **fresh_publication,
    }

    with (
        patch(
            "apps.equity.interface.sdk_contract_actions.get_decision_publication_gate",
            return_value=fresh_publication,
        ),
        patch(
            "apps.equity.interface.sdk_contract_actions.get_published_financial_facts",
            return_value=canonical_payload,
        ),
        patch(
            "apps.equity.interface.sdk_contract_actions.list_stock_financial_payloads",
            side_effect=AssertionError("published mode must not read legacy financial rows"),
        ),
    ):
        response = authenticated_client.get("/api/equity/financials/000001.SZ/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "published"
    assert payload["count"] == 1
    assert payload["results"][0]["period_end"] == "2025-12-31"
    assert payload["results"][0]["report_date"] == "2026-03-01"
    assert payload["results"][0]["revenue"] == "100.0"
    assert payload["results"][0]["roe"] == 12.5
    assert payload["must_not_use_for_decision"] is False


@pytest.mark.django_db
def test_equity_refresh_pool_requires_staff(authenticated_client):
    response = authenticated_client.post("/api/equity/pool/refresh/", {}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_equity_refresh_pool_returns_503_when_regime_missing(
    authenticated_client,
    auth_user,
):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])

    with patch("apps.regime.application.current_regime.resolve_current_regime", return_value=None):
        response = authenticated_client.post("/api/equity/pool/refresh/", {}, format="json")

    assert response.status_code == 503
    assert response.json()["message"] == "当前 Regime 不可用或处于降级状态，请先完成正式判定"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/equity/pool/?unexpected=true", None),
        ("post", "/api/equity/pool/refresh/", {"unexpected": True}),
    ],
)
def test_equity_pool_actions_reject_unknown_inputs(
    authenticated_client,
    auth_user,
    method,
    path,
    payload,
):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])

    if method == "get":
        response = authenticated_client.get(path)
    else:
        response = authenticated_client.post(path, payload, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_equity_refresh_pool_preserves_existing_pool_when_screen_is_empty(
    authenticated_client,
    auth_user,
):
    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    captured = {}
    empty_response = SimpleNamespace(success=True, stock_codes=[], error=None)

    def execute(request):
        captured["max_count"] = request.max_count
        return empty_response

    fake_use_case = SimpleNamespace(execute=execute)

    with (
        patch(
            "apps.regime.application.current_regime.resolve_current_regime",
            return_value=SimpleNamespace(
                dominant_regime="Recovery",
                is_fallback=False,
            ),
        ),
        patch(
            "apps.equity.interface.pool_actions.ScreenStocksUseCase",
            return_value=fake_use_case,
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.save_pool"
        ) as save_pool,
    ):
        response = authenticated_client.post("/api/equity/pool/refresh/", {}, format="json")

    assert response.status_code == 422
    assert response.json()["message"] == "筛选结果为空，已保留现有股票池"
    assert captured["max_count"] is None
    save_pool.assert_not_called()


@pytest.mark.django_db
def test_equity_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch(
        "apps.equity.application.services.EquityMultiDimScorer.screen_stocks",
        side_effect=RuntimeError("database-password=private"),
    ):
        response = authenticated_client.post(
            "/api/equity/multidim-screen/",
            {
                "filters": {"sector": "银行"},
                "context": {"regime": "Recovery", "policy_level": "P0", "sentiment_index": 0.1},
                "max_count": 10,
            },
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert payload["message"] == "筛选服务暂时不可用"
    assert "database-password" not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    (
        {"filters": [], "context": {}},
        {"filters": {"unknown": "value"}, "context": {}},
        {"filters": {}, "context": {"sentiment_index": "NaN"}},
        {"filters": {}, "context": {}, "max_count": 0},
        {"filters": {}, "context": {}, "unexpected": True},
    ),
)
def test_equity_multidim_screen_rejects_invalid_request_shapes(
    authenticated_client,
    payload,
):
    response = authenticated_client.post(
        "/api/equity/multidim-screen/",
        payload,
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_equity_sync_financial_data_returns_task_payload(authenticated_client):
    task_payload = {"success": True, "queued": True, "task_id": "sync-123"}

    with patch(
        "apps.equity.application.tasks_valuation_sync.sync_financial_data_task",
        return_value=task_payload,
    ) as mock_task:
        response = authenticated_client.post(
            "/api/equity/financial-data/sync/",
            {"stock_codes": ["600519.SH"], "periods": 4, "source": "akshare"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == task_payload
    mock_task.assert_called_once_with(
        source="akshare",
        periods=4,
        stock_codes=["600519.SH"],
    )


@pytest.mark.django_db
def test_equity_technical_chart_rejects_invalid_timeframe(authenticated_client):
    response = authenticated_client.get("/api/equity/technical/000001.SZ/?timeframe=bad")

    assert response.status_code == 400
    assert "timeframe" in response.json()["details"]


@pytest.mark.django_db
def test_equity_technical_chart_returns_candles_and_latest_signal(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    PriceBarModel.objects.bulk_create(
        [
            PriceBarModel(
                asset_code="000001.SZ",
                bar_date=today - timedelta(days=21 - index),
                freq="1d",
                adjustment="none",
                open="10.00",
                high="10.60",
                low="9.90",
                close="10.50" if index == 20 else "10.00",
                volume=1000 + index,
                amount="1000000.00",
                source="test",
            )
            for index in range(21)
        ]
    )

    response = authenticated_client.get(
        "/api/equity/technical/000001.SZ/?timeframe=day&lookback_days=30"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "000001.SZ"
    assert len(payload["candles"]) == 21
    assert payload["latest_signal"]["signal_type"] == "golden_cross"
    assert payload["candles"][-1]["close"] == 10.5
    assert payload["observed_at"] == payload["candles"][-1]["trade_date"]
    assert payload["freshness_status"] == "fresh"
    assert payload["must_not_use_for_decision"] is False
    assert payload["blocked_reason"] is None


@pytest.mark.django_db
def test_equity_technical_chart_preserves_stale_observation_diagnostics(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    stale_date = today - timedelta(days=30)
    technical_bars = [
        TechnicalBar(
            stock_code="000001.SZ",
            trade_date=stale_date - timedelta(days=1 - index),
            open=Decimal("10.00"),
            high=Decimal("10.60"),
            low=Decimal("9.90"),
            close=Decimal("10.00"),
            volume=1000 + index,
            amount=Decimal("1000000.00"),
            ma5=None,
            ma20=None,
            ma60=None,
            macd=None,
            macd_signal=None,
            macd_hist=None,
            rsi=None,
        )
        for index in range(2)
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_technical_bars",
        return_value=technical_bars,
    ):
        response = authenticated_client.get(
            "/api/equity/technical/000001.SZ/?timeframe=day&lookback_days=30"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["candles"]
    assert payload["observed_at"] == stale_date.isoformat()
    assert payload["freshness_status"] == "stale"
    assert payload["must_not_use_for_decision"] is True
    assert payload["blocked_reason"] == "technical_observation_stale"


@pytest.mark.django_db
def test_equity_intraday_chart_returns_points(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="000001.SZ",
        name="平安银行",
        sector="银行",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        short_name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )

    intraday_points = [
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 30, 0, tzinfo=UTC),
            price=10.98,
            avg_price=10.98,
            volume=4482,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 31, 0, tzinfo=UTC),
            price=11.00,
            avg_price=10.99,
            volume=42820,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_intraday_points",
        return_value=intraday_points,
    ):
        response = authenticated_client.get("/api/equity/intraday/000001.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "000001.SZ"
    assert len(payload["points"]) == 2
    assert payload["latest_point"]["price"] == 11.0
    assert payload["session_date"] == "2026-04-03"


@pytest.mark.django_db
def test_equity_intraday_chart_degrades_cleanly_when_sources_fail(authenticated_client):
    today = timezone.localdate()
    StockInfoModel.objects.create(
        stock_code="002709.SZ",
        name="天赐材料",
        sector="化工",
        market="SZ",
        list_date=today,
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="002709.SZ",
        name="天赐材料",
        short_name="天赐材料",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_intraday_points",
        side_effect=DataFetchError(message="002709.SZ 分时主备数据源均不可用"),
    ):
        response = authenticated_client.get("/api/equity/intraday/002709.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["stock_code"] == "002709.SZ"
    assert payload["stock_name"] == "天赐材料"
    assert payload["points"] == []
    assert "主备数据源均不可用" in payload["error"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    (
        "lookback_days=29",
        "lookback_days=1261",
        "lookback_days=invalid",
        "as_of_date=2026-07-12",
        "unknown=value",
    ),
)
def test_equity_valuation_rejects_invalid_or_unknown_query(
    authenticated_client,
    query,
):
    response = authenticated_client.get(f"/api/equity/valuation/300308.SZ/?{query}")

    assert response.status_code == 400


@pytest.mark.django_db
def test_equity_published_valuation_blocks_stale_publication_before_use_case(
    authenticated_client,
):
    fresh_financial_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
    }
    stale_valuation_publication = {
        "publication_id": "equity-valuation-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            side_effect=[
                fresh_financial_publication,
                stale_valuation_publication,
                fresh_financial_publication,
            ],
        ),
        patch(
            "apps.equity.interface.analysis_actions.AnalyzeValuationUseCase",
            side_effect=AssertionError("blocked publication must not run valuation"),
        ),
    ):
        response = authenticated_client.get("/api/equity/valuation/300308.SZ/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "blocked"
    assert payload["stock_code"] == "300308.SZ"
    assert payload["publication_id"] == stale_valuation_publication["publication_id"]
    assert payload["error"] == "publication_observation_stale"
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
def test_equity_published_valuation_blocks_stale_financial_publication_before_use_case(
    authenticated_client,
):
    stale_financial_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }
    fresh_valuation_publication = {
        "publication_id": "equity-valuation-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
    }

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            side_effect=[
                stale_financial_publication,
                fresh_valuation_publication,
                fresh_valuation_publication,
            ],
        ),
        patch(
            "apps.equity.interface.analysis_actions.AnalyzeValuationUseCase",
            side_effect=AssertionError("blocked publication must not run valuation"),
        ),
    ):
        response = authenticated_client.get("/api/equity/valuation/300308.SZ/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "blocked"
    assert payload["error"] == "publication_observation_stale"
    assert payload["publication_id"] == stale_financial_publication["publication_id"]
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
def test_equity_published_screen_blocks_stale_publication_before_use_case(
    authenticated_client,
):
    stale_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            return_value=stale_publication,
        ),
        patch(
            "apps.equity.interface.analysis_actions.ScreenStocksUseCase",
            side_effect=AssertionError("blocked publication must not run screening"),
        ),
    ):
        response = authenticated_client.post(
            "/api/equity/screen/",
            {"mode": "published", "regime": "Recovery"},
            format="json",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["status"] == "blocked"
    assert payload["stock_codes"] == []
    assert payload["error"] == "publication_observation_stale"
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "use_case_path", "expected_marker"),
    (
        (
            "/api/equity/dcf/",
            "apps.equity.interface.analysis_actions.CalculateDCFUseCase",
            "intrinsic_value",
        ),
        (
            "/api/equity/comprehensive-valuation/",
            "apps.equity.interface.analysis_actions.ComprehensiveValuationUseCase",
            "overall_score",
        ),
    ),
)
def test_equity_published_valuation_calculators_block_stale_publication_before_use_case(
    authenticated_client,
    path: str,
    use_case_path: str,
    expected_marker: str,
):
    stale_publication = {
        "publication_id": "equity-financials-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "publication_observation_stale",
        "freshness_status": "stale",
    }
    payload = {"stock_code": "300308.SZ", "mode": "published"}

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            return_value=stale_publication,
        ),
        patch(use_case_path, side_effect=AssertionError("blocked publication must not run")),
    ):
        response = authenticated_client.post(path, payload, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["status"] == "blocked"
    assert body["error"] == "publication_observation_stale"
    assert body["must_not_use_for_decision"] is True
    assert expected_marker in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "use_case_path", "payload", "expected_marker"),
    (
        (
            "post",
            "/api/equity/screen/",
            "apps.equity.interface.analysis_actions.ScreenStocksUseCase",
            {"mode": "published", "regime": "Recovery"},
            "stock_codes",
        ),
        (
            "get",
            "/api/equity/valuation/300308.SZ/?mode=published",
            "apps.equity.interface.analysis_actions.AnalyzeValuationUseCase",
            None,
            "latest_valuation",
        ),
        (
            "post",
            "/api/equity/dcf/",
            "apps.equity.interface.analysis_actions.CalculateDCFUseCase",
            {"stock_code": "300308.SZ", "mode": "published"},
            "intrinsic_value",
        ),
        (
            "post",
            "/api/equity/comprehensive-valuation/",
            "apps.equity.interface.analysis_actions.ComprehensiveValuationUseCase",
            {"stock_code": "300308.SZ", "mode": "published"},
            "overall_score",
        ),
    ),
)
def test_equity_published_reads_block_without_member_snapshot(
    authenticated_client,
    method: str,
    path: str,
    use_case_path: str,
    payload: dict[str, object] | None,
    expected_marker: str,
):
    fresh_publication = {
        "publication_id": "equity-data-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "observed_at": "2026-08-03T07:00:00+00:00",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
    }

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            side_effect=[fresh_publication, fresh_publication, fresh_publication],
        ),
        patch(use_case_path, side_effect=AssertionError("member snapshot absence must block")),
    ):
        if method == "get":
            response = authenticated_client.get(path)
        else:
            response = authenticated_client.post(path, payload, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["status"] == "blocked"
    assert body["error"] == "canonical_publication_member_snapshot_missing"
    assert body["must_not_use_for_decision"] is True
    assert expected_marker in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "use_case_path", "payload", "expected_marker"),
    (
        (
            "get",
            "/api/equity/valuation/300308.SZ/?mode=published",
            "apps.equity.interface.analysis_actions.AnalyzeValuationUseCase",
            None,
            "latest_valuation",
        ),
        (
            "post",
            "/api/equity/dcf/",
            "apps.equity.interface.analysis_actions.CalculateDCFUseCase",
            {"stock_code": "300308.SZ", "mode": "published"},
            "intrinsic_value",
        ),
        (
            "post",
            "/api/equity/comprehensive-valuation/",
            "apps.equity.interface.analysis_actions.ComprehensiveValuationUseCase",
            {"stock_code": "300308.SZ", "mode": "published"},
            "overall_score",
        ),
    ),
)
def test_equity_published_valuation_reads_block_stale_price_publication(
    authenticated_client,
    method: str,
    path: str,
    use_case_path: str,
    payload: dict[str, object] | None,
    expected_marker: str,
):
    fresh_publication = {
        "publication_id": "equity-data-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
    }
    stale_price_publication = {
        "publication_id": "equity-prices-2026-08-03",
        "published_at": "2026-08-03T08:00:00+00:00",
        "as_of": "2026-07-31",
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_stale",
        "freshness_status": "stale",
    }

    with (
        patch(
            "apps.equity.interface.analysis_actions.get_decision_publication_gate",
            side_effect=[fresh_publication, fresh_publication, stale_price_publication],
        ),
        patch(use_case_path, side_effect=AssertionError("stale price must block before use case")),
    ):
        if method == "get":
            response = authenticated_client.get(path)
        else:
            response = authenticated_client.post(path, payload, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["status"] == "blocked"
    assert body["error"] == "canonical_publication_stale"
    assert body["must_not_use_for_decision"] is True
    assert expected_marker in body


@pytest.mark.django_db
def test_equity_valuation_returns_basic_info_when_valuation_missing(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    PriceBarModel.objects.create(
        asset_code="300308.SZ",
        bar_date=today,
        freq="1d",
        adjustment="none",
        open="600.00",
        high="610.00",
        low="598.00",
        close="606.52",
        volume="100000.00",
        amount="60652000.00",
        source="test",
    )

    tracked_before = {
        "assets": list(
            AssetMasterModel.objects.order_by("id").values_list(
                "id",
                "updated_at",
            )
        ),
        "aliases": list(AssetAliasModel.objects.order_by("id").values_list("id", "created_at")),
        "prices": list(PriceBarModel.objects.order_by("id").values_list("id", "fetched_at")),
        "valuations": list(
            ValuationFactModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "financials": list(
            FinancialFactModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "legacy_stocks": list(
            StockInfoModel.objects.order_by("id").values_list("id", "updated_at")
        ),
        "legacy_prices": list(
            StockDailyModel.objects.order_by("id").values_list("id", "created_at")
        ),
        "legacy_valuations": list(
            ValuationModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "legacy_financials": list(
            FinancialDataModel.objects.order_by("id").values_list("id", "updated_at")
        ),
    }
    on_demand = SimpleNamespace(
        ensure_valuations=lambda *args, **kwargs: pytest.fail(
            "valuation GET must not hydrate valuations"
        ),
        ensure_financials=lambda *args, **kwargs: pytest.fail(
            "valuation GET must not hydrate financials"
        ),
        ensure_price_bars=lambda *args, **kwargs: pytest.fail(
            "valuation GET must not hydrate prices"
        ),
    )

    with patch(
        "apps.equity.infrastructure.repositories.make_on_demand_data_center_service",
        return_value=on_demand,
    ):
        response = authenticated_client.get("/api/equity/valuation/300308.SZ/?lookback_days=365")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert payload["market"] == "SZ"
    assert payload["latest_valuation"]["price"] == 606.52
    assert payload["latest_valuation"]["pe"] is None
    assert "估值数据" in payload["error"]
    assert {
        "assets": list(
            AssetMasterModel.objects.order_by("id").values_list(
                "id",
                "updated_at",
            )
        ),
        "aliases": list(AssetAliasModel.objects.order_by("id").values_list("id", "created_at")),
        "prices": list(PriceBarModel.objects.order_by("id").values_list("id", "fetched_at")),
        "valuations": list(
            ValuationFactModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "financials": list(
            FinancialFactModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "legacy_stocks": list(
            StockInfoModel.objects.order_by("id").values_list("id", "updated_at")
        ),
        "legacy_prices": list(
            StockDailyModel.objects.order_by("id").values_list("id", "created_at")
        ),
        "legacy_valuations": list(
            ValuationModel.objects.order_by("id").values_list("id", "fetched_at")
        ),
        "legacy_financials": list(
            FinancialDataModel.objects.order_by("id").values_list("id", "updated_at")
        ),
    } == tracked_before


@pytest.mark.django_db
def test_equity_intraday_chart_uses_data_center_stock_info(authenticated_client):
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    intraday_points = [
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 30, 0, tzinfo=UTC),
            price=606.00,
            avg_price=606.00,
            volume=1234,
        ),
        SimpleNamespace(
            timestamp=datetime(2026, 4, 3, 9, 31, 0, tzinfo=UTC),
            price=606.52,
            avg_price=606.26,
            volume=5678,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository.get_intraday_points",
        return_value=intraday_points,
    ):
        response = authenticated_client.get("/api/equity/intraday/300308.SZ/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["points"]) == 2
    assert payload["latest_point"]["price"] == 606.52


@pytest.mark.django_db
def test_equity_technical_chart_uses_tushare_gateway_bar_fallback(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    remote_bars = [
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=2),
            open=600.0,
            high=612.0,
            low=598.0,
            close=606.0,
            volume=100000,
            amount=60000000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=1),
            open=606.0,
            high=625.0,
            low=594.35,
            close=606.52,
            volume=290271,
            amount=17694513.705,
        ),
    ]

    with patch(
        "apps.equity.infrastructure.repositories.DjangoStockRepository._get_tushare_gateway_historical_bars",
        return_value=remote_bars,
    ):
        response = authenticated_client.get(
            "/api/equity/technical/300308.SZ/?timeframe=day&lookback_days=30"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["candles"]) == 2
    assert payload["candles"][-1]["close"] == 606.52
    cached_rows = PriceBarModel.objects.filter(asset_code="300308.SZ").order_by("bar_date")
    assert cached_rows.count() == 2
    assert cached_rows.last().close == Decimal("606.52")


@pytest.mark.django_db
def test_equity_regime_correlation_uses_tushare_gateway_daily_price_fallback(authenticated_client):
    today = timezone.localdate()
    asset = AssetMasterModel.objects.create(
        code="300308.SZ",
        name="中际旭创",
        short_name="中际旭创",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetAliasModel.objects.create(
        asset=asset,
        provider_name="legacy",
        alias_code="300308",
    )
    remote_bars = [
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=2),
            open=598.0,
            high=602.0,
            low=596.0,
            close=600.0,
            volume=100000,
            amount=59800000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today - timedelta(days=1),
            open=600.0,
            high=608.0,
            low=599.0,
            close=606.0,
            volume=120000,
            amount=72600000.0,
        ),
        SimpleNamespace(
            asset_code="300308",
            trade_date=today,
            open=606.0,
            high=607.0,
            low=603.0,
            close=606.52,
            volume=90000,
            amount=54586800.0,
        ),
    ]
    remote_prices = [
        (today - timedelta(days=2), Decimal("600.00")),
        (today - timedelta(days=1), Decimal("606.00")),
        (today, Decimal("606.52")),
    ]
    regime_history = {
        today - timedelta(days=1): "Recovery",
        today: "Overheat",
    }
    market_returns = {
        today - timedelta(days=1): 0.005,
        today: 0.001,
    }

    with (
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository._get_tushare_gateway_historical_bars",
            return_value=remote_bars,
        ),
        patch(
            "apps.equity.application.use_cases.AnalyzeRegimeCorrelationUseCase._get_regime_history",
            return_value=regime_history,
        ),
        patch(
            "apps.equity.application.use_cases.AnalyzeRegimeCorrelationUseCase._get_market_returns",
            return_value=market_returns,
        ),
    ):
        response = authenticated_client.get(
            "/api/equity/regime-correlation/300308.SZ/?lookback_days=252"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stock_code"] == "300308.SZ"
    assert payload["stock_name"] == "中际旭创"
    assert len(payload["regime_performance"]) == 4
    cached_rows = PriceBarModel.objects.filter(asset_code="300308.SZ").order_by("bar_date")
    assert cached_rows.count() == len(remote_prices)
    assert cached_rows.last().close == Decimal("606.52")


def test_screen_stocks_serializer_folds_flat_tui_fields_into_custom_rule():
    serializer = ScreenStocksRequestSerializer(
        data={
            "regime": "Recovery",
            "min_roe": 15,
            "max_pe": 30,
            "max_pb": 5,
            "min_revenue_growth": 10,
            "min_profit_growth": 8,
            "max_debt_ratio": 70,
            "max_count": 20,
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["custom_rule"] == {
        "min_roe": 15.0,
        "max_pe": 30.0,
        "max_pb": 5.0,
        "min_revenue_growth": 10.0,
        "min_profit_growth": 8.0,
        "max_debt_ratio": 70.0,
    }
    assert serializer.validated_data["max_count"] == 20
