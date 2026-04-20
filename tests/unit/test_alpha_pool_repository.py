from datetime import date
from decimal import Decimal

import pytest

from apps.alpha.infrastructure.repositories import AlphaPoolDataRepository
from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel
from apps.equity.infrastructure.models import ValuationModel


@pytest.mark.django_db
def test_alpha_pool_repository_strict_valuation_uses_latest_valuation_intersection():
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="600519.SH",
        name="贵州茅台",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    ValuationModel.objects.create(
        stock_code="600519.SH",
        trade_date=date(2026, 4, 18),
        total_mv=Decimal("1000000000"),
        circ_mv=Decimal("800000000"),
        source_provider="test",
        is_valid=True,
    )

    codes = AlphaPoolDataRepository().resolve_instrument_codes(
        market="CN",
        trade_date=date(2026, 4, 20),
        pool_mode="strict_valuation",
    )

    assert codes == ["600519.SH"]


@pytest.mark.django_db
def test_alpha_pool_repository_market_mode_uses_asset_master():
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="600519.SH",
        name="贵州茅台",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )

    codes = AlphaPoolDataRepository().resolve_instrument_codes(
        market="CN",
        trade_date=date(2026, 4, 20),
        pool_mode="market",
    )

    assert codes == ["000001.SZ", "600519.SH"]


@pytest.mark.django_db
def test_alpha_pool_repository_price_covered_mode_uses_price_bar_coverage():
    AssetMasterModel.objects.create(
        code="000001.SZ",
        name="平安银行",
        asset_type="stock",
        exchange="SZSE",
        is_active=True,
    )
    AssetMasterModel.objects.create(
        code="600519.SH",
        name="贵州茅台",
        asset_type="stock",
        exchange="SSE",
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 4, 18),
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume=1000,
        amount=10500,
        source="tushare",
    )

    codes = AlphaPoolDataRepository().resolve_instrument_codes(
        market="CN",
        trade_date=date(2026, 4, 20),
        pool_mode="price_covered",
    )

    assert codes == ["000001.SZ"]
