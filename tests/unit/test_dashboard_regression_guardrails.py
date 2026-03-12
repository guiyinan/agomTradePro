from datetime import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.account.domain.entities import AccountProfile, RiskTolerance
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository


@pytest.mark.django_db
def test_dashboard_page_does_not_log_known_regression_warnings(caplog):
    user = get_user_model().objects.create_user(
        username="dashboard_guardrail_user",
        password="x",
    )
    client = Client()
    client.force_login(user)

    with caplog.at_level("WARNING"):
        response = client.get("/dashboard/")

    assert response.status_code == 200
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "cannot import name 'AIProvider'" not in messages
    assert "unexpected keyword argument 'positions'" not in messages
    assert "get_risk_tolerance_display" not in messages


@pytest.mark.django_db
def test_dashboard_use_case_generates_allocation_advice_for_domain_profile():
    user = get_user_model().objects.create_user(
        username="allocation_guardrail_user",
        password="x",
    )
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    profile = AccountProfile(
        user_id=user.id,
        display_name=user.username,
        initial_capital=Decimal("1000000.00"),
        risk_tolerance=RiskTolerance.MODERATE,
        created_at=datetime.now(),
    )

    advice = use_case._generate_allocation_advice(
        current_regime="Recovery",
        policy_level="P0",
        profile=profile,
        total_assets=1000000.0,
        positions=[],
    )

    assert advice is not None
    assert advice["risk_profile_display"] == "稳健型"
    assert advice["target_allocation"]["equity"] > 0


@pytest.mark.django_db
def test_dashboard_ai_insights_uses_ai_provider_config_model(monkeypatch):
    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    AIProviderConfig.objects.create(
        name="dashboard-test-provider",
        provider_type="openai",
        is_active=True,
        priority=1,
        base_url="https://example.test/v1",
        api_key="test-key",
        default_model="gpt-4o-mini",
    )

    class DummySnapshot:
        total_value = Decimal("1000000")
        total_return_pct = 5.0
        positions = []

        @staticmethod
        def get_invested_ratio():
            return 0.4

    class DummyMatch:
        total_match_score = 80.0
        hostile_assets = []

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [
                    {"message": {"content": "1. 保持均衡配置\n2. 关注政策变化"}}
                ]
            }

    def fake_post(url, headers, json, timeout):
        assert url == "https://example.test/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-key"
        assert json["model"] == "gpt-4o-mini"
        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)

    insights = use_case._generate_ai_insights(
        current_regime="Recovery",
        snapshot=DummySnapshot(),
        match_analysis=DummyMatch(),
        active_signals=[],
        policy_level="P0",
    )

    assert insights
    assert "保持均衡配置" in insights[0]
