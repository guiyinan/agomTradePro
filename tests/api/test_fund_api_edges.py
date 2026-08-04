from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.fund.domain.entities import FundHolding, FundInfo, FundNetValue, FundScore
from apps.fund.infrastructure.models import (
    FundInfoModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
    FundTypePreferenceConfigModel,
)
from apps.fund.infrastructure.repositories import DjangoFundRepository
from apps.regime.infrastructure.models import RegimeLog
from core.exceptions import MissingConfigError


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
def test_fund_rank_reports_missing_preferences_as_configuration_conflict(
    authenticated_client,
):
    with patch(
        "apps.fund.interface.views.interface_services.rank_funds",
        side_effect=MissingConfigError("private configuration details"),
    ):
        response = authenticated_client.get(
            "/api/fund/rank/",
            {"regime": "Recovery", "max_count": 20},
        )

    assert response.status_code == 409
    assert response.json() == {
        "success": False,
        "error": "fund_ranking_preferences_unavailable",
    }
    assert "private configuration details" not in response.content.decode("utf-8")


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
        model._meta.label: list(model.objects.order_by("pk").values()) for model in tracked_models
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
        score_response = authenticated_client.get(
            "/api/fund/score/000001/",
            {"regime": "Recovery"},
        )

    assert screen_response.status_code == 200
    assert screen_response.json()["success"] is True
    assert screen_response.json()["regime"] == "Recovery"
    assert screen_response.json()["fund_codes"] == ["000001"]
    assert screen_response.json()["fund_names"] == ["持久化成长基金"]
    assert rank_response.status_code == 200
    assert rank_response.json()["count"] == 1
    assert rank_response.json()["funds"][0]["fund_code"] == "000001"
    assert score_response.status_code == 200
    assert score_response.json()["score"]["fund_code"] == "000001"
    assert score_response.json()["score"]["rank"] == 1
    after = {
        model._meta.label: list(model.objects.order_by("pk").values()) for model in tracked_models
    }
    assert after == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/fund/screen/", {"unknown": True}),
        ("get", "/api/fund/rank/", {"unknown": True}),
        ("get", "/api/fund/score/000001/", {"unknown": True}),
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
        ("get", "/api/fund/score/000001/"),
        ("get", "/api/fund/style/000001/"),
        ("post", "/api/fund/performance/calculate/"),
        ("get", "/api/fund/info/000001/"),
        ("get", "/api/fund/nav/000001/"),
        ("get", "/api/fund/holding/000001/"),
        ("post", "/api/fund/multidim-screen/"),
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
def test_fund_nav_default_reads_published_current_series(authenticated_client):
    with patch(
        "apps.fund.interface.views.interface_services.get_published_fund_nav_payload",
        return_value={
            "rows": [
                {
                    "fund_code": "000001",
                    "nav_date": "2026-07-09",
                    "unit_nav": 1.2345,
                    "accum_nav": 2.3456,
                    "daily_return": 0.42,
                }
            ],
            "publication_id": "fund-pub-1",
            "published_at": "2026-07-10T00:00:00+00:00",
            "as_of": "2026-07-09T00:00:00+00:00",
            "observed_at": "2026-07-09T00:00:00+00:00",
            "freshness_status": "fresh",
            "must_not_use_for_decision": False,
            "blocked_reason": "",
        },
    ) as mock_nav:
        response = authenticated_client.get("/api/fund/nav/000001/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"]["publication_id"] == "fund-pub-1"
    assert payload["contract"]["must_not_use_for_decision"] is False
    assert payload["nav_data"][0]["unit_nav"] == "1.2345"
    mock_nav.assert_called_once_with("000001")


@pytest.mark.django_db
def test_fund_nav_default_blocks_missing_publication(authenticated_client):
    with patch(
        "apps.fund.interface.views.interface_services.get_published_fund_nav_payload",
        return_value={
            "rows": [],
            "publication_id": None,
            "freshness_status": "missing",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        },
    ):
        response = authenticated_client.get("/api/fund/nav/000001/")

    assert response.status_code == 409
    assert response.json()["contract"]["blocked_reason"] == "canonical_publication_missing"


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

    with patch(
        "apps.fund.interface.views.AnalyzeFundStyleUseCase.execute", return_value=response_obj
    ):
        response = authenticated_client.get("/api/fund/style/000001/")

    assert response.status_code == 404
    assert response.json()["success"] is False
    assert response.json()["error"] == "fund not found"


@pytest.mark.django_db
def test_fund_multidim_screen_returns_500_on_exception(authenticated_client):
    with patch(
        "apps.fund.application.services.FundMultiDimScorer.screen_funds",
        side_effect=RuntimeError("boom"),
    ):
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
    assert "boom" not in str(payload)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/fund/performance/calculate/",
            {
                "fund_code": "000001",
                "start_date": "2026-07-10",
                "end_date": "2026-07-01",
            },
        ),
        (
            "get",
            "/api/fund/nav/000001/",
            {"start_date": "2026-07-10", "end_date": "2026-07-01"},
        ),
        ("get", "/api/fund/nav/000001/", {"start_date": "not-a-date"}),
        ("get", "/api/fund/holding/000001/", {"report_date": "not-a-date"}),
        (
            "post",
            "/api/fund/multidim-screen/",
            {"filters": {}, "max_count": 10},
        ),
    ],
)
def test_fund_contracts_reject_invalid_dates_and_missing_context(
    authenticated_client,
    method,
    path,
    payload,
):
    response = getattr(authenticated_client, method)(path, payload, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_fund_multidim_empty_result_is_a_successful_empty_state(authenticated_client):
    response = authenticated_client.post(
        "/api/fund/multidim-screen/",
        {
            "filters": {"fund_type": "不存在类型"},
            "context": {
                "regime": "Recovery",
                "policy_level": "P0",
                "sentiment_index": 0.0,
            },
            "max_count": 10,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["count"] == 0


def test_fund_multidim_screen_folds_flat_tui_fields_at_interface_boundary(
    authenticated_client,
):
    context = type(
        "FundContext",
        (),
        {
            "current_regime": "Recovery",
            "policy_level": "P1",
            "sentiment_index": 0.2,
        },
    )()
    with patch(
        "apps.fund.interface.views.interface_services.screen_funds_multidim",
        return_value={
            "result": {"success": True, "count": 0, "funds": []},
            "context": context,
            "active_signals_count": 0,
        },
    ) as screen:
        response = authenticated_client.post(
            "/api/fund/tui-multidim-screen/",
            {
                "fund_type": "股票型",
                "investment_style": "成长",
                "min_scale": 1000000000,
                "regime": "Recovery",
                "policy_level": "P1",
                "sentiment_index": 0.2,
                "max_count": 20,
            },
            format="json",
        )

    assert response.status_code == 200
    screen.assert_called_once_with(
        filters={
            "fund_type": "股票型",
            "investment_style": "成长",
            "min_scale": Decimal("1000000000.00"),
        },
        context_data={
            "regime": "Recovery",
            "policy_level": "P1",
            "sentiment_index": 0.2,
        },
        max_count=20,
    )


def test_fund_tui_multidim_screen_requires_complete_scoring_context(
    authenticated_client,
):
    """The flat TUI contract rejects context that Application cannot score."""

    response = authenticated_client.post(
        "/api/fund/tui-multidim-screen/",
        {"regime": "Recovery", "max_count": 20},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert set(response.json()["details"]) == {"policy_level", "sentiment_index"}
