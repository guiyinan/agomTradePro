from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.account.domain.entities import AccountProfile, RiskTolerance
from apps.account.infrastructure.models import PortfolioDailySnapshotModel
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.dashboard.application.queries import RegimeSummaryQuery
from apps.dashboard.application.use_cases import GetDashboardDataUseCase
from apps.data_center.application.macro_fact_governance import MacroFactGovernanceNormalizer
from apps.data_center.application.macro_publication import PublishMacroBatchUseCase
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.entities import IndicatorCatalog, IndicatorUnitRule, MacroFact
from apps.data_center.infrastructure.catalog_repositories import (
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DatasetContractRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.macro_fact_storage_repository import MacroFactRepository
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.decision_rhythm.infrastructure.models import (
    DecisionRequestModel,
    DecisionResponseModel,
    UnifiedRecommendationModel,
)
from apps.regime.infrastructure.repositories import DjangoRegimeRepository
from apps.signal.infrastructure.repositories import DjangoSignalRepository
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from shared.infrastructure.crypto import FieldEncryptionService


def _response_text(response) -> str:
    return response.content.decode(response.charset or "utf-8")


def _assert_dashboard_html_contract(response) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in (
        "AgomTradePro - 投资指挥中心",
        "投资指挥中心",
        "环境评估 → 方向选择 → 板块偏好 → 推优筛选 → 交易计划 → 审批执行",
        "进入新 Workflow",
        "Alpha 推荐资产",
        "待执行队列",
    ):
        assert fragment in content

    assert "Internal Server Error" not in content
    assert "Traceback" not in content
    return content


@pytest.mark.django_db
def test_dashboard_page_does_not_log_known_regression_warnings(caplog):
    user = get_user_model().objects.create_user(
        username="dashboard_guardrail_user",
        password="x",
    )
    client = Client()
    client.force_login(user)

    with override_settings(ROOT_URLCONF="tests.component.dashboard_compat_urls"):
        with caplog.at_level("WARNING"):
            response = client.get("/__test__/legacy-dashboard/")

    _assert_dashboard_html_contract(response)
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

    with override_settings(ROOT_URLCONF="tests.component.dashboard_compat_urls"):
        response = client.get("/__test__/legacy-dashboard/")

    content = _assert_dashboard_html_contract(response)
    assert "环境评估 → 方向选择 → 板块偏好 → 推优筛选 → 交易计划 → 审批执行" in content
    assert "环境 → 候选 → 决策 → 执行 → 回写" not in content
    assert 'href="/decision/workspace/"' in content
    assert "决策工作台" in content
    assert "进入新 Workflow" in content


@pytest.mark.django_db
def test_dashboard_entry_redirects_to_tui_command_center():
    user = get_user_model().objects.create_user(
        username="dashboard_redirect_user",
        password="x",
    )
    client = Client()
    client.force_login(user)

    response = client.get("/dashboard/", follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/tui/?screen=command-center.overview"


def test_regime_summary_uses_snapshot_repository_contract(monkeypatch):
    """Dashboard reads the current regime through the unified current resolver."""
    current = SimpleNamespace(
        dominant_regime="Recovery",
        observed_at=date(2026, 7, 22),
        confidence=0.88,
        growth_momentum_z=0.4,
        inflation_momentum_z=-0.2,
        distribution={"Recovery": 1.0},
        warnings=[],
        must_not_use_for_decision=False,
    )
    monkeypatch.setattr(
        "apps.dashboard.application.queries.resolve_current_regime",
        lambda: current,
    )
    monkeypatch.setattr(RegimeSummaryQuery, "_get_latest_macro_value", lambda *_: None)

    result = RegimeSummaryQuery().execute()

    assert result.current_regime == "Recovery"
    assert result.regime_date == date(2026, 7, 22)
    assert result.regime_confidence == 0.88


@pytest.mark.django_db
def test_dashboard_renders_pending_queue_from_real_decision_request_models(monkeypatch):
    monkeypatch.setattr(
        "apps.asset_analysis.application.asset_name_service.resolve_asset_names",
        lambda _codes: {},
    )
    user = get_user_model().objects.create_user(
        username="dashboard_pending_queue_user",
        password="x",
    )
    client = Client()
    client.force_login(user)

    owned_account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="Dashboard pending owner account",
        account_type="simulated",
        initial_capital="100000.00",
        current_cash="100000.00",
        total_value="100000.00",
    )
    owned_recommendation = UnifiedRecommendationModel.objects.create(
        recommendation_id=f"urec_dashboard_owner_{uuid4().hex[:12]}",
        account_id=str(owned_account.pk),
        security_code="000003.SH",
        side="BUY",
    )
    request = DecisionRequestModel.objects.create(
        request_id="req_dashboard_guardrail_001",
        asset_code="000003.SH",
        asset_class="a_share",
        direction="BUY",
        priority="HIGH",
        reason="dashboard pending queue guardrail",
        execution_target="SIMULATED",
        execution_status="PENDING",
        unified_recommendation=owned_recommendation,
    )
    DecisionResponseModel.objects.create(
        request=request,
        approved=True,
        approval_reason="guardrail approved",
    )

    foreign_user = get_user_model().objects.create_user(
        username="dashboard_pending_foreign_user",
        password="x",
    )
    foreign_account = SimulatedAccountModel.objects.create(
        user=foreign_user,
        account_name="Dashboard pending foreign account",
        account_type="simulated",
        initial_capital="100000.00",
        current_cash="100000.00",
        total_value="100000.00",
    )
    foreign_recommendation = UnifiedRecommendationModel.objects.create(
        recommendation_id=f"urec_dashboard_foreign_{uuid4().hex[:12]}",
        account_id=str(foreign_account.pk),
        security_code="600000.SH",
        side="BUY",
    )
    foreign_request = DecisionRequestModel.objects.create(
        request_id=f"req_dashboard_foreign_{uuid4().hex[:12]}",
        asset_code="600000.SH",
        asset_class="a_share",
        direction="BUY",
        priority="HIGH",
        reason="foreign owner pending request",
        execution_target="SIMULATED",
        execution_status="PENDING",
        unified_recommendation=foreign_recommendation,
    )
    DecisionResponseModel.objects.create(
        request=foreign_request,
        approved=True,
        approval_reason="foreign request approved",
    )
    orphan_request = DecisionRequestModel.objects.create(
        request_id=f"req_dashboard_orphan_{uuid4().hex[:12]}",
        asset_code="600001.SH",
        asset_class="a_share",
        direction="BUY",
        priority="HIGH",
        reason="ownerless pending request",
        execution_target="SIMULATED",
        execution_status="PENDING",
    )
    DecisionResponseModel.objects.create(
        request=orphan_request,
        approved=True,
        approval_reason="ownerless request approved",
    )

    with override_settings(ROOT_URLCONF="tests.component.dashboard_compat_urls"):
        response = client.get("/__test__/legacy-dashboard/")

    content = _assert_dashboard_html_contract(response)
    assert "待执行队列 (1)" in content
    assert "000003.SH" in content
    assert "600000.SH" not in content
    assert "600001.SH" not in content
    assert (
        "/decision/workspace/?source=dashboard-pending&amp;security_code=000003.SH&amp;step=5"
        in content
    )


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
def test_dashboard_use_case_ignores_pending_policy_for_allocation_advice():
    user = get_user_model().objects.create_user(
        username="allocation_pending_policy_user",
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
        policy_level="PX",
        profile=profile,
        total_assets=1000000.0,
        positions=[],
    )

    assert advice is not None
    assert advice["target_allocation"]["equity"] > 0


@pytest.mark.django_db
def test_dashboard_ai_insights_uses_ai_provider_config_model(settings, monkeypatch):
    settings.DASHBOARD_SYNC_AI_INSIGHTS_ENABLED = True

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
            return {"choices": [{"message": {"content": "1. 保持均衡配置\n2. 关注政策变化"}}]}

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
    settings.DASHBOARD_SYNC_AI_INSIGHTS_ENABLED = True
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
def test_dashboard_ai_insights_skips_invalid_provider_when_later_provider_is_usable(
    settings,
    monkeypatch,
):
    settings.DASHBOARD_SYNC_AI_INSIGHTS_ENABLED = True
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
        base_url="https://invalid.example.test/v1",
        api_key="",
        api_key_encrypted=wrong_service.encrypt("sk-invalid-for-current-key"),
        default_model="deepseek-chat",
    )
    AIProviderConfig.objects.create(
        name="dashboard-valid-provider",
        provider_type="openai",
        is_active=True,
        priority=2,
        base_url="https://valid.example.test/v1",
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
            return {"choices": [{"message": {"content": "1. 保持均衡配置\n2. 维持纪律执行"}}]}

    def fake_post(url, headers, json, timeout):
        assert url == "https://valid.example.test/v1/chat/completions"
        assert headers["Authorization"] == "Bearer test-key"
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


@pytest.mark.django_db
def test_portfolio_snapshot_handles_zero_monthly_baseline_without_500():
    user = get_user_model().objects.create_user(
        username="dashboard_zero_month_baseline_user",
        password="x",
    )
    account_repo = AccountRepository()
    portfolio_id = account_repo.get_or_create_default_portfolio(user.id)

    PortfolioDailySnapshotModel.objects.create(
        portfolio_id=portfolio_id,
        snapshot_date=date.today() - timedelta(days=30),
        total_value=Decimal("0.00"),
        cash_balance=Decimal("0.00"),
        invested_value=Decimal("0.00"),
        position_count=0,
    )

    snapshot = PortfolioRepository().get_portfolio_snapshot(portfolio_id)

    assert snapshot is not None
    assert snapshot.total_return_pct == 0.0


@pytest.mark.django_db
def test_dashboard_macro_values_read_from_data_center():
    today = date.today()
    catalog_repo = IndicatorCatalogRepository()
    unit_rule_repo = IndicatorUnitRuleRepository()
    macro_specs = (
        ("CN_PMI", "采购经理指数", "指数", "growth", "index", "index_level", 50.6),
        (
            "CN_CPI_NATIONAL_YOY",
            "全国CPI同比",
            "%",
            "inflation",
            "rate",
            "yoy_rate",
            1.4,
        ),
    )
    for code, name, unit, category, dimension, semantics, _value in macro_specs:
        catalog_repo.upsert(
            IndicatorCatalog(
                code=code,
                name_cn=name,
                default_unit=unit,
                default_period_type="M",
                category=category,
                is_active=True,
                extra={
                    "series_semantics": semantics,
                    "regime_input_policy": "direct_allowed",
                },
            )
        )
        unit_rule_repo.upsert(
            IndicatorUnitRule(
                id=None,
                indicator_code=code,
                source_type="akshare",
                dimension_key=dimension,
                original_unit=unit,
                storage_unit=unit,
                display_unit=unit,
                multiplier_to_storage=1.0,
                is_active=True,
                priority=1,
            )
        )

    raw_facts = [
        MacroFact(
            indicator_code=code,
            reporting_period=today,
            value=value,
            unit=unit,
            source="akshare",
            published_at=today,
        )
        for code, _name, unit, _category, _dimension, _semantics, value in macro_specs
    ]
    facts = MacroFactGovernanceNormalizer(catalog_repo, unit_rule_repo).normalize_many(
        raw_facts,
        source_type="akshare",
        provider_name="akshare",
    )
    assert [(fact.value, fact.unit, fact.published_at) for fact in facts] == [
        (50.6, "指数", today),
        (1.4, "%", today),
    ]
    fact_repo = MacroFactRepository()
    assert fact_repo.bulk_upsert(facts) == 2

    dataset_key = DatasetKey("macro.fact", "1.0", "1.0")
    DatasetContractRepository().save(
        DatasetContract(
            key=dataset_key,
            owner="dashboard-test",
            frequency="monthly",
            decision_critical=True,
            fields=(
                DatasetFieldContract(
                    name="observed_at",
                    value_type="datetime",
                    unit=None,
                    nullable=False,
                    zero_allowed=False,
                ),
            ),
            freshness_seconds=90 * 24 * 60 * 60,
        )
    )
    policy_repo = PublicationPolicyRepository()
    policy_repo.save(
        PublicationPolicy(
            dataset=dataset_key,
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "observed_at", "published_at", "payload_hash"),
            retention_days=3650,
        )
    )
    publication_repo = CanonicalPublicationRepository()
    publisher = PublishMacroBatchUseCase(
        fact_repository=fact_repo,
        publication_repository=publication_repo,
        policy_repository=policy_repo,
    )
    publication_time = datetime.now(UTC)
    for fact in facts:
        publication = publisher.execute(
            [fact],
            provider_name=fact.source,
            publication_key=fact.indicator_code,
            published_at=publication_time,
        )
        assert publication is not None
        members = publication_repo.list_members(publication.publication_id)
        assert len(members) == 1
        member = members[0]
        assert member.source_published_at is not None
        assert member.observed_at == member.source_published_at
        assert publication.published_at is not None
        assert member.source_published_at <= publication.published_at
        assert len(member.fact_content_hash) == 64

        # The macro batch writer does not advance the activation-owned pointer.
        CanonicalPublicationPointerModel.objects.update_or_create(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            defaults={
                "publication_id": publication.publication_id,
                "publication_hash": publication.publication_hash,
                "activation_id": f"fixture:{publication.publication_id}",
            },
        )

    use_case = GetDashboardDataUseCase(
        account_repo=AccountRepository(),
        portfolio_repo=PortfolioRepository(),
        position_repo=PositionRepository(),
        regime_repo=DjangoRegimeRepository(),
        signal_repo=DjangoSignalRepository(),
    )

    pmi_value, cpi_value = use_case._get_latest_macro_values()
    assert pmi_value == pytest.approx(50.6)
    assert cpi_value == pytest.approx(1.4)

    # A published revision without its activation-owned pointer is not current.
    CanonicalPublicationPointerModel.objects.filter(
        dataset_key="macro.fact",
        publication_key__in=("CN_PMI", "CN_CPI_NATIONAL_YOY"),
    ).delete()
    assert use_case._get_latest_macro_values() == (None, None)
