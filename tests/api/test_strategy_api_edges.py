import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PositionManagementRuleModel,
    StrategyModel,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="strategy_user",
        password="testpass123",
        email="strategy@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_login(auth_user)
    return api_client


@pytest.mark.django_db
def test_strategy_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/strategy/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["strategies"] == "/api/strategy/strategies/"
    assert payload["endpoints"]["execution_evaluate"] == "/api/strategy/execution/evaluate/"


@pytest.mark.django_db
def test_strategy_assignments_by_portfolio_requires_portfolio_id(authenticated_client):
    response = authenticated_client.get("/api/strategy/assignments/by_portfolio/")

    assert response.status_code == 400
    assert response.json()["detail"] == "必须提供 portfolio_id 参数"


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
def test_strategy_bind_requires_required_parameters(authenticated_client):
    response = authenticated_client.post("/api/strategy/bind-strategy/", data={}, content_type="application/json")

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

    hidden_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/"
    )
    assert hidden_response.status_code == 404

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    visible_response = authenticated_client.get(
        f"/api/strategy/strategies/{strategy.id}/"
    )

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
    assert authenticated_client.get(
        f"/api/strategy/ai-configs/{other_config.id}/"
    ).status_code == 404

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    staff_response = authenticated_client.get(
        f"/api/strategy/ai-configs/{other_config.id}/"
    )
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
    assert authenticated_client.get(
        f"/api/strategy/position-rules/{other_rule.id}/"
    ).status_code == 404
    assert authenticated_client.get(
        f"/api/strategy/strategies/{other_strategy.id}/position_rule/"
    ).status_code == 404

    auth_user.is_staff = True
    auth_user.save(update_fields=["is_staff"])
    staff_response = authenticated_client.get(
        f"/api/strategy/position-rules/{other_rule.id}/"
    )
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
    assert authenticated_client.post(
        f"/api/strategy/position-rules/{other_rule.id}/evaluate/",
        {"context": context},
        format="json",
    ).status_code == 404
    assert authenticated_client.post(
        f"/api/strategy/strategies/{other_strategy.id}/evaluate_position_management/",
        {"context": context},
        format="json",
    ).status_code == 404
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
