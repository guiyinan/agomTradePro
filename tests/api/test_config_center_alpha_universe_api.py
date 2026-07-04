import pytest

from apps.config_center.infrastructure.models import AlphaUniverseConfigModel
from apps.data_center.infrastructure.models import AssetMasterModel


@pytest.mark.django_db
def test_alpha_universe_api_saves_manual_codes(admin_client):
    response = admin_client.post(
        "/api/system/config-center/qlib/alpha-universes/",
        data={
            "universe_id": "manual_star",
            "name": "手工科创池",
            "source_type": "manual",
            "stock_codes": ["688001", "688001.SH", "300750"],
            "filters": {},
            "is_active": True,
            "description": "manual test",
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["universe_id"] == "manual_star"
    assert payload["stock_codes"] == ["688001.SH", "300750.SZ"]
    assert payload["member_count"] == 2


@pytest.mark.django_db
def test_alpha_universe_members_resolve_data_center_boards(admin_client):
    AssetMasterModel.objects.bulk_create(
        [
            AssetMasterModel(
                code="688001.SH",
                name="科创测试",
                asset_type="stock",
                exchange="SSE",
                is_active=True,
            ),
            AssetMasterModel(
                code="300750.SZ",
                name="创业测试",
                asset_type="stock",
                exchange="SZSE",
                is_active=True,
            ),
            AssetMasterModel(
                code="830799.BJ",
                name="北交测试",
                asset_type="stock",
                exchange="BSE",
                is_active=True,
            ),
            AssetMasterModel(
                code="600000.SH",
                name="主板测试",
                asset_type="stock",
                exchange="SSE",
                is_active=True,
            ),
        ]
    )
    AlphaUniverseConfigModel.objects.create(
        universe_id="growth_boards",
        name="成长板块",
        source_type=AlphaUniverseConfigModel.SOURCE_DATA_CENTER_FILTER,
        filters={
            "asset_type": "stock",
            "exchanges": ["SSE", "SZSE", "BSE"],
            "boards": ["star_market", "chinext", "bse"],
            "include_inactive": False,
        },
        is_active=True,
    )

    response = admin_client.get(
        "/api/system/config-center/qlib/alpha-universes/growth_boards/members/"
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["member_count"] == 3
    assert payload["members"] == ["300750.SZ", "688001.SH", "830799.BJ"]

