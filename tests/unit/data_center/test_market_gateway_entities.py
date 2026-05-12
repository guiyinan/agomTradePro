"""
Data Center 网关层实体测试
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.data_center.infrastructure.market_gateway_entities import (
    CapitalFlowSnapshot,
    ProviderStatus,
    QuoteSnapshot,
    StockNewsItem,
    TechnicalSnapshot,
)


class TestQuoteSnapshot:
    def test_create_valid(self):
        snap = QuoteSnapshot(
            stock_code="000001.SZ",
            price=Decimal("15.50"),
            change=Decimal("0.30"),
            change_pct=1.97,
            volume=1000000,
            source="eastmoney",
        )
        assert snap.stock_code == "000001.SZ"
        assert snap.price == Decimal("15.50")
        assert snap.change == Decimal("0.30")

    def test_empty_stock_code_raises(self):
        with pytest.raises(ValueError, match="stock_code"):
            QuoteSnapshot(stock_code="", price=Decimal("10.0"))

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="price"):
            QuoteSnapshot(stock_code="000001.SZ", price=Decimal("-1.0"))

    def test_to_dict(self):
        snap = QuoteSnapshot(
            stock_code="600000.SH",
            price=Decimal("8.88"),
            source="test",
        )
        d = snap.to_dict()
        assert d["stock_code"] == "600000.SH"
        assert d["price"] == "8.88"
        assert d["source"] == "test"

    def test_optional_fields_default_none(self):
        snap = QuoteSnapshot(stock_code="000001.SZ", price=Decimal("10.0"))
        assert snap.change is None
        assert snap.volume is None
        assert snap.turnover_rate is None
        assert snap.volume_ratio is None


class TestCapitalFlowSnapshot:
    def test_create_valid(self):
        flow = CapitalFlowSnapshot(
            stock_code="000001.SZ",
            trade_date=date(2026, 3, 1),
            main_net_inflow=50000000.0,
            main_net_ratio=5.5,
            super_large_net_inflow=30000000.0,
            large_net_inflow=20000000.0,
            source="eastmoney",
        )
        assert flow.stock_code == "000001.SZ"
        assert flow.main_net_inflow == 50000000.0

    def test_empty_stock_code_raises(self):
        with pytest.raises(ValueError):
            CapitalFlowSnapshot(
                stock_code="",
                trade_date=date.today(),
                main_net_inflow=0.0,
                main_net_ratio=0.0,
            )

    def test_to_dict_keys(self):
        flow = CapitalFlowSnapshot(
            stock_code="000001.SZ",
            trade_date=date(2026, 3, 1),
            main_net_inflow=100.0,
            main_net_ratio=1.0,
        )
        d = flow.to_dict()
        assert "stock_code" in d
        assert "trade_date" in d
        assert "main_net_inflow" in d


class TestStockNewsItem:
    def test_create_valid(self):
        item = StockNewsItem(
            stock_code="000001.SZ",
            news_id="abc123",
            title="Test News",
            content="Test content",
            source="eastmoney",
        )
        assert item.stock_code == "000001.SZ"
        assert item.title == "Test News"

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="title"):
            StockNewsItem(
                stock_code="000001.SZ",
                news_id="abc123",
                title="",
            )

    def test_empty_news_id_raises(self):
        with pytest.raises(ValueError, match="news_id"):
            StockNewsItem(
                stock_code="000001.SZ",
                news_id="",
                title="Test",
            )

    def test_to_text_with_content(self):
        item = StockNewsItem(
            stock_code="000001.SZ",
            news_id="abc",
            title="Title",
            content="Body",
        )
        assert item.to_text() == "Title\nBody"

    def test_to_text_without_content(self):
        item = StockNewsItem(
            stock_code="000001.SZ",
            news_id="abc",
            title="Title Only",
        )
        assert item.to_text() == "Title Only"


class TestTechnicalSnapshot:
    def test_create_valid(self):
        snap = TechnicalSnapshot(
            stock_code="000001.SZ",
            trade_date=date(2026, 3, 1),
            close=Decimal("15.50"),
            kdj_k=80.0,
            kdj_d=75.0,
            kdj_j=90.0,
            boll_upper=16.5,
            boll_mid=15.0,
            boll_lower=13.5,
            source="eastmoney",
        )
        assert snap.kdj_k == 80.0
        assert snap.boll_upper == 16.5

    def test_empty_stock_code_raises(self):
        with pytest.raises(ValueError):
            TechnicalSnapshot(
                stock_code="",
                trade_date=date.today(),
                close=Decimal("10.0"),
            )


class TestProviderStatus:
    def test_to_dict(self):
        status = ProviderStatus(
            provider_name="eastmoney",
            capability="realtime_quote",
            is_healthy=True,
            consecutive_failures=0,
        )
        d = status.to_dict()
        assert d["provider_name"] == "eastmoney"
        assert d["is_healthy"] is True

