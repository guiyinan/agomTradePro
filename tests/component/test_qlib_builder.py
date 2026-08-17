from __future__ import annotations

import threading
import time
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
from apps.config_center.infrastructure.models import AlphaUniverseConfigModel


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

    def trade_cal(
        self, exchange: str, start_date: str, end_date: str, is_open: str
    ) -> pd.DataFrame:
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


class _RateLimitedIndexWeightClient(_MockTushareProClient):
    def index_weight(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise RuntimeError("您请求速度过快")


class _CapturingIndexWeightClient(_MockTushareProClient):
    def __init__(self) -> None:
        self.index_weight_calls: list[tuple[str, str, str]] = []

    def index_weight(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.index_weight_calls.append((index_code, start_date, end_date))
        return pd.DataFrame(
            [
                {"trade_date": "20260101", "con_code": "600000.SH"},
            ]
        )


class _SensitiveIndexWeightErrorClient(_MockTushareProClient):
    def index_weight(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise RuntimeError("provider secret=do-not-log")


class _NonFiniteFactorClient(_MockTushareProClient):
    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = super().adj_factor(ts_code, start_date, end_date)
        frame["adj_factor"] = np.inf
        return frame


class _UntrustedDailyRowsClient(_MockTushareProClient):
    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = super().daily(ts_code, start_date, end_date)
        return pd.concat(
            [
                frame,
                pd.DataFrame(
                    [
                        {
                            "ts_code": ts_code,
                            "trade_date": "20260407",
                            "open": 10.0,
                            "high": 10.2,
                            "low": 9.9,
                            "close": 10.1,
                            "vol": 100.0,
                            "pct_chg": 1.0,
                        },
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260403",
                            "open": 10.0,
                            "high": 10.2,
                            "low": 9.9,
                            "close": 10.1,
                            "vol": 100.0,
                            "pct_chg": 1.0,
                        },
                        {
                            "ts_code": ts_code,
                            "trade_date": "20260402",
                            "open": 10.0,
                            "high": 9.0,
                            "low": 9.9,
                            "close": 10.1,
                            "vol": 100.0,
                            "pct_chg": 1.0,
                        },
                    ]
                ),
            ],
            ignore_index=True,
        )


class _ConcurrentStockClient(_MockTushareProClient):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_calls = 0
        self.max_active_calls = 0

    def daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._record_call(
            pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "trade_date": "20260403",
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 100.0,
                        "pct_chg": 1.0,
                    }
                ]
            )
        )

    def adj_factor(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._record_call(
            pd.DataFrame(
                [{"ts_code": ts_code, "trade_date": "20260403", "adj_factor": 16.5}]
            )
        )

    def _record_call(self, result: pd.DataFrame) -> pd.DataFrame:
        with self._lock:
            self._active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self._active_calls)
        try:
            time.sleep(0.02)
            return result
        finally:
            with self._lock:
                self._active_calls -= 1


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


@pytest.mark.django_db
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


@pytest.mark.django_db
def test_tushare_qlib_builder_falls_back_to_local_universe_members(tmp_path: Path) -> None:
    provider_uri = tmp_path / "cn_data"
    instrument_dir = provider_uri / "instruments"
    instrument_dir.mkdir(parents=True)
    (instrument_dir / "csi300.txt").write_text(
        "SH600000\t2005-01-01\t2026-05-06\n",
        encoding="utf-8",
    )
    builder = TushareQlibBuilder(str(provider_uri), pro_client=_RateLimitedIndexWeightClient())

    summary = builder.build_recent_data(
        target_date=date(2026, 4, 6),
        universes=["csi300"],
        lookback_days=30,
    )

    assert summary.stock_count == 1
    assert summary.universe_count == 1
    assert summary.latest_local_date_after == date(2026, 4, 3)
    assert "SH600000" in (provider_uri / "instruments" / "csi300.txt").read_text(encoding="utf-8")


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


@pytest.mark.django_db
def test_tushare_qlib_builder_resolves_custom_config_center_universe(tmp_path: Path) -> None:
    AlphaUniverseConfigModel.objects.create(
        universe_id="custom_large_cap",
        name="自定义大盘池",
        source_type=AlphaUniverseConfigModel.SOURCE_MANUAL,
        stock_codes=["600000.SH"],
        is_active=True,
    )
    provider_uri = tmp_path / "cn_data"
    builder = TushareQlibBuilder(str(provider_uri), pro_client=_MockTushareProClient())

    summary = builder.build_recent_data(
        target_date=date(2026, 4, 6),
        universes=["custom_large_cap"],
        lookback_days=30,
    )

    assert summary.stock_count == 1
    assert summary.universe_count == 1
    custom_txt = provider_uri / "instruments" / "custom_large_cap.txt"
    assert custom_txt.exists()
    assert "SH600000" in custom_txt.read_text(encoding="utf-8")


@pytest.mark.django_db
def test_tushare_qlib_builder_resolves_index_mapping_from_config_center(
    tmp_path: Path,
) -> None:
    AlphaUniverseConfigModel.objects.create(
        universe_id="custom_index",
        name="自定义指数池",
        source_type=AlphaUniverseConfigModel.SOURCE_TUSHARE_INDEX,
        filters={"index_code": "000300.SH"},
        is_active=True,
    )
    client = _CapturingIndexWeightClient()
    builder = TushareQlibBuilder(str(tmp_path / "cn_data"), pro_client=client)

    summary = builder.build_recent_data(
        target_date=date(2026, 4, 6),
        universes=["custom_index"],
        lookback_days=30,
    )

    assert summary.stock_count == 1
    assert client.index_weight_calls == [("000300.SH", "20251117", "20260406")]


def test_tushare_qlib_builder_rejects_invalid_explicit_scope(tmp_path: Path) -> None:
    builder = TushareQlibBuilder(
        str(tmp_path / "cn_data"),
        pro_client=_MockTushareProClient(),
    )

    with pytest.raises(ValueError, match="Tushare format"):
        builder.build_recent_data_for_codes(
            target_date=date(2026, 4, 6),
            stock_codes=["600000.SH", "../../secret"],
        )

    with pytest.raises(ValueError, match="Universe ID"):
        builder.build_recent_data_for_codes(
            target_date=date(2026, 4, 6),
            stock_codes=["600000.SH"],
            universe_id="../outside",
        )


def test_tushare_qlib_builder_rejects_invalid_build_window(tmp_path: Path) -> None:
    builder = TushareQlibBuilder(
        str(tmp_path / "cn_data"),
        pro_client=_MockTushareProClient(),
    )

    with pytest.raises(ValueError, match="1 to 3650"):
        builder.build_recent_data_for_codes(
            target_date=date(2026, 4, 6),
            stock_codes=["600000.SH"],
            lookback_days=0,
        )

    with pytest.raises(ValueError, match="1 to 3650"):
        builder.build_recent_data_for_codes(
            target_date=date(2026, 4, 6),
            stock_codes=["600000.SH"],
            lookback_days=3651,
        )

    with pytest.raises(ValueError, match="future"):
        builder.build_recent_data_for_codes(
            target_date=date.today().replace(year=date.today().year + 1),
            stock_codes=["600000.SH"],
        )


@pytest.mark.django_db
def test_tushare_qlib_builder_redacts_provider_error_detail(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider_uri = tmp_path / "cn_data"
    instrument_dir = provider_uri / "instruments"
    instrument_dir.mkdir(parents=True)
    (instrument_dir / "csi300.txt").write_text(
        "SH600000\t2005-01-01\t2026-05-06\n",
        encoding="utf-8",
    )
    builder = TushareQlibBuilder(
        str(provider_uri),
        pro_client=_SensitiveIndexWeightErrorClient(),
    )

    with caplog.at_level("WARNING"):
        builder.build_recent_data(
            target_date=date(2026, 4, 6),
            universes=["csi300"],
            lookback_days=30,
        )

    assert "RuntimeError" in caplog.text
    assert "do-not-log" not in caplog.text


def test_tushare_qlib_builder_drops_non_finite_adjustment_factors(
    tmp_path: Path,
) -> None:
    provider_uri = tmp_path / "cn_data"
    builder = TushareQlibBuilder(
        str(provider_uri),
        pro_client=_NonFiniteFactorClient(),
    )

    summary = builder.build_recent_data_for_codes(
        target_date=date(2026, 4, 6),
        stock_codes=["600000.SH"],
        lookback_days=30,
    )

    assert summary.feature_series_written == 0
    assert not (provider_uri / "features" / "sh600000").exists()


def test_tushare_qlib_builder_rejects_out_of_scope_and_invalid_daily_rows(
    tmp_path: Path,
) -> None:
    provider_uri = tmp_path / "cn_data"
    builder = TushareQlibBuilder(
        str(provider_uri),
        pro_client=_UntrustedDailyRowsClient(),
    )

    summary = builder.build_recent_data_for_codes(
        target_date=date(2026, 4, 6),
        stock_codes=["600000.SH"],
        lookback_days=30,
    )

    assert summary.effective_target_date == date(2026, 4, 3)
    close_raw = np.fromfile(
        provider_uri / "features" / "sh600000" / "close.day.bin",
        dtype="<f",
    )
    assert len(close_raw) == 5


def test_tushare_qlib_builder_rejects_invalid_retry_policy() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        TushareQlibBuilder._call_with_retry(lambda: None, retries=0)

    with pytest.raises(ValueError, match="finite and non-negative"):
        TushareQlibBuilder._call_with_retry(lambda: None, delay_seconds=float("nan"))


def test_tushare_qlib_builder_fetches_stocks_with_bounded_concurrency(
    tmp_path: Path,
) -> None:
    client = _ConcurrentStockClient()
    builder = TushareQlibBuilder(
        str(tmp_path / "cn_data"),
        pro_client=client,
        fetch_workers=4,
    )

    stock_codes = [f"{code:06d}.SZ" for code in range(1, 13)]
    daily_frame = builder._fetch_stock_daily(
        stock_codes,
        date(2026, 4, 1),
        date(2026, 4, 3),
    )
    adj_factor_frame = builder._fetch_stock_adj_factor(
        stock_codes,
        date(2026, 4, 1),
        date(2026, 4, 3),
    )

    assert len(daily_frame) == 12
    assert len(adj_factor_frame) == 12
    assert 2 <= client.max_active_calls <= 4


@pytest.mark.parametrize("fetch_workers", [0, -1, True])
def test_tushare_qlib_builder_rejects_invalid_fetch_workers(
    tmp_path: Path,
    fetch_workers: object,
) -> None:
    with pytest.raises(ValueError, match="fetch_workers"):
        TushareQlibBuilder(
            str(tmp_path / "cn_data"),
            pro_client=_MockTushareProClient(),
            fetch_workers=fetch_workers,  # type: ignore[arg-type]
        )


def test_tushare_qlib_builder_does_not_retry_authorization_failures() -> None:
    calls = 0

    def reject() -> None:
        nonlocal calls
        calls += 1
        raise PermissionError("provider authorization rejected")

    with pytest.raises(PermissionError, match="authorization rejected"):
        TushareQlibBuilder._call_with_retry(
            reject,
            retries=3,
            delay_seconds=0,
        )

    assert calls == 1
