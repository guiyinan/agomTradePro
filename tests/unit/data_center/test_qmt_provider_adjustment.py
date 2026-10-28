"""QMT unified adapter contracts for price adjustment and bridge compatibility."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.domain.entities import PriceBar, ProviderConfig
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure._provider_adapter_specialized import (
    QmtUnifiedProviderAdapter,
)
from apps.data_center.infrastructure.gateways.qmt_gateway import QMTGateway
from apps.data_center.infrastructure.market_gateway_entities import HistoricalPriceBar
from core.exceptions import DataValidationError


@pytest.mark.parametrize(
    ("dividend_type", "expected_adjustment"),
    (
        ("none", PriceAdjustment.NONE),
        ("front", PriceAdjustment.FORWARD),
        ("back", PriceAdjustment.BACKWARD),
        ("front_ratio", PriceAdjustment.FORWARD),
        ("back_ratio", PriceAdjustment.BACKWARD),
    ),
)
def test_qmt_unified_price_history_preserves_gateway_adjustment(
    monkeypatch: pytest.MonkeyPatch,
    dividend_type: str,
    expected_adjustment: PriceAdjustment,
) -> None:
    """Carry actual Gateway adjustment and request scope through the public adapter."""

    observed_calls: list[dict[str, object]] = []

    def get_market_data_ex(**kwargs: object) -> dict[str, pd.DataFrame]:
        observed_calls.append(kwargs)
        return {
            "000001.SZ": pd.DataFrame(
                [
                    {
                        "time": "20261028",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 10_500.0,
                    }
                ]
            )
        }

    xtdata = SimpleNamespace(get_market_data_ex=get_market_data_ex)
    monkeypatch.setattr(QMTGateway, "_load_xtdata", lambda _gateway: xtdata)
    adapter = QmtUnifiedProviderAdapter(
        ProviderConfig(
            id=18,
            name="QMT test",
            source_type="qmt",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={"dividend_type": dividend_type},
            description="",
        )
    )

    bars = adapter.fetch_price_history("000001.SZ", date(2026, 10, 27), date(2026, 10, 29))

    assert len(bars) == 1
    assert bars[0].adjustment is expected_adjustment
    assert bars[0].asset_code == "000001.SZ"
    assert bars[0].bar_date == date(2026, 10, 28)
    assert bars[0].volume == 1000.0
    assert len(observed_calls) == 1
    assert observed_calls[0] == {
        "field_list": ["time", "open", "high", "low", "close", "volume", "amount"],
        "stock_list": ["000001.SZ"],
        "period": "1d",
        "start_time": "20261027",
        "end_time": "20261029",
        "count": -1,
        "dividend_type": dividend_type,
        "fill_data": False,
    }


def test_qmt_bridge_price_history_keeps_existing_unadjusted_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured bridge path still returns its existing unadjusted bar unchanged."""

    from apps.data_center.infrastructure.qmt_bridge_provider import QmtBridgeProvider

    start = date(2026, 10, 27)
    end = date(2026, 10, 29)
    bridge_bar = PriceBar(
        asset_code="000001.SZ",
        bar_date=date(2026, 10, 28),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        source="qmt-bridge:test",
    )
    bridge_bars = [bridge_bar]
    observed_calls: list[tuple[str, date, date]] = []

    def read_bars(
        provider: QmtBridgeProvider,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        observed_calls.append((provider.binding_id, start_date, end_date))
        assert asset_code == "000001.SZ"
        return bridge_bars

    monkeypatch.setattr(QmtBridgeProvider, "bars", read_bars)
    adapter = QmtUnifiedProviderAdapter(
        ProviderConfig(
            id=18,
            name="QMT bridge test",
            source_type="qmt",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={"qmt_bridge_id": "binding-18", "dividend_type": "front"},
            description="",
        )
    )

    bars = adapter.fetch_price_history("000001.SZ", start, end)

    assert bars is bridge_bars
    assert bars[0].adjustment is PriceAdjustment.NONE
    assert observed_calls == [("binding-18", start, end)]


def test_qmt_unified_adapter_rejects_inexact_gateway_integer_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an exact Gateway integer when the public float DTO would round it."""

    source_volume = 2**53 + 1
    xtdata = SimpleNamespace(
        get_market_data_ex=lambda **_kwargs: {
            "000001.SZ": pd.DataFrame(
                [
                    {
                        "time": "20261028",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": source_volume,
                        "amount": 10_500.0,
                    }
                ]
            )
        }
    )
    monkeypatch.setattr(QMTGateway, "_load_xtdata", lambda _gateway: xtdata)
    gateway = QMTGateway(extra_config={"dividend_type": "none"})
    gateway_bars = gateway.get_historical_prices("000001.SZ", "20261028", "20261028")
    assert len(gateway_bars) == 1
    assert gateway_bars[0].volume == source_volume

    adapter = QmtUnifiedProviderAdapter(
        ProviderConfig(
            id=18,
            name="QMT precision test",
            source_type="qmt",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={"dividend_type": "none"},
            description="",
        )
    )

    with pytest.raises(DataValidationError) as caught:
        adapter.fetch_price_history("000001.SZ", date(2026, 10, 28), date(2026, 10, 28))

    assert caught.value.code == "QMT_VOLUME_NOT_EXACTLY_REPRESENTABLE"


def test_qmt_unified_adapter_keeps_missing_gateway_volume_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing volume remains None through the actual Gateway and unified adapter."""

    xtdata = SimpleNamespace(
        get_market_data_ex=lambda **_kwargs: {
            "000001.SZ": pd.DataFrame(
                [
                    {
                        "time": "20261028",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": None,
                        "amount": 10_500.0,
                    }
                ]
            )
        }
    )
    monkeypatch.setattr(QMTGateway, "_load_xtdata", lambda _gateway: xtdata)
    adapter = QmtUnifiedProviderAdapter(
        ProviderConfig(
            id=18,
            name="QMT missing volume test",
            source_type="qmt",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={"dividend_type": "none"},
            description="",
        )
    )

    bars = adapter.fetch_price_history("000001.SZ", date(2026, 10, 28), date(2026, 10, 28))

    assert len(bars) == 1
    assert bars[0].volume is None


@pytest.mark.parametrize("source_volume", (-1, 10**400), ids=("negative", "float-overflow"))
def test_qmt_unified_adapter_rejects_invalid_integer_volume(
    monkeypatch: pytest.MonkeyPatch,
    source_volume: int,
) -> None:
    """Reject negative or out-of-range source volume instead of returning a partial list."""

    adapter = QmtUnifiedProviderAdapter(
        ProviderConfig(
            id=18,
            name="QMT overflow test",
            source_type="qmt",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )
    )
    gateway_bar = HistoricalPriceBar(
        asset_code="000001.SZ",
        trade_date=date(2026, 10, 28),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        volume=source_volume,
    )
    monkeypatch.setattr(
        adapter,
        "_gateway",
        lambda: SimpleNamespace(get_historical_prices=lambda **_kwargs: [gateway_bar]),
    )

    with pytest.raises(DataValidationError) as caught:
        adapter.fetch_price_history("000001.SZ", date(2026, 10, 28), date(2026, 10, 28))

    assert caught.value.code == "QMT_VOLUME_NOT_EXACTLY_REPRESENTABLE"
