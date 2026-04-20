from unittest.mock import MagicMock, patch


def test_akshare_gateway_treats_000001_sz_as_stock_not_index():
    from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
        AKShareEastMoneyGateway,
    )

    fake_ak = MagicMock()
    fake_ak.stock_zh_a_hist.return_value = MagicMock(empty=True)
    fake_ak.stock_zh_index_daily.return_value = MagicMock(empty=True)

    with patch(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway.get_akshare_module",
        return_value=fake_ak,
    ):
        gateway = AKShareEastMoneyGateway()
        gateway.get_historical_prices("000001.SZ", "20260401", "20260419")

    fake_ak.stock_zh_a_hist.assert_called_once()
    fake_ak.stock_zh_index_daily.assert_not_called()


def test_tushare_gateway_treats_000001_sz_as_stock_not_index():
    from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

    fake_client = MagicMock()
    fake_client.daily.return_value = MagicMock(empty=True)
    fake_client.index_daily.return_value = MagicMock(empty=True)
    fake_client.fund_daily.return_value = MagicMock(empty=True)

    with patch(
        "shared.infrastructure.tushare_client.create_tushare_pro_client",
        return_value=fake_client,
    ):
        gateway = TushareGateway()
        gateway.get_historical_prices("000001.SZ", "20260401", "20260419")

    fake_client.daily.assert_called_once()
    fake_client.index_daily.assert_not_called()
