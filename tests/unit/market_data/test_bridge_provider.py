"""
Bridge Provider 测试

测试 MarketDataBridgePriceProvider 将 QuoteSnapshot 转换为 RealtimePrice。
"""

from datetime import UTC, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from apps.market_data.application.bridge_providers import MarketDataBridgePriceProvider
from apps.market_data.domain.entities import QuoteSnapshot
from apps.market_data.domain.enums import DataCapability
from apps.market_data.infrastructure.registries.source_registry import SourceRegistry
from apps.realtime.domain.entities import AssetType


class TestMarketDataBridgePriceProvider:
    def _make_registry_with_mock(self, snapshots):
        """创建带 mock provider 的 registry"""
        mock_provider = MagicMock()
        mock_provider.provider_name.return_value = "test"
        mock_provider.supports.return_value = True
        mock_provider.get_quote_snapshots.return_value = snapshots

        registry = SourceRegistry()
        registry.register(mock_provider, priority=10)
        return registry

    def test_batch_converts_snapshots(self):
        snapshots = [
            QuoteSnapshot(
                stock_code="000001.SZ",
                price=Decimal("15.50"),
                change=Decimal("0.30"),
                change_pct=1.97,
                volume=1000000,
                source="eastmoney",
                fetched_at=datetime.now(UTC),
            ),
        ]
        registry = self._make_registry_with_mock(snapshots)
        bridge = MarketDataBridgePriceProvider(registry)

        prices = bridge.get_realtime_prices_batch(["000001.SZ"])
        assert len(prices) == 1
        assert prices[0].asset_code == "000001.SZ"
        assert prices[0].price == "15.50"
        assert prices[0].change == "0.30"
        assert prices[0].source == "market_data:eastmoney"
        assert prices[0].asset_type == AssetType.EQUITY

    def test_single_price(self):
        snapshots = [
            QuoteSnapshot(
                stock_code="600000.SH",
                price=Decimal("8.88"),
                source="eastmoney",
                fetched_at=datetime.now(UTC),
            ),
        ]
        registry = self._make_registry_with_mock(snapshots)
        bridge = MarketDataBridgePriceProvider(registry)

        price = bridge.get_realtime_price("600000.SH")
        assert price is not None
        assert price.asset_code == "600000.SH"

    def test_no_provider_returns_empty(self):
        registry = SourceRegistry()
        bridge = MarketDataBridgePriceProvider(registry)

        prices = bridge.get_realtime_prices_batch(["000001.SZ"])
        assert prices == []

    def test_is_available_true(self):
        snapshots = []
        registry = self._make_registry_with_mock(snapshots)
        bridge = MarketDataBridgePriceProvider(registry)
        assert bridge.is_available() is True

    def test_is_available_false(self):
        registry = SourceRegistry()
        bridge = MarketDataBridgePriceProvider(registry)
        assert bridge.is_available() is False

    def test_infer_asset_type_sh(self):
        assert MarketDataBridgePriceProvider._infer_asset_type("600000.SH") == AssetType.EQUITY

    def test_infer_asset_type_sz(self):
        assert MarketDataBridgePriceProvider._infer_asset_type("000001.SZ") == AssetType.EQUITY

    def test_infer_asset_type_unknown(self):
        assert MarketDataBridgePriceProvider._infer_asset_type("BTC") == AssetType.UNKNOWN
