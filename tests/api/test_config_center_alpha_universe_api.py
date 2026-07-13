from uuid import UUID

import pytest

from apps.config_center.infrastructure.models import (
    AlphaUniverseConfigModel,
    QlibTrainingProfileModel,
    QlibTrainingRunModel,
)
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


@pytest.mark.django_db
def test_alpha_universe_catalog_returns_named_records(admin_client):
    AlphaUniverseConfigModel.objects.create(
        universe_id="manual_core",
        name="核心观察池",
        source_type=AlphaUniverseConfigModel.SOURCE_MANUAL,
        stock_codes=["600000.SH"],
        is_active=True,
    )

    response = admin_client.get(
        "/api/system/config-center/qlib/alpha-universes/",
        {"include_inactive": "1"},
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"][0]["universe_id"] == "manual_core"


@pytest.mark.django_db
def test_qlib_training_profile_catalog_returns_serialized_profiles(admin_client):
    QlibTrainingProfileModel.objects.create(
        profile_key="lgb_v1",
        name="LGB V1",
        model_name="lgb_csi300",
        model_type="LGBModel",
        universe="csi300",
    )

    response = admin_client.get(
        "/api/system/config-center/qlib/training-profiles/"
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"][0]["profile_key"] == "lgb_v1"
    assert payload["data"][0]["model_name"] == "lgb_csi300"


@pytest.mark.django_db
def test_qlib_training_run_list_and_detail_return_serialized_runs(admin_client):
    run = QlibTrainingRunModel.objects.create(
        status=QlibTrainingRunModel.STATUS_SUCCEEDED,
        model_name="lgb_csi300",
        model_type="LGBModel",
        resolved_train_config={"universe": "csi300"},
        result_metrics={"ic": 0.08},
    )

    list_response = admin_client.get(
        "/api/system/config-center/qlib/training-runs/",
        {"limit": 10},
    )
    detail_response = admin_client.get(
        f"/api/system/config-center/qlib/training-runs/{run.run_id}/"
    )

    assert list_response.status_code == 200
    assert list_response["Content-Type"].startswith("application/json")
    list_payload = list_response.json()
    assert list_payload["success"] is True
    assert UUID(list_payload["data"][0]["run_id"]) == run.run_id
    assert list_payload["data"][0]["status"] == QlibTrainingRunModel.STATUS_SUCCEEDED

    assert detail_response.status_code == 200
    assert detail_response["Content-Type"].startswith("application/json")
    detail_payload = detail_response.json()
    assert detail_payload["success"] is True
    assert UUID(detail_payload["data"]["run_id"]) == run.run_id
    assert detail_payload["data"]["result_metrics"] == {"ic": 0.08}
