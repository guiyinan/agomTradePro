from io import StringIO

import pytest
from django.core.management import call_command

from apps.data_center.infrastructure.asset_master_backfill import AssetMasterBackfillService
from apps.data_center.infrastructure.models import AssetAliasModel, AssetMasterModel
from apps.fund.infrastructure.models import FundHoldingModel
from apps.rotation.infrastructure.models import AssetClassModel


@pytest.mark.django_db
def test_asset_master_backfill_service_uses_legacy_holding_and_creates_alias():
    FundHoldingModel.objects.create(
        fund_code="000001",
        report_date="2026-03-31",
        stock_code="601899.SH",
        stock_name="紫金矿业",
    )

    report = AssetMasterBackfillService().backfill_codes(["601899.SH"])

    assert report.unresolved_codes == []
    assert AssetMasterModel.objects.filter(code="601899.SH", name="紫金矿业").exists()
    assert AssetAliasModel.objects.filter(
        provider_name="legacy",
        alias_code="601899",
        asset__code="601899.SH",
    ).exists()


@pytest.mark.django_db
def test_asset_master_backfill_service_supports_remote_name_recovery(mocker):
    mocker.patch(
        "apps.data_center.infrastructure.asset_master_backfill.AssetMasterBackfillService._fetch_remote_name",
        return_value="中信特钢",
    )

    report = AssetMasterBackfillService().backfill_codes(["000708.SZ"], include_remote=True)

    assert report.unresolved_codes == []
    assert AssetMasterModel.objects.filter(code="000708.SZ", name="中信特钢").exists()
    assert AssetAliasModel.objects.filter(
        provider_name="legacy",
        alias_code="000708",
        asset__code="000708.SZ",
    ).exists()


@pytest.mark.django_db
def test_asset_master_backfill_service_keeps_shanghai_etf_suffix():
    AssetClassModel.objects.create(
        code="510300",
        name="沪深300ETF",
        category="equity",
        currency="CNY",
        is_active=True,
    )

    report = AssetMasterBackfillService().backfill_codes(["510300"])

    assert report.unresolved_codes == []
    assert AssetMasterModel.objects.filter(code="510300.SH", name="沪深300ETF").exists()
    assert AssetAliasModel.objects.filter(
        provider_name="legacy",
        alias_code="510300",
        asset__code="510300.SH",
    ).exists()


@pytest.mark.django_db
def test_backfill_asset_master_command_backfills_requested_codes():
    FundHoldingModel.objects.create(
        fund_code="000001",
        report_date="2026-03-31",
        stock_code="601899.SH",
        stock_name="紫金矿业",
    )
    stdout = StringIO()

    call_command("backfill_asset_master", "--codes", "601899.SH", stdout=stdout)

    assert "Asset master backfill completed" in stdout.getvalue()
    assert AssetMasterModel.objects.filter(code="601899.SH", name="紫金矿业").exists()
