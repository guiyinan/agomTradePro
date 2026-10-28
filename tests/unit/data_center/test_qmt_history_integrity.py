from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.gateways import qmt_gateway


def _bar_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "time": "20240102",
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "volume": 100,
        "amount": 1100.0,
    }
    row.update(changes)
    return row


def _gateway_with_response(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    *,
    extra_config: dict[str, object] | None = None,
) -> tuple[qmt_gateway.QMTGateway, list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def get_market_data_ex(**kwargs: object) -> object:
        calls.append(kwargs)
        return response

    gateway = qmt_gateway.QMTGateway(extra_config=extra_config)
    monkeypatch.setattr(
        gateway,
        "_load_xtdata",
        lambda: SimpleNamespace(get_market_data_ex=get_market_data_ex),
    )
    return gateway, calls


@pytest.mark.parametrize(
    ("dividend_type", "expected_adjustment"),
    [
        ("none", PriceAdjustment.NONE),
        ("front", PriceAdjustment.FORWARD),
        ("back", PriceAdjustment.BACKWARD),
        ("front_ratio", PriceAdjustment.FORWARD),
        ("back_ratio", PriceAdjustment.BACKWARD),
    ],
)
def test_history_uses_unfilled_bars_and_preserves_supported_adjustment(
    monkeypatch: pytest.MonkeyPatch,
    dividend_type: str,
    expected_adjustment: PriceAdjustment,
) -> None:
    response = {"000001.SZ": pd.DataFrame([_bar_row()])}
    gateway, calls = _gateway_with_response(
        monkeypatch,
        response,
        extra_config={"dividend_type": dividend_type},
    )

    bars = gateway.get_historical_prices("000001.SZ", "20240101", "20240131")

    assert calls[0]["fill_data"] is False
    assert calls[0]["dividend_type"] == dividend_type
    assert len(bars) == 1
    assert bars[0].adjustment is expected_adjustment


def test_unknown_adjustment_is_rejected_before_loading_qmt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = qmt_gateway.QMTGateway(extra_config={"dividend_type": "future_mode"})
    calls: list[str] = []

    def load() -> object:
        calls.append("load")
        return SimpleNamespace(get_market_data_ex=lambda **_kwargs: {})

    monkeypatch.setattr(gateway, "_load_xtdata", load)

    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
    assert calls == []


def test_history_never_borrows_a_different_security_or_unidentified_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = pd.DataFrame([_bar_row()])
    gateway, _ = _gateway_with_response(monkeypatch, {"600000.SH": foreign})
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []

    gateway, _ = _gateway_with_response(monkeypatch, pd.DataFrame([_bar_row()]))
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


def test_single_frame_requires_and_checks_its_own_security_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identified = pd.DataFrame([_bar_row(stock_code="000001.SZ")])
    gateway, _ = _gateway_with_response(monkeypatch, identified)
    bars = gateway.get_historical_prices("000001.SZ", "20240101", "20240131")
    assert len(bars) == 1

    mismatched = pd.DataFrame([_bar_row(stock_code="600000.SH")])
    gateway, _ = _gateway_with_response(monkeypatch, mismatched)
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []

    identified_by_ts_code = pd.DataFrame([_bar_row(ts_code="000001.SZ")])
    gateway, _ = _gateway_with_response(monkeypatch, identified_by_ts_code)
    assert len(gateway.get_historical_prices("000001.SZ", "20240101", "20240131")) == 1

    mismatched_ts_code = pd.DataFrame([_bar_row(ts_code="600000.SH")])
    gateway, _ = _gateway_with_response(monkeypatch, mismatched_ts_code)
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


@pytest.mark.parametrize(
    "rows",
    [
        [_bar_row(), _bar_row()],
        [_bar_row(), _bar_row(close=11.5)],
        [_bar_row(), _bar_row(open=0)],
    ],
)
def test_history_rejects_a_date_with_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
) -> None:
    gateway, _ = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame(rows)},
    )

    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (1704153600, date(2024, 1, 2)),
        (1704211200, date(2024, 1, 3)),
        (1704211200000, date(2024, 1, 3)),
        ("1704153600000", date(2024, 1, 2)),
        (datetime(2024, 1, 1, 16, 0, tzinfo=UTC), date(2024, 1, 2)),
        ("2024-01-01T16:00:00+00:00", date(2024, 1, 2)),
    ],
)
def test_epoch_and_aware_times_resolve_to_china_market_date(
    timestamp: object,
    expected: date,
) -> None:
    assert qmt_gateway.QMTGateway._parse_trade_date(timestamp) == expected


def test_invalid_epoch_and_out_of_range_history_dates_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert qmt_gateway.QMTGateway._parse_trade_date("99999999999999999999") is None
    response = {
        "000001.SZ": pd.DataFrame(
            [
                _bar_row(time="20231229"),
                _bar_row(time="20240115"),
                _bar_row(time="20240201"),
            ]
        )
    }
    gateway, _ = _gateway_with_response(monkeypatch, response)

    bars = gateway.get_historical_prices("000001.SZ", "20240101", "20240131")

    assert [bar.trade_date for bar in bars] == [date(2024, 1, 15)]
    assert qmt_gateway.QMTGateway._parse_trade_date(20240102) == date(2024, 1, 2)


def test_iso_request_bounds_are_normalized_for_qmt_without_changing_the_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, calls = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame([_bar_row(time="20240115")])},
    )

    bars = gateway.get_historical_prices("000001.SZ", "2024-01-01", "2024-01-31")

    assert calls[0]["start_time"] == "20240101"
    assert calls[0]["end_time"] == "20240131"
    assert len(bars) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", None),
        ("high", float("nan")),
        ("low", float("inf")),
        ("close", 0),
        ("close", -1),
    ],
)
def test_history_drops_bars_with_missing_or_nonpositive_ohlc(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    response = {"000001.SZ": pd.DataFrame([_bar_row(**{field: value})])}
    gateway, _ = _gateway_with_response(monkeypatch, response)

    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


@pytest.mark.parametrize(
    "changes",
    [
        {"low": 12.0},
        {"open": 12.5},
        {"close": 12.5},
        {"open": True},
        {"high": True},
    ],
)
def test_history_rejects_inconsistent_or_boolean_ohlc(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
) -> None:
    gateway, _ = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame([_bar_row(**changes)])},
    )

    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


def test_history_does_not_truncate_fractional_volume_into_valid_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, _ = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame([_bar_row(volume=100.5)])},
    )

    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


def test_history_preserves_exact_large_integer_volume_and_rejects_unreliable_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_volume = 2**53 + 1
    gateway, _ = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame([_bar_row(volume=exact_volume)])},
    )
    bars = gateway.get_historical_prices("000001.SZ", "20240101", "20240131")
    assert len(bars) == 1
    assert bars[0].volume == exact_volume

    gateway, _ = _gateway_with_response(
        monkeypatch,
        {"000001.SZ": pd.DataFrame([_bar_row(volume=float(2**53 + 2))])},
    )
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
