"""Behavioral checks for the QMT market snapshot vendor boundary."""

from __future__ import annotations

import sys
from dataclasses import is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from qmt_agent.qmt_adapter import XtQuantAdapter


class _FakeXtData:
    """Record requested QMT metadata and tick data without vendor access."""

    def __init__(
        self,
        *,
        detail: object,
        ticks: object,
    ) -> None:
        self.detail = detail
        self.ticks = ticks
        self.detail_calls: list[str] = []
        self.tick_calls: list[list[str]] = []

    def get_instrument_detail(self, asset_code: str) -> object:
        """Return a configured instrument detail fixture."""

        self.detail_calls.append(asset_code)
        return self.detail

    def get_full_tick(self, asset_codes: list[str]) -> object:
        """Return configured full-tick data for the requested symbols."""

        self.tick_calls.append(asset_codes)
        return self.ticks


class _FakeVendorArray:
    """Stand in for vendor quote arrays that expose ``tolist``."""

    def __init__(self, values: list[object]) -> None:
        self.values = values

    def tolist(self) -> list[object]:
        """Match the value conversion used by NumPy-like vendor arrays."""

        return self.values


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    detail: object,
    ticks: object,
) -> tuple[XtQuantAdapter, _FakeXtData]:
    """Create a connected adapter backed only by a local fake xtdata object."""

    xtdata = _FakeXtData(detail=detail, ticks=ticks)
    xtquant_module = ModuleType("xtquant")
    xtquant_module.xtdata = xtdata
    monkeypatch.setitem(sys.modules, "xtquant", xtquant_module)
    adapter = XtQuantAdapter(
        userdata_path=Path("unused"),
        broker_account_id="fake-account",
    )
    adapter.trader = object()
    return adapter, xtdata


def test_market_snapshot_uses_documented_detail_fields_and_keeps_compatibility_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, xtdata = _adapter(
        monkeypatch,
        detail={
            "UpStopPrice": 11.76,
            "DownStopPrice": 9.62,
            "PriceTick": 0.01,
            "InstrumentStatus": 0,
            "IsTrading": True,
        },
        ticks={
            "600000.SH": {
                "time": 1_797_000_000_123,
                "lastPrice": 10.25,
                "askPrice": _FakeVendorArray([10.26, 10.27]),
                "bidPrice": _FakeVendorArray([10.24, 10.23]),
                "openInt": 91,
                "stockStatus": 13,
                "upperLimit": 99,
                "lowerLimit": 1,
            }
        },
    )

    snapshot = adapter.market_snapshot("600000.SH")

    assert xtdata.detail_calls == ["600000.SH"]
    assert xtdata.tick_calls == [["600000.SH"]]
    assert snapshot["last_price"] == "10.25"
    assert snapshot["upper_limit"] == "11.76"
    assert snapshot["lower_limit"] == "9.62"
    assert snapshot["price_tick"] == "0.01"
    assert snapshot["ask_price"] == "10.26"
    assert snapshot["bid_price"] == "10.24"
    assert snapshot["open_int"] == "91"
    assert snapshot["tick_time_ms"] == 1_797_000_000_123
    assert snapshot["instrument_status"] == 0
    assert snapshot["is_trading"] is True
    assert snapshot["stock_status"] == 13
    assert snapshot["security_state"] == "UNKNOWN"
    assert snapshot["boundary_mode"] == "REPORTED_LIMITS"
    assert snapshot["boundary_usable_for_submission"] is False
    assert snapshot["metadata_observed_at"] is None
    assert snapshot["field_sources"]["upper_limit"] == ("xtdata.get_instrument_detail.UpStopPrice")
    assert snapshot["field_sources"]["last_price"] == "xtdata.get_full_tick.lastPrice"
    captured_at = datetime.fromisoformat(str(snapshot["captured_at_utc"]))
    assert captured_at.utcoffset() is not None


def test_capture_market_snapshot_returns_a_typed_auditable_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"UpStopPrice": 11, "DownStopPrice": 9},
        ticks={"600000.SH": {"lastPrice": 10, "time": 1_797_000_000_123}},
    )

    snapshot = adapter.capture_market_snapshot("600000.SH")

    assert is_dataclass(snapshot)
    assert snapshot.asset_code == "600000.SH"
    assert snapshot.security_state.value == "UNKNOWN"
    assert snapshot.boundary_mode.value == "REPORTED_LIMITS"
    assert snapshot.metadata_observed_at is None
    assert snapshot.last_price.source_api == "xtdata.get_full_tick"
    assert snapshot.upper_limit.source_field == "UpStopPrice"


def test_missing_or_invalid_vendor_values_are_unknown_or_invalid_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"UpStopPrice": None, "DownStopPrice": "NaN", "PriceTick": 0},
        ticks={
            "600000.SH": {
                "lastPrice": 0,
                "askPrice": [],
                "bidPrice": [float("inf")],
                "openInt": -1,
                "time": 0,
            }
        },
    )

    snapshot = adapter.capture_market_snapshot("600000.SH")
    payload = snapshot.to_payload()

    assert payload["last_price"] is None
    assert payload["upper_limit"] is None
    assert payload["lower_limit"] is None
    assert payload["price_tick"] is None
    assert payload["ask_price"] is None
    assert payload["bid_price"] is None
    assert payload["open_int"] is None
    assert payload["tick_time_ms"] is None
    assert payload["boundary_mode"] == "UNKNOWN"
    assert snapshot.last_price.state.value == "UNKNOWN"
    assert snapshot.upper_limit.state.value == "UNKNOWN"
    assert snapshot.lower_limit.state.value == "INVALID"
    assert snapshot.bid_price.state.value == "INVALID"
    assert snapshot.open_int.state.value == "INVALID"


@pytest.mark.parametrize(
    "detail",
    [
        {"UpStopPrice": 11},
        {"UpStopPrice": 9, "DownStopPrice": 11},
    ],
)
def test_missing_or_inverted_limit_pair_marks_both_compatibility_bounds_unknown(
    monkeypatch: pytest.MonkeyPatch,
    detail: object,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail=detail,
        ticks={"600000.SH": {"lastPrice": 10}},
    )

    payload = adapter.market_snapshot("600000.SH")

    assert payload["upper_limit"] is None
    assert payload["lower_limit"] is None
    assert payload["boundary_mode"] == "UNKNOWN"
    assert payload["boundary_usable_for_submission"] is False


def test_non_mapping_vendor_responses_produce_unknown_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(monkeypatch, detail=["bad"], ticks=["bad"])

    payload = adapter.market_snapshot("600000.SH")

    assert payload["last_price"] is None
    assert payload["upper_limit"] is None
    assert payload["lower_limit"] is None
    assert payload["boundary_mode"] == "UNKNOWN"
    assert payload["security_state"] == "UNKNOWN"


def test_tick_limit_decoys_are_ignored_when_instrument_metadata_lacks_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"PriceTick": 0.01},
        ticks={
            "600000.SH": {
                "lastPrice": 10,
                "upperLimit": 11,
                "lowerLimit": 9,
            }
        },
    )

    payload = adapter.market_snapshot("600000.SH")

    assert payload["upper_limit"] is None
    assert payload["lower_limit"] is None
    assert payload["boundary_mode"] == "UNKNOWN"
    assert payload["field_evidence"]["upper_limit"]["source_field"] == "UpStopPrice"
    assert payload["field_evidence"]["upper_limit"]["state"] == "UNKNOWN"


def test_positive_instrument_status_and_is_trading_do_not_prove_tradability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"InstrumentStatus": 1, "IsTrading": True},
        ticks={"600000.SH": {"stockStatus": 3}},
    )

    payload = adapter.market_snapshot("600000.SH")

    assert payload["instrument_status"] == 1
    assert payload["is_trading"] is True
    assert payload["stock_status"] == 3
    assert payload["security_state"] == "UNKNOWN"
    assert payload["market_evidence_usable_for_submission"] is False


@pytest.mark.parametrize("value", [Decimal("1E+1000000"), Decimal("1E-1000000")])
def test_extreme_decimal_exponents_are_rejected_without_expansion(
    monkeypatch: pytest.MonkeyPatch,
    value: Decimal,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"UpStopPrice": value, "DownStopPrice": 1},
        ticks={"600000.SH": {"lastPrice": value}},
    )

    snapshot = adapter.capture_market_snapshot("600000.SH")

    assert snapshot.last_price.state.value == "INVALID"
    assert snapshot.last_price.reason_code == "NUMERIC_TEXT_TOO_LONG"
    assert snapshot.upper_limit.state.value == "INVALID"
    assert snapshot.upper_limit.reason_code == "NUMERIC_TEXT_TOO_LONG"
    assert snapshot.boundary_mode.value == "UNKNOWN"


def test_market_snapshot_requires_a_connected_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={},
        ticks={},
    )
    adapter.trader = None

    with pytest.raises(RuntimeError, match="not connected"):
        adapter.market_snapshot("600000.SH")


def test_external_float_values_use_their_decimal_text_without_binary_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _xtdata = _adapter(
        monkeypatch,
        detail={"UpStopPrice": 0.3, "DownStopPrice": 0.1, "PriceTick": 0.01},
        ticks={"600000.SH": {"lastPrice": 0.2}},
    )

    payload = adapter.market_snapshot("600000.SH")

    assert payload["last_price"] == "0.2"
    assert payload["upper_limit"] == "0.3"
    assert payload["lower_limit"] == "0.1"
    assert payload["price_tick"] == "0.01"
