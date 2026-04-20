from datetime import date
from unittest.mock import MagicMock, patch

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
