from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.fund.domain.entities import FundHolding, FundInfo, FundNetValue, FundScore
from apps.fund.infrastructure.models import (
    FundInfoModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
    FundTypePreferenceConfigModel,
)
from apps.fund.infrastructure.repositories import DjangoFundRepository
from apps.regime.infrastructure.models import RegimeLog


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="fund_user",
        password="testpass123",
        email="fund@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.mark.django_db
def test_fund_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/fund/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["screen"] == "/api/fund/screen/"
    assert payload["endpoints"]["multidim_screen"] == "/api/fund/multidim-screen/"


@pytest.mark.django_db
def test_fund_rank_success_contract(authenticated_client):
    scores = [
        FundScore(
            fund_code="000001",
            fund_name="华夏成长",
            score_date=date(2026, 7, 10),
            performance_score=86.0,
            regime_fit_score=92.0,
            risk_score=78.0,
            scale_score=81.0,
            total_score=85.5,
            rank=1,
        )
    ]

    with patch(
        "apps.fund.interface.views.interface_services.rank_funds",
        return_value=scores,
    ) as mock_rank:
        response = authenticated_client.get(
            "/api/fund/rank/",
            {"regime": "Recovery", "max_count": 20},
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "regime": "Recovery",
        "count": 1,
        "funds": [
            {
                "fund_code": "000001",
                "fund_name": "华夏成长",
                "score_date": "2026-07-10",
                "performance_score": 86.0,
                "regime_fit_score": 92.0,
                "risk_score": 78.0,
                "scale_score": 81.0,
                "total_score": 85.5,
                "rank": 1,
            }
        ],
    }
    mock_rank.assert_called_once_with("Recovery", 20)


@pytest.mark.django_db
def test_fund_screen_and_rank_use_persisted_snapshots_without_writes(
    authenticated_client,
):
    today = date.today()
    start_date = today.replace(year=today.year - 1)
    FundInfoModel.objects.create(
        fund_code="000001",
        fund_name="持久化成长基金",
        fund_type="股票型",
        investment_style="成长",
        fund_scale=Decimal("5000000000.00"),
        is_active=True,
    )
    FundPerformanceModel.objects.create(
        fund_code="000001",
        start_date=start_date,
        end_date=today,
        total_return=12.0,
        annualized_return=12.0,
        volatility=8.0,
        sharpe_ratio=1.2,
        max_drawdown=5.0,
    )
    FundSectorAllocationModel.objects.create(
        fund_code="000001",
        report_date=today,
        sector_name="电子",
        allocation_ratio=20.0,
    )
    FundTypePreferenceConfigModel.objects.create(
        regime="Recovery",
        fund_type="股票型",
        style="成长",
        priority=10,
        is_active=True,
    )
    RegimeLog.objects.create(
        observed_at=today,
        growth_momentum_z=0.5,
        inflation_momentum_z=-0.2,
        distribution={"Recovery": 0.8},
        dominant_regime="Recovery",
        confidence=0.8,
    )
    tracked_models = (
        FundInfoModel,
        FundPerformanceModel,
        FundSectorAllocationModel,
        FundTypePreferenceConfigModel,
        RegimeLog,
    )
    before = {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in tracked_models
    }

    with (
        patch.object(
            DjangoFundRepository,
            "ensure_fund_universe_seeded",
            side_effect=AssertionError("fund universe seeding is forbidden"),
        ),
        patch.object(
            DjangoFundRepository,
            "build_and_store_fund_performance",
            side_effect=AssertionError("performance persistence is forbidden"),
        ),
        patch.object(
            DjangoFundRepository,
            "sync_fund_info_from_tushare",
            side_effect=AssertionError("fund provider sync is forbidden"),
        ),
        patch.object(
            DjangoFundRepository,
            "sync_fund_nav_from_tushare",
            side_effect=AssertionError("fund NAV sync is forbidden"),
        ),
    ):
        screen_response = authenticated_client.post(
            "/api/fund/screen/",
            {"max_count": 10},
            format="json",
        )
        rank_response = authenticated_client.get(
            "/api/fund/rank/",
            {"regime": "Recovery", "max_count": 10},
        )

    assert screen_response.status_code == 200
    assert screen_response.json()["success"] is True
    assert screen_response.json()["regime"] == "Recovery"
    assert screen_response.json()["fund_codes"] == ["000001"]
    assert screen_response.json()["fund_names"] == ["持久化成长基金"]
    assert rank_response.status_code == 200
    assert rank_response.json()["count"] == 1
    assert rank_response.json()["funds"][0]["fund_code"] == "000001"
    after = {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in tracked_models
    }
    assert after == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/fund/screen/", {"unknown": True}),
        ("get", "/api/fund/rank/", {"unknown": True}),
    ],
)
def test_fund_research_contracts_reject_unknown_parameters(
    authenticated_client,
    method,
    path,
    payload,
):
    response = getattr(authenticated_client, method)(path, payload, format="json")

    assert response.status_code == 400
    assert "Unknown parameters" in str(response.json())


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/fund/screen/"),
        ("get", "/api/fund/rank/"),
    ],
)
def test_fund_research_contracts_require_authentication(api_client, method, path):
    response = getattr(api_client, method)(path, {}, format="json")

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_fund_detail_success_contract(authenticated_client):
    fund = FundInfo(
        fund_code="000001",
        fund_name="华夏成长",
        fund_type="股票型",
        investment_style="成长",
        setup_date=date(2001, 12, 18),
        management_company="华夏基金",
        custodian="中国建设银行",
        fund_scale=Decimal("1234567890.12"),
    )

    with patch(
        "apps.fund.interface.views.interface_services.get_fund_info",
        return_value=fund,
    ) as mock_detail:
        response = authenticated_client.get("/api/fund/info/000001/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "fund": {
            "fund_code": "000001",
            "fund_name": "华夏成长",
            "fund_type": "股票型",
            "investment_style": "成长",
            "setup_date": "2001-12-18",
            "management_company": "华夏基金",
            "custodian": "中国建设银行",
            "fund_scale": "1234567890.12",
        },
    }
    mock_detail.assert_called_once_with("000001")


@pytest.mark.django_db
def test_fund_nav_history_success_contract(authenticated_client):
    nav_rows = [
        FundNetValue(
            fund_code="000001",
            nav_date=date(2026, 7, 9),
            unit_nav=Decimal("1.2345"),
            accum_nav=Decimal("2.3456"),
            daily_return=0.42,
        )
    ]

    with patch(
        "apps.fund.interface.views.interface_services.get_fund_nav",
        return_value=nav_rows,
    ) as mock_nav:
        response = authenticated_client.get(
            "/api/fund/nav/000001/",
            {"start_date": "2026-07-01", "end_date": "2026-07-10"},
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "fund_code": "000001",
        "count": 1,
        "nav_data": [
            {
                "fund_code": "000001",
                "nav_date": "2026-07-09",
                "unit_nav": "1.2345",
                "accum_nav": "2.3456",
                "daily_return": 0.42,
            }
        ],
    }
    mock_nav.assert_called_once_with(
        "000001",
        date(2026, 7, 1),
        date(2026, 7, 10),
    )


@pytest.mark.django_db
def test_fund_holdings_success_contract(authenticated_client):
    holdings = [
        FundHolding(
            fund_code="000001",
            report_date=date(2026, 6, 30),
            stock_code="600519.SH",
            stock_name="贵州茅台",
            holding_amount=1000,
            holding_value=Decimal("1500000.00"),
            holding_ratio=8.75,
        )
    ]

    with patch(
        "apps.fund.interface.views.interface_services.get_fund_holdings",
        return_value=holdings,
    ) as mock_holdings:
        response = authenticated_client.get(
            "/api/fund/holding/000001/",
            {"report_date": "2026-06-30"},
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "fund_code": "000001",
        "report_date": "2026-06-30",
        "count": 1,
        "holdings": [
            {
                "fund_code": "000001",
                "report_date": "2026-06-30",
                "stock_code": "600519.SH",
                "stock_name": "贵州茅台",
                "holding_amount": 1000,
                "holding_value": "1500000.00",
                "holding_ratio": 8.75,
            }
        ],
    }
    mock_holdings.assert_called_once_with("000001", date(2026, 6, 30))


@pytest.mark.django_db
def test_fund_style_returns_404_when_use_case_reports_missing_fund(authenticated_client):
    response_obj = type(
        "FundStyleResponse",
        (),
        {
            "success": False,
            "fund_code": "000001",
            "fund_name": "",
            "style_weights": {},
            "sector_concentration": {},
            "error": "fund not found",
        },
    )()

    with patch("apps.fund.interface.views.AnalyzeFundStyleUseCase.execute", return_value=response_obj):
        response = authenticated_client.get("/api/fund/style/000001/")

    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"] == "fund not found"


@pytest.mark.django_db
def test_fund_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch("apps.fund.application.services.FundMultiDimScorer.screen_funds", side_effect=RuntimeError("boom")):
        response = authenticated_client.post(
            "/api/fund/multidim-screen/",
            {
                "filters": {"fund_type": "股票型"},
                "context": {"regime": "Recovery", "policy_level": "P0", "sentiment_index": 0.1},
                "max_count": 10,
            },
            format="json",
        )

    assert response.status_code == 500
    payload = response.json()
    assert payload["success"] is False
    assert "筛选失败" in payload["message"]
