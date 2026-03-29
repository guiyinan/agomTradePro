"""Integration tests for the Phase 2 decision funnel workspace."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.audit.infrastructure.models import AttributionReport, ExperienceSummary, LossAnalysis
from apps.backtest.infrastructure.models import BacktestResultModel

pytestmark = pytest.mark.timeout(90)


def _action_recommendation_stub(*recommended_sectors):
    """Build a minimal action recommendation compatible with Step 2 and Step 3."""
    return SimpleNamespace(
        reasoning="测试用资产配置建议",
        regime_contribution=0.6,
        pulse_contribution=0.4,
        position_limit_pct=0.8,
        recommended_sectors=list(recommended_sectors),
        asset_weights={"equity": 0.6, "bond": 0.2, "commodity": 0.1, "cash": 0.1},
        risk_budget_pct=0.7,
    )


@pytest.fixture
def authenticated_client(db):
    """Return a logged-in Django test client."""
    user = User.objects.create_user(
        username="decision-funnel-user",
        email="decision-funnel@example.com",
        password="testpass123",
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def sample_backtest(db):
    """Create a completed backtest for audit replay."""
    return BacktestResultModel.objects.create(
        name="Decision Funnel Backtest",
        status="completed",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 1),
        initial_capital=100000.0,
        final_capital=108000.0,
        total_return=0.08,
        annualized_return=0.16,
        max_drawdown=-0.03,
        sharpe_ratio=1.2,
        equity_curve=[["2026-01-01", 100000.0], ["2026-03-01", 108000.0]],
        regime_history=[{"date": "2026-01-01", "regime": "RECOVERY", "confidence": 0.8}],
        trades=[],
    )


@pytest.fixture
def sample_attribution_report(sample_backtest):
    """Create an existing attribution report and related artifacts."""
    report = AttributionReport.objects.create(
        backtest=sample_backtest,
        period_start=sample_backtest.start_date,
        period_end=sample_backtest.end_date,
        attribution_method="brinson",
        regime_timing_pnl=0.03,
        asset_selection_pnl=0.04,
        interaction_pnl=0.01,
        total_pnl=0.08,
        regime_accuracy=0.75,
        regime_predicted="RECOVERY",
        regime_actual="RECOVERY",
    )
    LossAnalysis.objects.create(
        report=report,
        loss_source="ASSET_SELECTION_ERROR",
        impact=-0.01,
        impact_percentage=12.5,
        description="选股权重分配过于集中。",
        improvement_suggestion="降低单一资产集中度。",
    )
    ExperienceSummary.objects.create(
        report=report,
        lesson="顺周期资产需要配合更严格的仓位控制。",
        recommendation="下次优先检查波动率和仓位上限。",
        priority="HIGH",
    )
    return report


@pytest.mark.django_db
def test_decision_step3_partial_uses_rotation_outputs(authenticated_client):
    """Step 3 partial should render real rotation/action orchestration output."""
    with (
        patch(
            "core.application.decision_context.GetActionRecommendationUseCase.execute",
            return_value=_action_recommendation_stub("科技", "消费"),
        ),
        patch(
            "core.application.decision_context.RotationIntegrationService.get_rotation_recommendation",
            return_value={
                "target_allocation": {
                    "CSI300": 0.42,
                    "GOLD": 0.18,
                }
            },
        ),
        patch(
            "core.application.decision_context.RotationIntegrationService.get_asset_master",
            return_value=[
                {"code": "CSI300", "name": "沪深300", "category": "equity"},
                {"code": "GOLD", "name": "黄金", "category": "equity"},
            ],
        ),
    ):
        response = authenticated_client.get("/api/decision/context/step3/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "科技" in content
    assert "消费" in content
    assert "沪深300" in content
    assert "BUY" in content


@pytest.mark.django_db
def test_decision_audit_api_returns_existing_report(
    authenticated_client,
    sample_attribution_report,
):
    """Standalone audit API should return the current attribution payload."""
    response = authenticated_client.get(
        f"/api/decision/audit/?backtest_id={sample_attribution_report.backtest_id}"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["report_id"] == sample_attribution_report.id
    assert payload["data"]["backtest_id"] == sample_attribution_report.backtest_id
    assert payload["data"]["attribution_method"] == "brinson"
    assert payload["data"]["portfolio_return"] == 8.0
    assert payload["data"]["allocation_effect"] == 3.0
    assert payload["data"]["selection_effect"] == 4.0
    assert payload["data"]["interaction_effect"] == 1.0
    assert payload["data"]["loss_source"] == "资产选择错误"


@pytest.mark.django_db
def test_decision_funnel_context_and_step6_partial(
    authenticated_client,
    sample_attribution_report,
):
    """Context API may expose audit data, but Step 6 partial must stay execution-only."""
    with (
        patch(
            "core.application.decision_context.GetActionRecommendationUseCase.execute",
            return_value=_action_recommendation_stub("科技"),
        ),
        patch(
            "core.application.decision_context.RotationIntegrationService.get_rotation_recommendation",
            return_value={"target_allocation": {"CSI300": 0.4}},
        ),
        patch(
            "core.application.decision_context.RotationIntegrationService.get_asset_master",
            return_value=[{"code": "CSI300", "name": "沪深300", "category": "equity"}],
        ),
    ):
        context_response = authenticated_client.get(
            f"/api/decision/funnel/context/?backtest_id={sample_attribution_report.backtest_id}"
        )
        partial_response = authenticated_client.get(
            f"/api/decision/context/step6/?backtest_id={sample_attribution_report.backtest_id}"
        )

    assert context_response.status_code == 200
    assert context_response["Content-Type"].startswith("application/json")
    context_payload = context_response.json()
    assert context_payload["success"] is True
    assert context_payload["data"]["step3_sectors"]["rotation_signals"][0]["sector"] == "沪深300"
    assert (
        context_payload["data"]["step6_audit"]["lesson_learned"]
        == "顺周期资产需要配合更严格的仓位控制。"
    )

    assert partial_response.status_code == 200
    partial_html = partial_response.content.decode("utf-8")
    assert "阶段 6: 审批执行" in partial_html
    assert "自动交易系统" in partial_html
    assert "Brinson 模型归因报告" not in partial_html
