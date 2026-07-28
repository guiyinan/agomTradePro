import json
from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from apps.data_center.infrastructure.alpha_price_coverage_sync import (
    AlphaPriceCoverageSyncService,
)
from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
from apps.data_center.infrastructure.market_gateway_protocol import MarketGatewayProtocol
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

    class EmptyGateway(MarketGatewayProtocol):
        def provider_name(self) -> str:
            return "empty"

        def supports(self, capability):
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            return []

    class TencentTestGateway(MarketGatewayProtocol):
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


def test_alpha_price_sync_rejects_reversed_range_before_backfill(mocker):
    backfill = mocker.Mock()
    service = AlphaPriceCoverageSyncService(
        backfill_service=backfill,
        gateways=[mocker.Mock(spec=MarketGatewayProtocol)],
        price_repo=mocker.Mock(),
    )

    with pytest.raises(ValueError, match="alpha_price_date_range_invalid"):
        service.sync_codes(
            codes=["000001.SZ"],
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 14),
        )

    backfill.backfill_codes.assert_not_called()


@pytest.mark.django_db
def test_alpha_price_sync_fails_over_redacts_error_and_filters_invalid_bars(
    mocker,
    caplog,
):
    class FailingGateway(MarketGatewayProtocol):
        def provider_name(self) -> str:
            return "failing"

        def supports(self, capability):
            del capability
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            del asset_code, start_date, end_date
            raise RuntimeError("postgresql://admin:raw-secret@example.test/prices")

    class MixedGateway(MarketGatewayProtocol):
        def provider_name(self) -> str:
            return "mixed"

        def supports(self, capability):
            del capability
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            del asset_code, start_date, end_date
            return [
                HistoricalPriceBar(
                    asset_code="000001.SZ",
                    trade_date=date(2026, 4, 14),
                    open=10.0,
                    high=11.0,
                    low=9.5,
                    close=10.5,
                    volume=1000,
                    amount=10500.0,
                    source="tencent",
                ),
                HistoricalPriceBar(
                    asset_code="600000.SH",
                    trade_date=date(2026, 4, 14),
                    open=10.0,
                    high=11.0,
                    low=9.5,
                    close=10.5,
                    source="tencent",
                ),
                HistoricalPriceBar(
                    asset_code="000001.SZ",
                    trade_date=date(2026, 4, 13),
                    open=10.0,
                    high=11.0,
                    low=9.5,
                    close=10.5,
                    source="tencent",
                ),
                HistoricalPriceBar(
                    asset_code="000001.SZ",
                    trade_date=date(2026, 4, 14),
                    open=12.0,
                    high=11.0,
                    low=9.5,
                    close=10.5,
                    source="akshare",
                ),
            ]

    price_repo = mocker.Mock()
    price_repo.bulk_upsert.side_effect = lambda bars: len(bars)
    backfill = mocker.Mock()
    backfill.backfill_codes.return_value = SimpleNamespace(unresolved_codes=[])
    service = AlphaPriceCoverageSyncService(
        backfill_service=backfill,
        gateways=[FailingGateway(), MixedGateway()],
        price_repo=price_repo,
    )
    mocker.patch.object(service, "_replace_managed_bars")

    report = service.sync_codes(
        codes=["000001.SZ"],
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 14),
    )

    assert report.synced_codes == ["000001.SZ"]
    assert report.total_bars == 1
    stored_bars = price_repo.bulk_upsert.call_args.args[0]
    assert len(stored_bars) == 1
    assert stored_bars[0].asset_code == "000001.SZ"
    assert stored_bars[0].source == "tencent"
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


@pytest.mark.django_db
def test_alpha_price_sync_rolls_back_old_bar_deletion_when_write_fails(mocker):
    class ValidGateway(MarketGatewayProtocol):
        def provider_name(self) -> str:
            return "valid"

        def supports(self, capability):
            del capability
            return True

        def get_historical_prices(self, asset_code: str, start_date: str, end_date: str):
            del asset_code, start_date, end_date
            return [
                HistoricalPriceBar(
                    asset_code="000001.SZ",
                    trade_date=date(2026, 4, 14),
                    open=10.0,
                    high=11.0,
                    low=9.5,
                    close=10.5,
                    source="tencent",
                )
            ]

    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 4, 14),
        open=9.0,
        high=10.0,
        low=8.5,
        close=9.5,
        volume=100,
        amount=950.0,
        source="akshare",
    )
    backfill = mocker.Mock()
    backfill.backfill_codes.return_value = SimpleNamespace(unresolved_codes=[])
    price_repo = mocker.Mock()
    price_repo.bulk_upsert.side_effect = RuntimeError("write_failed")
    service = AlphaPriceCoverageSyncService(
        backfill_service=backfill,
        gateways=[ValidGateway()],
        price_repo=price_repo,
    )

    with pytest.raises(RuntimeError, match="write_failed"):
        service.sync_codes(
            codes=["000001.SZ"],
            start_date=date(2026, 4, 14),
            end_date=date(2026, 4, 14),
        )

    assert PriceBarModel.objects.filter(
        asset_code="000001.SZ",
        bar_date=date(2026, 4, 14),
        source="akshare",
    ).exists()


def test_sync_alpha_price_coverage_command_rejects_reversed_dates(mocker):
    service = mocker.patch(
        "apps.data_center.management.commands.sync_alpha_price_coverage."
        "AlphaPriceCoverageSyncService"
    )

    with pytest.raises(CommandError, match="alpha_price_date_range_invalid"):
        call_command(
            "sync_alpha_price_coverage",
            start_date="2026-04-20",
            end_date="2026-04-14",
        )

    service.assert_not_called()


def test_sync_alpha_price_coverage_command_emits_json_report(mocker):
    report = SimpleNamespace(
        to_dict=lambda: {
            "requested_count": 1,
            "synced_count": 1,
            "start_date": "2026-04-14",
            "end_date": "2026-04-14",
        }
    )
    service_cls = mocker.patch(
        "apps.data_center.management.commands.sync_alpha_price_coverage."
        "AlphaPriceCoverageSyncService"
    )
    service_cls.return_value.sync_from_alpha_cache.return_value = report
    stdout = StringIO()

    call_command(
        "sync_alpha_price_coverage",
        start_date="2026-04-14",
        end_date="2026-04-14",
        extra_code=["000001.SZ"],
        no_remote=True,
        stdout=stdout,
    )

    service_cls.return_value.sync_from_alpha_cache.assert_called_once_with(
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 14),
        include_remote=False,
        extra_codes=["000001.SZ"],
    )
    payload = json.loads(stdout.getvalue().splitlines()[-1])
    assert payload["requested_count"] == 1
    assert payload["synced_count"] == 1
