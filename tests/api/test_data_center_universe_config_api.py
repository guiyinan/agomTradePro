import pytest

from apps.data_center.infrastructure.models import AssetMasterModel


@pytest.mark.django_db
def test_production_coverage_universe_config_api_round_trips(admin_client):
    response = admin_client.get("/api/data-center/production-coverage/universe/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["universe_id"] == "active_a_share"
    assert payload["exchanges"] == ["SSE", "SZSE", "BSE"]

    update_response = admin_client.put(
        "/api/data-center/production-coverage/universe/",
        data={
            "universe_id": "szse_chinext",
            "asset_type": "stock",
            "exchanges": ["SZSE"],
            "include_inactive": False,
            "min_active_asset_count": 1,
            "min_star_market_count": 0,
            "min_chinext_count": 1,
            "min_bse_count": 0,
            "description": "test universe",
        },
        content_type="application/json",
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["universe_id"] == "szse_chinext"
    assert updated["exchanges"] == ["SZSE"]
    assert updated["min_chinext_count"] == 1


@pytest.mark.django_db
def test_production_coverage_summary_uses_saved_universe_config(admin_client):
    AssetMasterModel.objects.create(
        code="300750.SZ",
        name="宁德时代",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="600000.SH",
        name="浦发银行",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    admin_client.patch(
        "/api/data-center/production-coverage/universe/",
        data={
            "universe_id": "szse_only",
            "exchanges": ["SZSE"],
            "min_active_asset_count": 1,
            "min_star_market_count": 0,
            "min_chinext_count": 1,
            "min_bse_count": 0,
        },
        content_type="application/json",
    )

    response = admin_client.get("/api/data-center/production-coverage/summary/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["universe"] == "szse_only"
    assert payload["asset_count"] == 1
    assert payload["universe_quality"]["exchange_counts"] == {"SZSE": 1}


@pytest.mark.django_db
def test_data_center_universe_page_requires_staff(client, django_user_model):
    user = django_user_model.objects.create_user(username="plain", password="pw")
    client.force_login(user)

    response = client.get("/data-center/universe/")

    assert response.status_code == 302


@pytest.mark.django_db
def test_data_center_universe_page_renders_for_staff(client, django_user_model):
    user = django_user_model.objects.create_user(
        username="staff",
        password="pw",
        is_staff=True,
    )
    client.force_login(user)

    response = client.get("/data-center/universe/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "生产覆盖 Universe 配置" in content
    assert "/api/data-center/production-coverage/universe/" in content
    assert "/api/data-center/production-coverage/summary/" in content
