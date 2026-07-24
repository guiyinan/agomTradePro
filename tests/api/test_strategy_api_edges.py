from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
)
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    StrategyExecutionLogModel,
    StrategyModel,
)


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_login(auth_user)
    return api_client


@pytest.mark.django_db
def test_strategy_assignments_by_portfolio_requires_portfolio_id(authenticated_client):
    response = authenticated_client.get("/api/strategy/assignments/by_portfolio/")

    assert response.status_code == 400
    assert response.json()["detail"] == "必须提供 portfolio_id 参数"


@pytest.mark.django_db
def test_strategy_assignments_are_owner_scoped_and_reject_cross_owner_links(
    authenticated_client,
    auth_user,
):
    other_user = get_user_model().objects.create_user(
        username="strategy_assignment_other",
        password="testpass123",
    )
    own_strategy = StrategyModel.objects.create(
        name="Own Assignment Strategy",
        strategy_type="rule_based",
        version=1,
        created_by=auth_user.account_profile,
    )
    other_strategy = StrategyModel.objects.create(
        name="Other Assignment Strategy",
        strategy_type="rule_based",
        version=1,
        created_by=other_user.account_profile,
    )
    own_account = SimulatedAccountModel.objects.create(
        user=auth_user,
        account_name="Own Assignment Account",
        initial_capital=100_000,
        current_cash=100_000,
        total_value=100_000,
    )
    other_account = SimulatedAccountModel.objects.create(
        user=other_user,
        account_name="Other Assignment Account",
        initial_capital=100_000,
        current_cash=100_000,
        total_value=100_000,
    )
    own_assignment = PortfolioStrategyAssignmentModel.objects.create(
        portfolio=own_account,
        strategy=own_strategy,
        assigned_by=auth_user.account_profile,
    )
    other_assignment = PortfolioStrategyAssignmentModel.objects.create(
        portfolio=other_account,
        strategy=other_strategy,
        assigned_by=other_user.account_profile,
    )

    list_response = authenticated_client.get("/api/strategy/assignments/")
    rows = list_response.json().get("results", list_response.json())
    hidden_portfolio = authenticated_client.get(
        f"/api/strategy/assignments/by_portfolio/?portfolio_id={other_account.id}"
    )
    cross_portfolio = authenticated_client.post(
        "/api/strategy/assignments/",
        {"portfolio": other_account.id, "strategy": own_strategy.id},
        format="json",
    )
    cross_strategy = authenticated_client.patch(
        f"/api/strategy/assignments/{own_assignment.id}/",
        {"strategy": other_strategy.id},
        format="json",
    )

    assert list_response.status_code == 200
    assert {row["id"] for row in rows} == {own_assignment.id}
    assert hidden_portfolio.status_code == 200
    assert hidden_portfolio.json() == []
    assert (
        authenticated_client.get(f"/api/strategy/assignments/{other_assignment.id}/").status_code
        == 404
    )
    assert cross_portfolio.status_code == 403
    assert cross_strategy.status_code == 403
    assert PortfolioStrategyAssignmentModel.objects.count() == 2


@pytest.mark.django_db
def test_strategy_execution_evaluate_rejects_invalid_json(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/execution/evaluate/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "无效 JSON"


@pytest.mark.django_db
def test_strategy_execution_evaluate_rejects_nonfinite_numbers(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/execution/evaluate/",
        data='{"symbol":"000001.SZ","side":"buy","account_equity":NaN}',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "account_equity" in response.json()["errors"]


@pytest.mark.django_db
def test_strategy_script_preview_rejects_non_object_and_oversized_payloads(
    authenticated_client,
):
    non_object = authenticated_client.post(
        "/api/strategy/test-script/",
        data="[]",
        content_type="application/json",
    )
    oversized = authenticated_client.post(
        "/api/strategy/test-script/",
        data={"script_code": "x" * 50_001},
        format="json",
    )

    assert non_object.status_code == 400
    assert non_object.json()["error"] == "JSON 请求体必须是对象"
    assert oversized.status_code == 400
    assert "不能超过 50000 个字符" in oversized.json()["error"]


@pytest.mark.django_db
def test_strategy_bind_requires_required_parameters(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/bind-strategy/", data={}, content_type="application/json"
    )

    assert response.status_code == 400
    assert response.json()["error"] == "缺少必要参数"


@pytest.mark.django_db
def test_strategy_unbind_rejects_invalid_json(authenticated_client):
    response = authenticated_client.post(
        "/api/strategy/unbind-strategy/",
        data="{bad json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "无效 JSON"


def _strategy_table_counts() -> dict[str, int]:
    return {
        model._meta.label_lower: model._default_manager.count()
        for model in django_apps.get_app_config("strategy").get_models()
    }


@pytest.mark.django_db
def test_strategy_catalog_api_is_read_only(authenticated_client, auth_user):
    strategy = StrategyModel.objects.create(
        name="Macro Guard",
        description="Read-only contract fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    other_user = get_user_model().objects.create_user(
        username="strategy_other",
        password="testpass123",
    )
    other_strategy = StrategyModel.objects.create(
        name="Other User Strategy",
        description="Must remain outside the owner scope",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=other_user.account_profile,
    )
    before = _strategy_table_counts()

    response = authenticated_client.get(
        "/api/strategy/strategies/",
        {"strategy_type": "rule_based", "is_active": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    rows = payload.get("results", payload)
    assert any(row["id"] == strategy.id for row in rows)
    assert all(row["id"] != other_strategy.id for row in rows)
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_strategy_detail_api_is_read_only(authenticated_client, auth_user):
    strategy = StrategyModel.objects.create(
        name="Quality Rotation",
        description="Detail contract fixture",
        strategy_type="hybrid",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    before = _strategy_table_counts()

    response = authenticated_client.get(f"/api/strategy/strategies/{strategy.id}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == strategy.id
    assert payload["rules_count"] == 0
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_strategy_detail_hides_other_owner_but_staff_can_read(
    authenticated_client,
    auth_user,
):
    other_user = get_user_model().objects.create_user(
        username="strategy_staff_target",
        password="testpass123",
    )
    strategy = StrategyModel.objects.create(
        name="Staff Visible Strategy",
        description="Owner scope fixture",
        strategy_type="ai_driven",
        version=1,
        is_active=True,
        created_by=other_user.account_profile,
    )
    before = _strategy_table_counts()

    hidden_response = authenticated_client.get(f"/api/strategy/strategies/{strategy.id}/")
    assert hidden_response.status_code == 404

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    visible_response = authenticated_client.get(f"/api/strategy/strategies/{strategy.id}/")

    assert visible_response.status_code == 200
    assert visible_response.json()["id"] == strategy.id
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_ai_strategy_config_api_is_owner_scoped_read_only_with_staff_override(
    authenticated_client,
    auth_user,
):
    own_strategy = StrategyModel.objects.create(
        name="Owner AI Strategy",
        description="AI config owner fixture",
        strategy_type="ai_driven",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    own_config = AIStrategyConfigModel.objects.create(
        strategy=own_strategy,
        approval_mode="conditional",
    )
    other_user = get_user_model().objects.create_user(
        username="strategy_ai_other",
        password="testpass123",
    )
    other_strategy = StrategyModel.objects.create(
        name="Other AI Strategy",
        description="AI config isolation fixture",
        strategy_type="ai_driven",
        version=1,
        is_active=True,
        created_by=other_user.account_profile,
    )
    other_config = AIStrategyConfigModel.objects.create(
        strategy=other_strategy,
        approval_mode="auto",
    )
    before = _strategy_table_counts()

    list_response = authenticated_client.get("/api/strategy/ai-configs/")
    rows = list_response.json().get("results", list_response.json())
    assert list_response.status_code == 200
    assert {row["id"] for row in rows} == {own_config.id}
    assert (
        authenticated_client.get(f"/api/strategy/ai-configs/{other_config.id}/").status_code == 404
    )

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    staff_response = authenticated_client.get(f"/api/strategy/ai-configs/{other_config.id}/")
    assert staff_response.status_code == 200
    assert staff_response.json()["id"] == other_config.id
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_position_rule_api_is_owner_scoped_read_only_with_staff_override(
    authenticated_client,
    auth_user,
):
    own_strategy = StrategyModel.objects.create(
        name="Owner Rule Strategy",
        description="Position rule owner fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    own_rule = PositionManagementRuleModel.objects.create(
        strategy=own_strategy,
        name="Owner ATR Guard",
        buy_price_expr="current_price",
        sell_price_expr="current_price",
        stop_loss_expr="current_price * 0.95",
        take_profit_expr="current_price * 1.1",
        position_size_expr="100",
    )
    other_user = get_user_model().objects.create_user(
        username="strategy_rule_other",
        password="testpass123",
    )
    other_strategy = StrategyModel.objects.create(
        name="Other Rule Strategy",
        description="Position rule isolation fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=other_user.account_profile,
    )
    other_rule = PositionManagementRuleModel.objects.create(
        strategy=other_strategy,
        name="Other ATR Guard",
        buy_price_expr="current_price",
        sell_price_expr="current_price",
        stop_loss_expr="current_price * 0.95",
        take_profit_expr="current_price * 1.1",
        position_size_expr="100",
    )
    before = _strategy_table_counts()

    list_response = authenticated_client.get("/api/strategy/position-rules/")
    rows = list_response.json().get("results", list_response.json())
    assert list_response.status_code == 200
    assert {row["id"] for row in rows} == {own_rule.id}
    assert (
        authenticated_client.get(f"/api/strategy/position-rules/{other_rule.id}/").status_code
        == 404
    )
    assert (
        authenticated_client.get(
            f"/api/strategy/strategies/{other_strategy.id}/position_rule/"
        ).status_code
        == 404
    )

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    staff_response = authenticated_client.get(f"/api/strategy/position-rules/{other_rule.id}/")
    assert staff_response.status_code == 200
    assert staff_response.json()["id"] == other_rule.id
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_position_rule_calculations_are_owner_scoped_and_side_effect_free(
    authenticated_client,
    auth_user,
):
    own_strategy = StrategyModel.objects.create(
        name="Owner Position Calculator",
        description="Pure calculation fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    own_rule = PositionManagementRuleModel.objects.create(
        strategy=own_strategy,
        name="Owner Calculation Rule",
        buy_price_expr="current_price",
        sell_price_expr="current_price * 1.2",
        stop_loss_expr="buy_price * 0.9",
        take_profit_expr="buy_price * 1.2",
        position_size_expr="account_equity * 0.01",
    )
    other_user = get_user_model().objects.create_user(
        username="strategy_compute_other",
        password="testpass123",
    )
    other_strategy = StrategyModel.objects.create(
        name="Other Position Calculator",
        description="Cross-owner calculation fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=other_user.account_profile,
    )
    other_rule = PositionManagementRuleModel.objects.create(
        strategy=other_strategy,
        name="Other Calculation Rule",
        buy_price_expr="current_price",
        sell_price_expr="current_price * 1.2",
        stop_loss_expr="buy_price * 0.9",
        take_profit_expr="buy_price * 1.2",
        position_size_expr="account_equity * 0.01",
    )
    context = {"current_price": 10.0, "account_equity": 100000.0}
    before = _strategy_table_counts()

    rule_response = authenticated_client.post(
        f"/api/strategy/position-rules/{own_rule.id}/evaluate/",
        {"context": context},
        format="json",
    )
    strategy_response = authenticated_client.post(
        f"/api/strategy/strategies/{own_strategy.id}/evaluate_position_management/",
        {"context": context},
        format="json",
    )

    assert rule_response.status_code == 200
    assert strategy_response.status_code == 200
    assert rule_response.json()["position_size"] == 1000.0
    assert strategy_response.json() == rule_response.json()
    assert (
        authenticated_client.post(
            f"/api/strategy/position-rules/{other_rule.id}/evaluate/",
            {"context": context},
            format="json",
        ).status_code
        == 404
    )
    assert (
        authenticated_client.post(
            f"/api/strategy/strategies/{other_strategy.id}/evaluate_position_management/",
            {"context": context},
            format="json",
        ).status_code
        == 404
    )
    assert _strategy_table_counts() == before

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    staff_response = authenticated_client.post(
        f"/api/strategy/position-rules/{other_rule.id}/evaluate/",
        {"context": context},
        format="json",
    )

    assert staff_response.status_code == 200
    assert staff_response.json()["position_size"] == 1000.0
    assert _strategy_table_counts() == before


@pytest.mark.django_db
def test_strategy_execute_action_uses_canonical_application_boundary(
    authenticated_client,
    auth_user,
):
    strategy = StrategyModel.objects.create(
        name="Canonical Execute",
        description="Execution API fixture",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        created_by=auth_user.account_profile,
    )
    expected = {
        "success": True,
        "strategy_id": strategy.id,
        "executed_portfolios": 1,
        "signals_count": 2,
    }
    with patch(
        "apps.strategy.interface.sdk_contract_actions.execute_strategy_for_assignments",
        return_value=expected,
    ) as execute:
        response = authenticated_client.post(
            f"/api/strategy/strategies/{strategy.id}/execute/",
            {"portfolio_id": 7, "as_of_date": timezone.localdate().isoformat()},
            format="json",
        )
        historical_response = authenticated_client.post(
            f"/api/strategy/strategies/{strategy.id}/execute/",
            {"portfolio_id": 7, "as_of_date": "2000-01-01"},
            format="json",
        )

    assert response.status_code == 200
    assert response.json() == expected
    execute.assert_called_once()
    assert execute.call_args.kwargs["strategy_id"] == strategy.id
    assert execute.call_args.kwargs["portfolio_id"] == 7
    assert historical_response.status_code == 400
    assert "Historical strategy execution" in str(historical_response.json())


@pytest.mark.django_db
def test_strategy_sdk_reads_are_owner_scoped_strict_and_side_effect_free(
    authenticated_client,
    auth_user,
):
    strategy = StrategyModel.objects.create(
        name="Persisted SDK Reads",
        description="Read contract fixture",
        strategy_type="rule_based",
        created_by=auth_user.account_profile,
    )
    account = SimulatedAccountModel.objects.create(
        user=auth_user,
        account_name="Strategy Read Portfolio",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("99000.00"),
        current_market_value=Decimal("1000.00"),
        total_value=Decimal("100000.00"),
    )
    PortfolioStrategyAssignmentModel.objects.create(
        portfolio=account,
        strategy=strategy,
        assigned_by=auth_user.account_profile,
        is_active=True,
    )
    StrategyExecutionLogModel.objects.create(
        strategy=strategy,
        portfolio=account,
        execution_duration_ms=25,
        execution_result={"status": "completed"},
        signals_generated=[
            {
                "asset_code": "000001.SZ",
                "action": "buy",
                "status": "generated",
            }
        ],
        is_success=True,
    )
    PositionModel.objects.create(
        account=account,
        asset_code="000001.SZ",
        asset_name="平安银行",
        asset_type="equity",
        quantity=Decimal("100.000000"),
        available_quantity=Decimal("100.000000"),
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("1000.00"),
        current_price=Decimal("10.5000"),
        market_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        first_buy_date=date(2026, 7, 10),
    )
    other_user = get_user_model().objects.create_user(
        username="strategy_other_user",
        password="testpass123",
    )
    other_strategy = StrategyModel.objects.create(
        name="Other User Strategy",
        description="Must remain hidden",
        strategy_type="rule_based",
        created_by=other_user.account_profile,
    )
    strategy_before = _strategy_table_counts()
    simulated_before = {
        "accounts": list(SimulatedAccountModel._default_manager.order_by("pk").values()),
        "positions": list(PositionModel._default_manager.order_by("pk").values()),
    }

    performance_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/performance/"
    )
    signals_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/signals/",
        {"status": "generated", "limit": 10},
    )
    positions_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/positions/"
    )
    unknown_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/performance/",
        {"limit": 10},
    )
    hidden_response = authenticated_client.get(
        f"/api/strategy/strategies/{other_strategy.id}/performance/"
    )

    assert performance_response.status_code == 200
    assert performance_response.json()["execution_count"] == 1
    assert performance_response.json()["signals_generated"] == 1
    assert signals_response.status_code == 200
    assert signals_response.json()["count"] == 1
    assert signals_response.json()["results"][0]["asset_code"] == "000001.SZ"
    assert positions_response.status_code == 200
    assert positions_response.json()["count"] == 1
    assert positions_response.json()["results"][0]["portfolio_id"] == account.id
    assert unknown_response.status_code == 400
    assert "Unknown parameters: limit" in str(unknown_response.json())
    assert hidden_response.status_code == 404
    assert _strategy_table_counts() == strategy_before
    simulated_after = {
        "accounts": list(SimulatedAccountModel._default_manager.order_by("pk").values()),
        "positions": list(PositionModel._default_manager.order_by("pk").values()),
    }
    assert simulated_after == simulated_before
