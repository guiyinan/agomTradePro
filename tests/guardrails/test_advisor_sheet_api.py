from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.decision_rhythm.application.advisor_services import AdvisorAccessError


@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username="advisor_api_user", password="testpass")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_advisor_sheet_requires_account_id(authenticated_client):
    response = authenticated_client.get("/api/decision/advisor/sheet/")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert "account_id" in payload["error"]


@pytest.mark.django_db
def test_advisor_sheet_maps_account_access_error(authenticated_client, monkeypatch):
    def fake_execute(self, *, account_id, user):
        raise AdvisorAccessError("无权查看该账户", 403)

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.advisor_api_views.GenerateAdvisorDecisionSheetUseCase.execute",
        fake_execute,
    )

    response = authenticated_client.get("/api/decision/advisor/sheet/?account_id=9")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "无权查看该账户"


@pytest.mark.django_db
def test_advisor_sheet_returns_account_holdings_allocation_and_order_intents(
    authenticated_client,
    monkeypatch,
):
    def fake_execute(self, *, account_id, user):
        return {
            "account": {"account_id": account_id, "account_name": "A"},
            "baseline": "existing_positions",
            "today_conclusion": "ACT",
            "holdings": [{"asset_code": "AAA"}],
            "allocation": [{"asset_class": "equity"}],
            "order_intents": [{"order_intent_id": "oi_1", "side": "BUY"}],
            "order_summary": {"total": 1},
            "blockers": [],
            "next_actions": [],
        }

    monkeypatch.setattr(
        "apps.decision_rhythm.interface.advisor_api_views.GenerateAdvisorDecisionSheetUseCase.execute",
        fake_execute,
    )

    response = authenticated_client.get("/api/decision/advisor/sheet/?account_id=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["today_conclusion"] in {"ACT", "REVIEW", "WAIT", "BLOCKED"}
    assert "holdings" in data
    assert "allocation" in data
    assert "order_intents" in data


@pytest.mark.django_db
def test_advisor_sheet_default_chain_is_pure_read_for_manual_portfolio(
    authenticated_client,
):
    from apps.account.infrastructure.models import (
        PortfolioModel,
        PositionModel as LegacyPositionModel,
    )
    from apps.dashboard.infrastructure.models import (
        AutoAdvisorNotificationModel,
        AutoAdvisorWeeklyReportModel,
    )
    from apps.data_center.infrastructure.models import (
        MarketThermometerSnapshotModel,
        QuoteSnapshotModel,
    )
    from apps.decision_rhythm.infrastructure.models import (
        CooldownPeriodModel,
        DecisionQuotaModel,
        UnifiedRecommendationModel,
    )
    from apps.regime.infrastructure.models import ActionRecommendationLog
    from apps.risk_center.infrastructure.models import (
        AccountRiskPolicyModel,
        GlobalRiskFloorModel,
        RiskDailyReportModel,
        RiskExceptionModel,
        RiskPolicyAuditModel,
        RiskTemplateModel,
    )
    from apps.simulated_trading.infrastructure.models import (
        LedgerMigrationMapModel,
        PositionModel as UnifiedPositionModel,
        SimulatedAccountModel,
    )

    user = User.objects.get(username="advisor_api_user")
    account = SimulatedAccountModel._default_manager.get(
        user=user,
        account_type="real",
    )
    portfolio = PortfolioModel._default_manager.create(
        user=user,
        name="Advisor manual portfolio",
        is_active=True,
    )
    LegacyPositionModel._default_manager.create(
        portfolio=portfolio,
        asset_code="000001.SZ",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        shares=100,
        avg_cost="10.0000",
        current_price="12.0000",
        market_value="1200.00",
        unrealized_pnl="200.00",
        unrealized_pnl_pct=20.0,
        source="manual",
        is_closed=False,
    )
    LedgerMigrationMapModel._default_manager.create(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.id,
        target_table="simulated_account",
        target_id=account.id,
    )

    tracked_models = (
        PortfolioModel,
        LegacyPositionModel,
        SimulatedAccountModel,
        UnifiedPositionModel,
        LedgerMigrationMapModel,
        UnifiedRecommendationModel,
        DecisionQuotaModel,
        CooldownPeriodModel,
        QuoteSnapshotModel,
        MarketThermometerSnapshotModel,
        ActionRecommendationLog,
        GlobalRiskFloorModel,
        RiskTemplateModel,
        AccountRiskPolicyModel,
        RiskExceptionModel,
        RiskPolicyAuditModel,
        RiskDailyReportModel,
        AutoAdvisorWeeklyReportModel,
        AutoAdvisorNotificationModel,
    )
    before_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }

    responses = {
        "sheet": authenticated_client.get(
            "/api/decision/advisor/sheet/",
            {"account_id": account.id},
        ),
        "console": authenticated_client.get(
            "/api/dashboard/auto-advisor-console/",
            {"account_id": account.id},
        ),
        "query": authenticated_client.get(
            "/api/dashboard/auto-advisor-query/",
            {
                "account_id": account.id,
                "question": "最大风险是什么",
            },
        ),
        "weekly_report": authenticated_client.get(
            "/api/dashboard/auto-advisor-weekly-report/",
            {
                "account_id": account.id,
                "as_of": "2026-07-11",
            },
        ),
    }

    for response in responses.values():
        assert response.status_code == 200
        assert response.json()["success"] is True

    sheet_payload = responses["sheet"].json()
    assert any(
        holding["asset_code"] == "000001.SZ"
        for holding in sheet_payload["data"]["holdings"]
    )
    assert responses["console"].json()["data"]["status"] == "ok"
    assert responses["query"].json()["data"]["query"]["intent"] == "largest_risk"
    assert responses["weekly_report"].json()["data"]["week"]["as_of"] == "2026-07-11"
    after_counts = {
        model._meta.label_lower: model._default_manager.count()
        for model in tracked_models
    }
    assert after_counts == before_counts
