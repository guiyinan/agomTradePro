import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorPortfolioConfigModel,
)


def _build_authenticated_client() -> APIClient:
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username="factor_portfolio_api_tester",
        defaults={"email": "factor-portfolio@test.example"},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_factor_portfolio_config_crud_flow():
    client = _build_authenticated_client()

    create_payload = {
        "name": "测试组合配置",
        "description": "组合配置接口回归测试",
        "factor_weights": {"pe_ttm": -0.3, "roe": 0.7},
        "universe": "all_a",
        "top_n": 25,
        "rebalance_frequency": "monthly",
        "weight_method": "equal_weight",
        "max_pe": 40.5,
    }

    create_response = client.post("/api/factor/configs/", create_payload, format="json")
    assert create_response.status_code == 201
    config_id = create_response.data["id"]
    assert create_response.data["name"] == "测试组合配置"
    assert create_response.data["factor_weights"]["roe"] == 0.7

    patch_response = client.patch(
        f"/api/factor/configs/{config_id}/",
        {
            "description": "组合配置接口已更新",
            "top_n": 30,
            "factor_weights": {"pe_ttm": -0.2, "momentum_20d": 0.5},
        },
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["top_n"] == 30
    assert patch_response.data["factor_weights"]["momentum_20d"] == 0.5

    detail_response = client.get(f"/api/factor/configs/{config_id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["description"] == "组合配置接口已更新"

    delete_response = client.delete(f"/api/factor/configs/{config_id}/")
    assert delete_response.status_code == 204
    assert not FactorPortfolioConfigModel._default_manager.filter(id=config_id).exists()


@pytest.mark.django_db
def test_factor_portfolio_weight_is_managed_with_scalar_operations():
    client = _build_authenticated_client()
    FactorDefinitionModel._default_manager.create(
        code="quality_scalar_api",
        name="质量因子",
        category="quality",
        data_source="test",
        data_field="quality",
        direction="positive",
    )
    create_response = client.post(
        "/api/factor/configs/",
        {
            "name": "逐项权重配置",
            "description": "不使用原始 JSON 表单",
            "is_active": False,
        },
        format="json",
    )
    assert create_response.status_code == 201
    config_id = create_response.data["id"]
    assert create_response.data["factor_weights"] == {}

    set_response = client.patch(
        f"/api/factor/configs/{config_id}/factor-weight/",
        {"factor_code": "quality_scalar_api", "weight": 0.75},
        format="json",
    )
    assert set_response.status_code == 200
    assert set_response.data["factor_weights"] == {"quality_scalar_api": 0.75}

    unknown_response = client.patch(
        f"/api/factor/configs/{config_id}/factor-weight/",
        {"factor_code": "unknown_factor", "weight": 0.25},
        format="json",
    )
    assert unknown_response.status_code == 400

    remove_response = client.post(
        f"/api/factor/configs/{config_id}/remove-factor-weight/",
        {"factor_code": "quality_scalar_api"},
        format="json",
    )
    assert remove_response.status_code == 200
    assert remove_response.data["factor_weights"] == {}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("universe", "unknown"),
        ("rebalance_frequency", "hourly"),
        ("weight_method", "random"),
        ("top_n", 0),
        ("max_debt_ratio", 101),
        ("max_sector_weight", 0),
        ("max_single_stock_weight", 1.1),
        ("factor_weights", {"quality": 1.1}),
    ],
)
def test_factor_portfolio_config_rejects_values_outside_owner_contract(
    field,
    value,
):
    client = _build_authenticated_client()
    payload = {"name": f"非法组合-{field}"}
    payload[field] = value

    response = client.post("/api/factor/configs/", payload, format="json")

    assert response.status_code == 400
