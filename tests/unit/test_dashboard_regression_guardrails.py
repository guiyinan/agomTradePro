from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.account.domain.entities import AccountProfile, RiskTolerance
from apps.account.infrastructure.models import PortfolioDailySnapshotModel
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository
from shared.infrastructure.crypto import FieldEncryptionService


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
def test_dashboard_homepage_uses_unified_decision_workflow_entry():
    user = get_user_model().objects.create_user(
        username="dashboard_workflow_user",
        password="x",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "环境评估 → 方向选择 → 板块偏好 → 推优筛选 → 交易计划 → 审批执行" in content
    assert "环境 → 候选 → 决策 → 执行 → 回写" not in content
    assert 'href="/decision/workspace/"' in content
    assert "决策工作台" in content
    assert "进入新 Workflow" in content


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


@pytest.mark.django_db
def test_dashboard_ai_insights_falls_back_when_encrypted_key_is_invalid(settings, monkeypatch):
    settings.AGOMTRADEPRO_ENCRYPTION_KEY = FieldEncryptionService.generate_key()
    wrong_service = FieldEncryptionService(FieldEncryptionService.generate_key())

    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    AIProviderConfig.objects.create(
        name="dashboard-invalid-encrypted-provider",
        provider_type="deepseek",
        is_active=True,
        priority=1,
        base_url="https://example.test/v1",
        api_key="",
        api_key_encrypted=wrong_service.encrypt("sk-invalid-for-current-key"),
        default_model="deepseek-chat",
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

    def fail_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called when API key is unusable")

    monkeypatch.setattr("requests.post", fail_post)

    insights = use_case._generate_ai_insights(
        current_regime="Recovery",
        snapshot=DummySnapshot(),
        match_analysis=DummyMatch(),
        active_signals=[],
        policy_level="P0",
    )

    assert insights


@pytest.mark.django_db
def test_dashboard_performance_chart_uses_portfolio_snapshot_history():
    user = get_user_model().objects.create_user(
        username="performance_history_user",
        password="x",
    )
    account_repo = AccountRepository()
    portfolio_id = account_repo.get_or_create_default_portfolio(user.id)

    today = date.today()
    PortfolioDailySnapshotModel.objects.bulk_create(
        [
            PortfolioDailySnapshotModel(
                portfolio_id=portfolio_id,
                snapshot_date=today - timedelta(days=2),
                total_value=Decimal("1000.00"),
                cash_balance=Decimal("300.00"),
                invested_value=Decimal("700.00"),
                position_count=2,
            ),
            PortfolioDailySnapshotModel(
                portfolio_id=portfolio_id,
                snapshot_date=today - timedelta(days=1),
                total_value=Decimal("1100.00"),
                cash_balance=Decimal("250.00"),
                invested_value=Decimal("850.00"),
                position_count=3,
            ),
            PortfolioDailySnapshotModel(
                portfolio_id=portfolio_id,
                snapshot_date=today,
                total_value=Decimal("1200.00"),
                cash_balance=Decimal("200.00"),
                invested_value=Decimal("1000.00"),
                position_count=4,
            ),
        ]
    )

    use_case = GetDashboardDataUseCase(
        account_repo=account_repo,
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    performance_data = use_case._generate_performance_chart_data(
        portfolio_id=portfolio_id,
        current_total_return_pct=20.0,
        days=30,
    )

    assert [point["date"] for point in performance_data] == [
        (today - timedelta(days=2)).isoformat(),
        (today - timedelta(days=1)).isoformat(),
        today.isoformat(),
    ]
    assert [point["portfolio_value"] for point in performance_data] == [1000.0, 1100.0, 1200.0]
    assert [point["return_pct"] for point in performance_data] == [0.0, 10.0, 20.0]
    assert performance_data[-1]["cash_balance"] == 200.0
    assert performance_data[-1]["invested_value"] == 1000.0
    assert performance_data[-1]["position_count"] == 4
