from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    inspect_latest_trade_date,
    resolve_effective_trade_date,
)


class _MockTushareProClient:
    def index_weight(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if index_code != "000300.SH":
            return pd.DataFrame(columns=["trade_date", "con_code"])
        return pd.DataFrame(
            [
                {"trade_date": "20260403", "con_code": "600000.SH"},
            ]
        )

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ts_code != "600000.SH":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": "20260331",
                    "open": 10.00,
                    "high": 10.20,
                    "low": 9.90,
                    "close": 10.10,
                    "vol": 1200.0,
                    "pct_chg": 1.0,
                },
                {
                    "ts_code": ts_code,
                    "trade_date": "20260401",
                    "open": 10.10,
                    "high": 10.30,
                    "low": 10.00,
                    "close": 10.20,
                    "vol": 1300.0,
                    "pct_chg": 0.99,
                },
                {
                    "ts_code": ts_code,
                    "trade_date": "20260403",
                    "open": 10.15,
                    "high": 10.25,
                    "low": 10.05,
                    "close": 10.18,
                    "vol": 1400.0,
                    "pct_chg": -0.20,
                },
            ]
        )

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ts_code != "600000.SH":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {"ts_code": ts_code, "trade_date": "20260331", "adj_factor": 16.5},
                {"ts_code": ts_code, "trade_date": "20260401", "adj_factor": 16.5},
                {"ts_code": ts_code, "trade_date": "20260403", "adj_factor": 16.5},
            ]
        )

    def trade_cal(self, exchange: str, start_date: str, end_date: str, is_open: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"cal_date": "20260331"},
                {"cal_date": "20260401"},
                {"cal_date": "20260402"},
                {"cal_date": "20260403"},
            ]
        )

    def index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ts_code != "000300.SH":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "trade_date": "20260331",
                    "open": 4400.0,
                    "high": 4410.0,
                    "low": 4390.0,
                    "close": 4405.0,
                    "vol": 1000000.0,
                    "pct_chg": 0.20,
                },
                {
                    "ts_code": ts_code,
                    "trade_date": "20260401",
                    "open": 4410.0,
                    "high": 4420.0,
                    "low": 4400.0,
                    "close": 4415.0,
                    "vol": 1100000.0,
                    "pct_chg": 0.23,
                },
                {
                    "ts_code": ts_code,
                    "trade_date": "20260403",
                    "open": 4412.0,
                    "high": 4418.0,
                    "low": 4399.0,
                    "close": 4400.0,
                    "vol": 1200000.0,
                    "pct_chg": -0.34,
                },
            ]
        )


def test_resolve_effective_trade_date_adjusts_to_latest_available() -> None:
    effective_date, metadata = resolve_effective_trade_date(
        requested_trade_date=date(2026, 4, 6),
        latest_available_date=date(2026, 4, 3),
    )

    assert effective_date == date(2026, 4, 3)
    assert metadata["trade_date_adjusted"] is True
    assert metadata["effective_trade_date"] == "2026-04-03"


def test_resolve_effective_trade_date_allows_ten_day_holiday_gap() -> None:
    effective_date, metadata = resolve_effective_trade_date(
        requested_trade_date=date(2026, 4, 13),
        latest_available_date=date(2026, 4, 3),
    )

    assert effective_date == date(2026, 4, 3)
    assert metadata["trade_date_adjusted"] is True


def test_resolve_effective_trade_date_raises_when_gap_is_too_large() -> None:
    with pytest.raises(RuntimeError, match="2020-09-25"):
        resolve_effective_trade_date(
            requested_trade_date=date(2026, 4, 6),
            latest_available_date=date(2020, 9, 25),
        )


def test_tushare_qlib_builder_writes_recent_layout(tmp_path: Path) -> None:
    provider_uri = tmp_path / "cn_data"
    builder = TushareQlibBuilder(str(provider_uri), pro_client=_MockTushareProClient())

    summary = builder.build_recent_data(
        target_date=date(2026, 4, 6),
        universes=["csi300"],
        lookback_days=30,
    )

    assert summary.latest_local_date_after == date(2026, 4, 3)
    assert inspect_latest_trade_date(str(provider_uri)) == date(2026, 4, 3)
    assert summary.instrument_files_written == 2
    assert summary.feature_series_written == 14

    all_txt = provider_uri / "instruments" / "all.txt"
    csi300_txt = provider_uri / "instruments" / "csi300.txt"
    assert all_txt.exists()
    assert csi300_txt.exists()
    assert "SH600000" in all_txt.read_text(encoding="utf-8")
    assert "SH600000" in csi300_txt.read_text(encoding="utf-8")

    factor_path = provider_uri / "features" / "sh600000" / "factor.day.bin"
    close_path = provider_uri / "features" / "sh600000" / "close.day.bin"
    assert factor_path.exists()
    assert close_path.exists()

    factor_raw = np.fromfile(factor_path, dtype="<f")
    close_raw = np.fromfile(close_path, dtype="<f")
    assert int(factor_raw[0]) == 0
    assert len(factor_raw) == 5
    assert len(close_raw) == 5


def test_tushare_qlib_builder_writes_explicit_stock_scope(tmp_path: Path) -> None:
    provider_uri = tmp_path / "cn_data"
    builder = TushareQlibBuilder(str(provider_uri), pro_client=_MockTushareProClient())

    summary = builder.build_recent_data_for_codes(
        target_date=date(2026, 4, 6),
        stock_codes=["600000.SH"],
        universe_id="scoped_portfolios",
        lookback_days=30,
    )

    assert summary.stock_count == 1
    assert summary.universe_count == 1
    assert summary.latest_local_date_after == date(2026, 4, 3)

    scoped_txt = provider_uri / "instruments" / "scoped_portfolios.txt"
    assert scoped_txt.exists()
    assert "SH600000" in scoped_txt.read_text(encoding="utf-8")
