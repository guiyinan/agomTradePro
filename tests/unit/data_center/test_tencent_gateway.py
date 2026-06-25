from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests

from apps.data_center.infrastructure.gateways.tencent_gateway import TencentGateway


def test_tencent_gateway_parses_stock_history_rows():
    response = MagicMock()
    response.json.return_value = {
        "code": 0,
        "data": {
            "sz000001": {
                "qfqday": [
                    ["2026-04-01", "11.09", "11.15", "11.23", "11.08", "918925.000"],
                ]
            }
        },
    }

    with patch(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        return_value=response,
    ) as mocked_get:
        bars = TencentGateway().get_historical_prices("000001.SZ", "20260401", "20260419")

    mocked_get.assert_called_once()
    assert len(bars) == 1
    assert bars[0].asset_code == "000001.SZ"
    assert bars[0].trade_date == date(2026, 4, 1)
    assert bars[0].close == 11.15
    assert bars[0].source == "tencent"


def test_tencent_gateway_maps_index_code_to_sh_prefix():
    response = MagicMock()
    response.json.return_value = {
        "code": 0,
        "data": {
            "sh000300": {
                "day": [
                    ["2026-04-01", "4461.74", "4491.95", "4496.41", "4447.14", "209293092.000"],
                ]
            }
        },
    }

    with patch(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        return_value=response,
    ) as mocked_get:
        bars = TencentGateway().get_historical_prices("000300.SH", "20260401", "20260419")

    _, kwargs = mocked_get.call_args
    assert kwargs["params"]["param"].startswith("sh000300,day,2026-04-01,2026-04-19")
    assert len(bars) == 1
    assert bars[0].asset_code == "000300.SH"


def test_tencent_gateway_parses_realtime_quote_rows():
    response = MagicMock()
    response.text = (
        'v_sh510300="1~沪深300ETF华泰柏瑞~510300~5.048~4.967~4.973~'
        "26406087~6844264~19561823~5.048~296~5.047~1484~5.046~338~"
        "5.045~4822~5.044~4531~5.049~215~5.050~13282~5.051~324~"
        "5.052~4375~5.053~8116~~20260625161456~0.081~1.63~5.055~"
        '4.966~5.048/26406087/13252886361~26406087~1325289~12.73";'
        'v_sh000300="1~沪深300~000300~5020.10~4943.02~4950.98~'
        "346664289~0~0~0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~"
        "0.00~0~0.00~0~0.00~0~0.00~0~0.00~0~~20260625161406~"
        "77.08~1.56~5032.00~4944.88~5020.10/346664289/1110040892256~"
        '346664289~111004089~1.04";'
    )

    with patch(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        return_value=response,
    ) as mocked_get:
        quotes = TencentGateway().get_quote_snapshots(["510300.SH", "000300.SH"])

    mocked_get.assert_called_once()
    assert [quote.stock_code for quote in quotes] == ["510300.SH", "000300.SH"]
    assert quotes[0].price == Decimal("5.048")
    assert quotes[0].amount == Decimal("13252886361")
    assert quotes[1].price == Decimal("5020.10")
    assert quotes[1].pre_close == Decimal("4943.02")
    assert quotes[1].source == "tencent"


def test_tencent_gateway_skips_follow_up_requests_after_permission_denied():
    blocked_error = requests.ConnectionError("[WinError 10013] socket access forbidden")

    with patch(
        "apps.data_center.infrastructure.gateways.tencent_gateway.requests.get",
        side_effect=blocked_error,
    ) as mocked_get:
        gateway = TencentGateway()
        first = gateway.get_historical_prices("000001.SZ", "20260401", "20260419")
        second = gateway.get_historical_prices("399001.SZ", "20260401", "20260419")

    assert first == []
    assert second == []
    mocked_get.assert_called_once()
