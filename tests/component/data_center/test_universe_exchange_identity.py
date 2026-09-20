from datetime import date

import pytest

from apps.data_center.infrastructure.a_share_universe_sync import AShareUniverseSyncService
from apps.data_center.infrastructure.models import AssetMasterModel


@pytest.mark.django_db
def test_universe_sync_preserves_explicit_exchange_and_known_new_board_code():
    AssetMasterModel.objects.create(
        code="302132.SZ", name="Existing", asset_type="stock", exchange="SZSE", is_active=False
    )

    class Provider:
        def load_code_names(self):
            return [{"code": "302132", "name": "Existing"}, {"code": "302999.SZ", "name": "New"}]

    result = AShareUniverseSyncService(provider=Provider()).sync(deactivate_missing=True)
    assert result.active_count == 2
    assert AssetMasterModel.objects.filter(code="302132.SZ", is_active=True).exists()
    assert AssetMasterModel.objects.filter(code="302999.SZ", is_active=True).exists()


@pytest.mark.django_db
def test_code_name_refresh_preserves_listing_and_classification_metadata():
    asset = AssetMasterModel.objects.create(
        code="302132.SZ",
        name="Old name",
        asset_type="stock",
        exchange="SZSE",
        is_active=False,
        list_date=date(2010, 8, 27),
        sector="technology",
        industry="electronics",
        total_shares=123456,
        extra={"source_proof": "retained"},
    )

    class Provider:
        def load_code_names(self):
            return [{"code": "302132.SZ", "name": "New name"}]

    AShareUniverseSyncService(provider=Provider()).sync()
    asset.refresh_from_db()
    assert asset.name == "New name"
    assert asset.is_active
    assert asset.list_date == date(2010, 8, 27)
    assert asset.sector == "technology"
    assert asset.industry == "electronics"
    assert asset.total_shares == 123456
    assert asset.extra["source_proof"] == "retained"


@pytest.mark.parametrize("code", ["302132.XX", "SZoops", "SH6000011", "600001junk"])
def test_universe_sync_rejects_malformed_code(code):
    assert AShareUniverseSyncService._canonicalize_a_share_code(code) == ""
