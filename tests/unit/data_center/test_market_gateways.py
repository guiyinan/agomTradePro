"""
Data Center 网关测试

使用 mock 避免实际网络调用。
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.data_center.infrastructure.market_gateway_enums import DataCapability


class TestTushareGateway:
    def test_provider_name(self):
        from apps.data_center.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        gw = TushareGateway()
        assert gw.provider_name() == "tushare"

    def test_supports_realtime_quote(self):
        from apps.data_center.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        gw = TushareGateway()
        assert gw.supports(DataCapability.REALTIME_QUOTE)
        assert gw.supports(DataCapability.TECHNICAL_FACTORS)
        assert not gw.supports(DataCapability.CAPITAL_FLOW)
        assert not gw.supports(DataCapability.STOCK_NEWS)

    @patch("apps.data_center.infrastructure.gateways.tushare_gateway.TushareGateway.get_quote_snapshots")
    def test_get_technical_snapshot_delegates(self, mock_quotes):
        from apps.data_center.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )
        from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot

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

    @patch("apps.data_center.infrastructure.gateways.tushare_gateway.TushareGateway.get_quote_snapshots")
    def test_get_technical_snapshot_empty(self, mock_quotes):
        from apps.data_center.infrastructure.gateways.tushare_gateway import (
            TushareGateway,
        )

        mock_quotes.return_value = []
        gw = TushareGateway()
        assert gw.get_technical_snapshot("000001.SZ") is None

    @patch("apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway.get_historical_prices")
    @patch("shared.infrastructure.tushare_client.create_tushare_pro_client")
    def test_history_falls_back_to_tencent_when_tushare_errors(self, mock_client_factory, mock_tencent_history):
        from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
        from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar

        mock_client_factory.side_effect = RuntimeError("timeout")
        mock_tencent_history.return_value = [
            HistoricalPriceBar(
                asset_code="000001.SZ",
                trade_date=pd.Timestamp("2026-04-01").date(),
                open=11.09,
                high=11.23,
                low=11.08,
                close=11.15,
                volume=918925,
                amount=None,
                source="tencent",
            )
        ]

        bars = TushareGateway().get_historical_prices("000001.SZ", "20260401", "20260419")

        assert len(bars) == 1
        assert bars[0].source == "tencent"
        mock_tencent_history.assert_called_once_with("000001.SZ", "20260401", "20260419")


class TestQMTGateway:
    def test_provider_name(self):
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        gw = QMTGateway()
        assert gw.provider_name() == "qmt"

    def test_supports(self):
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        gw = QMTGateway()
        assert gw.supports(DataCapability.REALTIME_QUOTE)
        assert gw.supports(DataCapability.TECHNICAL_FACTORS)
        assert gw.supports(DataCapability.HISTORICAL_PRICE)
        assert not gw.supports(DataCapability.CAPITAL_FLOW)
        assert not gw.supports(DataCapability.STOCK_NEWS)

    def test_get_quote_snapshots(self):
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        fake_xtdata = MagicMock()
        fake_xtdata.get_full_tick.return_value = {
            "000001.SZ": {
                "lastPrice": 15.5,
                "lastClose": 15.2,
                "open": 15.3,
                "high": 15.8,
                "low": 15.1,
                "volume": 1000000,
                "amount": 15500000,
                "turnoverRate": 3.2,
                "volumeRatio": 1.1,
            }
        }

        gw = QMTGateway()
        with patch.object(gw, "_load_xtdata", return_value=fake_xtdata):
            results = gw.get_quote_snapshots(["000001.SZ"])

        assert len(results) == 1
        assert results[0].stock_code == "000001.SZ"
        assert results[0].price == Decimal("15.5")
        assert results[0].pre_close == Decimal("15.2")
        assert results[0].source == "qmt"

    def test_get_historical_prices(self):
        from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway

        fake_xtdata = MagicMock()
        fake_xtdata.get_market_data_ex.return_value = {
            "000001.SZ": pd.DataFrame(
                {
                    "time": ["20260325", "20260326"],
                    "open": [15.1, 15.2],
                    "high": [15.6, 15.7],
                    "low": [14.9, 15.0],
                    "close": [15.4, 15.5],
                    "volume": [1000, 1200],
                    "amount": [15000, 18000],
                }
            )
        }

        gw = QMTGateway()
        with patch.object(gw, "_load_xtdata", return_value=fake_xtdata):
            results = gw.get_historical_prices("000001.SZ", "20260325", "20260326")

        assert len(results) == 2
        assert results[0].asset_code == "000001.SZ"
        assert results[0].close == 15.4
        assert results[0].source == "qmt"


class TestAKShareGeneralGateway:
    def test_provider_name(self):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        gw = AKShareGeneralGateway()
        assert gw.provider_name() == "akshare_general"

    def test_supports(self):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        gw = AKShareGeneralGateway()
        assert gw.supports(DataCapability.REALTIME_QUOTE)
        assert gw.supports(DataCapability.TECHNICAL_FACTORS)
        assert not gw.supports(DataCapability.CAPITAL_FLOW)

    @patch("akshare.stock_zh_a_spot_em")
    def test_get_quote_snapshots(self, mock_spot_em):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
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
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        mock_spot_em.return_value = pd.DataFrame()
        gw = AKShareGeneralGateway()
        results = gw.get_quote_snapshots(["000001.SZ"])
        assert results == []

    @patch("akshare.stock_zh_a_spot_em")
    def test_exception_returns_empty(self, mock_spot_em):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            AKShareGeneralGateway,
        )

        mock_spot_em.side_effect = Exception("network error")
        gw = AKShareGeneralGateway()
        results = gw.get_quote_snapshots(["000001.SZ"])
        assert results == []


class TestCodeConversion:
    def test_to_akshare_code(self):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            _to_akshare_code,
        )

        assert _to_akshare_code("000001.SZ") == "000001"
        assert _to_akshare_code("600000.SH") == "600000"
        assert _to_akshare_code("000001") == "000001"

    def test_to_tushare_code(self):
        from apps.data_center.infrastructure.gateways.akshare_general_gateway import (
            _to_tushare_code,
        )

        assert _to_tushare_code("000001") == "000001.SZ"
        assert _to_tushare_code("600000") == "600000.SH"
        assert _to_tushare_code("300001") == "300001.SZ"
        assert _to_tushare_code("830001") == "830001.BJ"
        assert _to_tushare_code("000001.SZ") == "000001.SZ"

    def test_to_market_arg(self):
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            _to_market_arg,
        )

        assert _to_market_arg("600000.SH") == "sh"
        assert _to_market_arg("000001.SZ") == "sz"
        assert _to_market_arg("830001.BJ") == "bj"


class TestAKShareEastMoneyGateway:
    @patch("akshare.stock_individual_fund_flow")
    def test_capital_flow_uses_bj_market_for_bj_stocks(self, mock_fund_flow):
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )

        mock_fund_flow.return_value = pd.DataFrame()
        gw = AKShareEastMoneyGateway()

        gw.get_capital_flows("830001.BJ", period="5d")

        assert mock_fund_flow.call_args.kwargs["market"] == "bj"

    @patch("apps.data_center.infrastructure.gateways.tencent_gateway.TencentGateway.get_historical_prices")
    def test_history_falls_back_to_tencent_when_akshare_errors(self, mock_tencent_history):
        from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
            AKShareEastMoneyGateway,
        )
        from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar

        mock_tencent_history.return_value = [
            HistoricalPriceBar(
                asset_code="000001.SZ",
                trade_date=pd.Timestamp("2026-04-01").date(),
                open=11.09,
                high=11.23,
                low=11.08,
                close=11.15,
                volume=918925,
                amount=None,
                source="tencent",
            )
        ]

        gw = AKShareEastMoneyGateway()
        with patch.object(
            gw,
            "_fetch_with_retries",
            side_effect=RuntimeError("connection aborted"),
        ):
            bars = gw.get_historical_prices("000001.SZ", "20260401", "20260419")

        assert len(bars) == 1
        assert bars[0].source == "tencent"
        mock_tencent_history.assert_called_once_with("000001.SZ", "20260401", "20260419")



