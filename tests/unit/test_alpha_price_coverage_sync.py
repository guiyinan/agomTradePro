from datetime import date

import pytest

from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from apps.data_center.infrastructure.alpha_price_coverage_sync import (
    AlphaPriceCoverageSyncService,
)
from apps.data_center.infrastructure.gateway_protocols import GatewayProviderProtocol
from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel


@pytest.mark.django_db
def test_alpha_price_coverage_sync_service_collects_codes_from_cache():
    AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 14),
        provider_source="qlib",
        asof_date=date(2026, 4, 14),
        scores=[
            {"code": "000001.SZ", "score": 0.8},
            {"code": "(Timestamp('2026-04-14 00:00:00'), 'SH600048')", "score": 0.7},
        ],
        status="available",
        metrics_snapshot={},
    )

    codes = AlphaPriceCoverageSyncService().collect_codes_from_alpha_cache(
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 14),
    )

    assert codes == ["000001.SZ", "600048.SH"]


@pytest.mark.django_db
def test_alpha_price_coverage_sync_service_backfills_assets_and_prices(mocker):
    AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 14),
        provider_source="qlib",
        asof_date=date(2026, 4, 14),
        scores=[{"code": "000001.SZ", "score": 0.8}],
        status="available",
        metrics_snapshot={},
    )

    mocker.patch(
        "apps.data_center.infrastructure.asset_master_backfill.AssetMasterBackfillService._fetch_remote_name",
        return_value="平安银行",
    )
    class EmptyGateway(GatewayProviderProtocol):
        def provider_name(self) -> str:
            return "empty"

        def supports(self, capability):
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            return []

    class TencentTestGateway(GatewayProviderProtocol):
        def provider_name(self) -> str:
            return "tencent"

        def supports(self, capability):
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            return [
                HistoricalPriceBar(
                    asset_code="000001.SZ",
                    trade_date=date(2026, 4, 14),
                    open=10.0,
                    high=11.0,
                    low=9.9,
                    close=10.5,
                    volume=1000,
                    amount=10500.0,
                    source="tencent",
                )
            ]

    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 4, 14),
        open=3900.0,
        high=3900.0,
        low=3900.0,
        close=3900.0,
        volume=1,
        amount=3900.0,
        source="akshare",
    )

    report = AlphaPriceCoverageSyncService(
        gateways=[EmptyGateway(), TencentTestGateway()],
    ).sync_from_alpha_cache(
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 19),
    )

    assert report.synced_codes == ["000001.SZ"]
    assert report.total_bars == 1
    assert AssetMasterModel.objects.filter(code="000001.SZ", name="平安银行").exists()
    bars = list(PriceBarModel.objects.filter(asset_code="000001.SZ", bar_date=date(2026, 4, 14)))
    assert len(bars) == 1
    assert bars[0].source == "tencent"
    assert float(bars[0].close) == 10.5
