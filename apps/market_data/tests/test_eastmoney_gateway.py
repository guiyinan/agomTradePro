from decimal import Decimal

from apps.market_data.infrastructure.gateways.akshare_eastmoney_gateway import (
    AKShareEastMoneyGateway,
)


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_eastmoney_gateway_parses_single_stock_quote(mocker):
    gateway = AKShareEastMoneyGateway(request_interval_sec=0)
    session = mocker.Mock()
    session.get.return_value = _DummyResponse(
        {
            "data": {
                "f43": 1094,
                "f44": 1096,
                "f45": 1085,
                "f46": 1087,
                "f47": 754906,
                "f48": 824171953.5,
                "f50": 107,
                "f60": 1089,
                "f168": 39,
                "f169": 5,
                "f170": 46,
            }
        }
    )

    snapshot = gateway._fetch_quote_snapshot(session, "000001.SZ")

    assert snapshot is not None
    assert snapshot.stock_code == "000001.SZ"
    assert snapshot.price == Decimal("10.94")
    assert snapshot.high == Decimal("10.96")
    assert snapshot.low == Decimal("10.85")
    assert snapshot.open == Decimal("10.87")
    assert snapshot.pre_close == Decimal("10.89")
    assert snapshot.change == Decimal("0.05")
    assert snapshot.change_pct == 0.46
    assert snapshot.turnover_rate == 0.39
    assert snapshot.volume_ratio == 1.07
    assert snapshot.volume == 754906
