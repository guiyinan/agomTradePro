import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.factor.infrastructure.models import FactorPortfolioConfigModel


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
