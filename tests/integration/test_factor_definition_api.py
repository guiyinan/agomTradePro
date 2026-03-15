import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.factor.infrastructure.models import FactorDefinitionModel


def _build_authenticated_client() -> APIClient:
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username="factor_definition_api_tester",
        defaults={"email": "factor@test.example"},
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_factor_definition_crud_and_toggle_flow():
    client = _build_authenticated_client()

    create_payload = {
        "code": "test_factor_api",
        "name": "测试因子",
        "category": "value",
        "description": "用于 API 回归测试",
        "data_source": "test_source",
        "data_field": "test_field",
        "direction": "positive",
        "update_frequency": "daily",
        "is_active": True,
        "min_data_points": 12,
        "allow_missing": False,
    }

    create_response = client.post("/api/factor/definitions/", create_payload, format="json")
    assert create_response.status_code == 201
    factor_id = create_response.data["id"]
    assert create_response.data["category_display"] == "价值"
    assert create_response.data["direction_display"] == "正向"

    patch_response = client.patch(
        f"/api/factor/definitions/{factor_id}/",
        {"name": "测试因子-更新", "allow_missing": True, "min_data_points": 24},
        format="json",
    )
    assert patch_response.status_code == 200
    assert patch_response.data["name"] == "测试因子-更新"
    assert patch_response.data["allow_missing"] is True
    assert patch_response.data["min_data_points"] == 24

    toggle_response = client.post(f"/api/factor/definitions/{factor_id}/toggle-active/", {}, format="json")
    assert toggle_response.status_code == 200
    assert toggle_response.data["success"] is True
    assert toggle_response.data["is_active"] is False

    detail_response = client.get(f"/api/factor/definitions/{factor_id}/")
    assert detail_response.status_code == 200
    assert detail_response.data["is_active"] is False

    delete_response = client.delete(f"/api/factor/definitions/{factor_id}/")
    assert delete_response.status_code == 204
    assert not FactorDefinitionModel._default_manager.filter(id=factor_id).exists()
