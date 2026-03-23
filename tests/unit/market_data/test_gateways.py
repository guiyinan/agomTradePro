"""
Gateway 测试

使用 mock 避免实际网络调用。
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.market_data.domain.enums import DataCapability


class TestTushareGateway:
    def test_provider_name(self):
        from apps.market_data.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        gw = TushareGateway()
        assert gw.provider_name() == "tushare"

    def test_supports_realtime_quote(self):
        from apps.market_data.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        gw = TushareGateway()
        assert gw.supports(DataCapability.REALTIME_QUOTE)
        assert gw.supports(DataCapability.TECHNICAL_FACTORS)
        assert not gw.supports(DataCapability.CAPITAL_FLOW)
        assert not gw.supports(DataCapability.STOCK_NEWS)

    @patch("apps.market_data.infrastructure.gateways.tushare_gateway.TushareGateway.get_quote_snapshots")
    def test_get_technical_snapshot_delegates(self, mock_quotes):
        from apps.market_data.domain.entities import QuoteSnapshot
        from apps.market_data.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        mock_quotes.return_value = [
            QuoteSnapshot(
                stock_code="000001.SZ",
                price=Decimal("15.50"),
                turnover_rate=3.2,
                source="tushare",
            )
        ]
        gw = TushareGateway()
        tech = gw.get_technical_snapshot("000001.SZ")
        assert tech is not None
        assert tech.stock_code == "000001.SZ"
        assert tech.close == Decimal("15.50")
        assert tech.source == "tushare"

    @patch("apps.market_data.infrastructure.gateways.tushare_gateway.TushareGateway.get_quote_snapshots")
    def test_get_technical_snapshot_empty(self, mock_quotes):
        from apps.market_data.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        mock_quotes.return_value = []
        gw = TushareGateway()
        assert gw.get_technical_snapshot("000001.SZ") is None


class TestAKShareGeneralGateway:
    def test_provider_name(self):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        gw = AKShareGeneralGateway()
        assert gw.provider_name() == "akshare_general"

    def test_supports(self):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        gw = AKShareGeneralGateway()
        assert gw.supports(DataCapability.REALTIME_QUOTE)
        assert gw.supports(DataCapability.TECHNICAL_FACTORS)
        assert not gw.supports(DataCapability.CAPITAL_FLOW)

    @patch("akshare.stock_zh_a_spot_em")
    def test_get_quote_snapshots(self, mock_spot_em):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        df = pd.DataFrame({
            "代码": ["000001", "600000"],
            "最新价": [15.50, 8.20],
            "涨跌额": [0.30, -0.10],
            "涨跌幅": [1.97, -1.20],
            "成交量": [1000000, 500000],
            "成交额": [15500000.0, 4100000.0],
            "换手率": [3.2, 1.5],
            "量比": [1.1, 0.9],
            "最高": [15.80, 8.30],
            "最低": [15.20, 8.10],
            "今开": [15.30, 8.25],
            "昨收": [15.20, 8.30],
        })
        mock_spot_em.return_value = df

        gw = AKShareGeneralGateway()
        results = gw.get_quote_snapshots(["000001.SZ", "600000.SH"])

        assert len(results) == 2
        assert results[0].stock_code == "000001.SZ"
        assert results[0].price == Decimal("15.5")
        assert results[0].source == "akshare_general"

    @patch("akshare.stock_zh_a_spot_em")
    def test_empty_dataframe(self, mock_spot_em):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        mock_spot_em.return_value = pd.DataFrame()
        gw = AKShareGeneralGateway()
        results = gw.get_quote_snapshots(["000001.SZ"])
        assert results == []

    @patch("akshare.stock_zh_a_spot_em")
    def test_exception_returns_empty(self, mock_spot_em):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        mock_spot_em.side_effect = Exception("network error")
        gw = AKShareGeneralGateway()
        results = gw.get_quote_snapshots(["000001.SZ"])
        assert results == []


class TestCodeConversion:
    def test_to_akshare_code(self):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            _to_akshare_code,
        )

        assert _to_akshare_code("000001.SZ") == "000001"
        assert _to_akshare_code("600000.SH") == "600000"
        assert _to_akshare_code("000001") == "000001"

    def test_to_tushare_code(self):
        from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
            _to_tushare_code,
        )

        assert _to_tushare_code("000001") == "000001.SZ"
        assert _to_tushare_code("600000") == "600000.SH"
        assert _to_tushare_code("300001") == "300001.SZ"
        assert _to_tushare_code("830001") == "830001.BJ"
        assert _to_tushare_code("000001.SZ") == "000001.SZ"

    def test_to_market_arg(self):
        from apps.market_data.infrastructure.gateways.akshare_eastmoney_gateway import (
            _to_market_arg,
        )

        assert _to_market_arg("600000.SH") == "sh"
        assert _to_market_arg("000001.SZ") == "sz"
        assert _to_market_arg("830001.BJ") == "bj"


class TestAKShareEastMoneyGateway:
    @patch("akshare.stock_individual_fund_flow")
    def test_capital_flow_uses_bj_market_for_bj_stocks(self, mock_fund_flow):
        from apps.market_data.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        mock_fund_flow.return_value = pd.DataFrame()
        gw = AKShareEastMoneyGateway()

        gw.get_capital_flows("830001.BJ", period="5d")

        assert mock_fund_flow.call_args.kwargs["market"] == "bj"


class TestRegistryFactory:
    @patch("apps.market_data.application.registry_factory.settings")
    def test_all_providers_registered(self, mock_settings):
        from apps.market_data.application.registry_factory import (
            _build_registry,
        )

        mock_settings.MARKET_DATA_EASTMONEY_ENABLED = True
        mock_settings.MARKET_DATA_EASTMONEY_INTERVAL_SEC = 0.5
        mock_settings.MARKET_DATA_EASTMONEY_PRIORITY = 10
        mock_settings.MARKET_DATA_AKSHARE_GENERAL_ENABLED = True
        mock_settings.MARKET_DATA_AKSHARE_GENERAL_PRIORITY = 20
        mock_settings.MARKET_DATA_TUSHARE_ENABLED = True
        mock_settings.MARKET_DATA_TUSHARE_PRIORITY = 30

        registry = _build_registry()
        providers = registry.get_providers(DataCapability.REALTIME_QUOTE)
        names = [p.provider_name() for p in providers]

        assert "eastmoney" in names
        assert "akshare_general" in names
        assert "tushare" in names
        # eastmoney should be first (priority 10)
        assert names[0] == "eastmoney"

    @patch("apps.market_data.application.registry_factory.settings")
    def test_disabled_providers_not_registered(self, mock_settings):
        from apps.market_data.application.registry_factory import (
            _build_registry,
        )

        mock_settings.MARKET_DATA_EASTMONEY_ENABLED = False
        mock_settings.MARKET_DATA_AKSHARE_GENERAL_ENABLED = False
        mock_settings.MARKET_DATA_TUSHARE_ENABLED = True
        mock_settings.MARKET_DATA_TUSHARE_PRIORITY = 30

        registry = _build_registry()
        providers = registry.get_providers(DataCapability.REALTIME_QUOTE)
        names = [p.provider_name() for p in providers]

        assert "eastmoney" not in names
        assert "akshare_general" not in names
        assert "tushare" in names
