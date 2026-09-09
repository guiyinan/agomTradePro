"""Tushare normalization behind the Data Center model-market contract."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Event
from typing import Any, Protocol, TypeVar, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from apps.data_center.domain.model_market_data import ModelDailyBar
from core.exceptions import TushareError
from shared.numeric import safe_float

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
PandasDataFrame = Any


class _TushareProClient(Protocol):
    def trade_cal(self, **kwargs: object) -> Any: ...
    def index_weight(self, **kwargs: object) -> Any: ...
    def daily(self, **kwargs: object) -> Any: ...
    def adj_factor(self, **kwargs: object) -> Any: ...
    def index_daily(self, **kwargs: object) -> Any: ...


def _normalize_tushare_code(raw_code: object) -> str | None:
    value = str(raw_code or "").strip().upper()
    return value if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", value) else None


class TushareModelMarketSource:
    """Adapt a configured SDK client; all SDK schemas stay inside Data Center."""

    def __init__(
        self,
        client: object | None = None,
        *,
        source: str = "tushare",
        client_factory: Callable[[], object] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._fetch_workers = 1
        self._source = source

    @property
    def _pro(self) -> _TushareProClient:
        if self._client is None:
            if self._client_factory is None:
                raise ValueError("A configured model-market client is required")
            self._client = self._client_factory()
        return cast(_TushareProClient, self._client)

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Fetch matched raw daily prices and corporate-action factors."""
        daily = self._fetch_stock_daily([asset_code], start_date, end_date)
        if daily.empty:
            return ()
        factors = self._fetch_stock_adj_factor([asset_code], start_date, end_date)
        frame = daily.merge(
            factors[["ts_code", "trade_date", "adj_factor"]],
            on=["ts_code", "trade_date"],
            how="left",
        )
        return self._rows(frame, volume_multiplier=100.0)

    def index_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Fetch index observations without stock corporate-action adjustment."""
        return self._rows(
            self._fetch_index_daily(asset_code, start_date, end_date), volume_multiplier=100.0
        )

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Read the exchange calendar without manufacturing weekdays."""
        return tuple(sorted(set(self._fetch_trade_days(start_date, end_date))))

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        """Read the latest effective snapshot, never a future constituent list."""
        return tuple(
            self._fetch_index_weight_members(
                universe=index_code, index_code=index_code, target_date=target_date
            )
        )

    def _rows(
        self, frame: PandasDataFrame, *, volume_multiplier: float
    ) -> tuple[ModelDailyBar, ...]:
        if frame is None or frame.empty:
            return ()
        rows: list[ModelDailyBar] = []
        for row in (
            frame.sort_values("trade_date")
            .drop_duplicates(["ts_code", "trade_date"], keep="last")
            .to_dict("records")
        ):
            rows.append(
                ModelDailyBar(
                    asset_code=str(row["ts_code"]),
                    trade_date=row["trade_date"].date(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["vol"]) * volume_multiplier,
                    change_percent=float(row["pct_chg"]),
                    adjustment_factor=safe_float(row.get("adj_factor")),
                    source=self._source,
                    amount=(
                        value * 1000.0
                        if (value := safe_float(row.get("amount"))) is not None
                        else None
                    ),
                )
            )
        return tuple(rows)

    def _fetch_trade_days(self, start_date: date, end_date: date) -> list[date]:
        df = self._call_with_retry(
            self._pro.trade_cal,
            exchange="SSE",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            is_open="1",
        )
        if df is None or df.empty:
            return []
        if "cal_date" not in df.columns:
            logger.warning("Invalid trade calendar schema returned by provider")
            return []
        normalized = df.copy()
        normalized["cal_date"] = pd.to_datetime(
            normalized["cal_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        normalized = normalized.loc[
            normalized["cal_date"].notna()
            & (normalized["cal_date"] >= pd.Timestamp(start_date))
            & (normalized["cal_date"] <= pd.Timestamp(end_date))
        ]
        normalized = normalized.sort_values("cal_date")
        return [item.date() for item in normalized["cal_date"].tolist()]

    def _fetch_index_weight_members(
        self,
        *,
        universe: str,
        index_code: str,
        target_date: date,
    ) -> list[str]:
        """Fetch the latest effective constituents for one configured index."""
        try:
            frame = self._call_with_retry(
                self._pro.index_weight,
                index_code=index_code,
                start_date=(target_date - timedelta(days=140)).strftime("%Y%m%d"),
                end_date=target_date.strftime("%Y%m%d"),
            )
        except (PermissionError, TushareError):
            raise
        except Exception as exc:
            logger.warning(
                "Failed to fetch index_weight for %s: %s",
                universe,
                type(exc).__name__,
            )
            return []
        if frame is None or frame.empty:
            logger.warning("No index_weight returned for %s", universe)
            return []
        if not {"trade_date", "con_code"}.issubset(frame.columns):
            logger.warning("Invalid index_weight schema returned for %s", universe)
            return []

        normalized = frame.copy()
        normalized["trade_date"] = pd.to_datetime(
            normalized["trade_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        normalized = normalized.loc[
            normalized["trade_date"].notna()
            & (normalized["trade_date"] <= pd.Timestamp(target_date))
        ]
        if normalized.empty:
            return []
        latest_weight_date = normalized["trade_date"].max()
        members = {
            code
            for raw_code in normalized.loc[
                normalized["trade_date"] == latest_weight_date,
                "con_code",
            ].tolist()
            if (code := _normalize_tushare_code(raw_code)) is not None
        }
        return sorted(members)

    def _fetch_stock_daily(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        def fetch_one(ts_code: str) -> PandasDataFrame | None:
            try:
                df = self._call_with_retry(
                    self._pro.daily,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except (PermissionError, TushareError):
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to fetch daily for %s: %s",
                    ts_code,
                    type(exc).__name__,
                )
                return None
            if df is None or df.empty:
                return None
            normalized = self._normalize_daily_frame(
                df,
                requested_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if normalized.empty:
                return None
            return normalized

        rows = self._fetch_stock_frames(stock_codes, fetch_one)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_stock_adj_factor(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        def fetch_one(ts_code: str) -> PandasDataFrame | None:
            try:
                df = self._call_with_retry(
                    self._pro.adj_factor,
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
            except (PermissionError, TushareError):
                raise
            except Exception as exc:
                logger.warning(
                    "Failed to fetch adj_factor for %s: %s",
                    ts_code,
                    type(exc).__name__,
                )
                return None
            if df is None or df.empty:
                return None
            if not {"ts_code", "trade_date", "adj_factor"}.issubset(df.columns):
                logger.warning("Invalid adj_factor schema returned for %s", ts_code)
                return None
            normalized = df.copy()
            normalized["trade_date"] = pd.to_datetime(
                normalized["trade_date"],
                format="%Y%m%d",
                errors="coerce",
            )
            normalized["adj_factor"] = pd.to_numeric(
                normalized["adj_factor"],
                errors="coerce",
            )
            normalized["ts_code"] = normalized["ts_code"].map(_normalize_tushare_code)
            normalized = normalized.loc[
                normalized["trade_date"].notna()
                & (normalized["trade_date"] >= pd.Timestamp(start_date))
                & (normalized["trade_date"] <= pd.Timestamp(end_date))
                & (normalized["ts_code"] == ts_code)
                & np.isfinite(normalized["adj_factor"])
                & (normalized["adj_factor"] > 0)
            ]
            if normalized.empty:
                return None
            return normalized

        rows = self._fetch_stock_frames(stock_codes, fetch_one)
        if not rows:
            return pd.DataFrame(columns=["ts_code", "trade_date", "adj_factor"])
        return pd.concat(rows, ignore_index=True, sort=False)

    def _fetch_stock_frames(
        self,
        stock_codes: list[str],
        fetch_one: Callable[[str], PandasDataFrame | None],
    ) -> list[PandasDataFrame]:
        """Fetch independent per-stock frames with bounded I/O concurrency."""
        if not stock_codes:
            return []
        stopped = Event()

        def fetch_unless_stopped(ts_code: str) -> PandasDataFrame | None:
            if stopped.is_set():
                return None
            try:
                return fetch_one(ts_code)
            except (PermissionError, TushareError):
                stopped.set()
                raise

        worker_count = min(self._fetch_workers, len(stock_codes))
        if worker_count == 1:
            frames = [fetch_one(ts_code) for ts_code in stock_codes]
        else:
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="qlib-tushare",
            ) as executor:
                frames = list(executor.map(fetch_unless_stopped, stock_codes))
        return [frame for frame in frames if frame is not None and not frame.empty]

    def _fetch_index_daily(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        try:
            df = self._call_with_retry(
                self._pro.index_daily,
                ts_code=index_code,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )
        except (PermissionError, TushareError):
            raise
        except Exception as exc:
            logger.warning(
                "Failed to fetch index_daily for %s: %s",
                index_code,
                type(exc).__name__,
            )
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        return self._normalize_daily_frame(
            df,
            requested_code=index_code,
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def _normalize_daily_frame(
        frame: PandasDataFrame,
        *,
        requested_code: str,
        start_date: date,
        end_date: date,
    ) -> PandasDataFrame:
        """Validate provider daily rows before they affect Qlib availability."""
        required_columns = {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "pct_chg",
        }
        if not required_columns.issubset(frame.columns):
            logger.warning("Invalid daily schema returned for %s", requested_code)
            return pd.DataFrame()

        normalized = frame.copy()
        normalized["ts_code"] = normalized["ts_code"].map(_normalize_tushare_code)
        normalized["trade_date"] = pd.to_datetime(
            normalized["trade_date"],
            format="%Y%m%d",
            errors="coerce",
        )
        numeric_columns = ["open", "high", "low", "close", "vol", "pct_chg"]
        for column in numeric_columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        finite_prices = np.isfinite(normalized[["open", "high", "low", "close"]]).all(axis=1)
        valid_prices = (
            finite_prices
            & (normalized[["open", "high", "low", "close"]] > 0).all(axis=1)
            & (normalized["high"] >= normalized[["open", "low", "close"]].max(axis=1))
            & (normalized["low"] <= normalized[["open", "high", "close"]].min(axis=1))
        )
        valid_volume = np.isfinite(normalized["vol"]) & (normalized["vol"] >= 0)
        valid_change = np.isfinite(normalized["pct_chg"])
        return normalized.loc[
            normalized["trade_date"].notna()
            & (normalized["trade_date"] >= pd.Timestamp(start_date))
            & (normalized["trade_date"] <= pd.Timestamp(end_date))
            & (normalized["ts_code"] == requested_code)
            & valid_prices
            & valid_volume
            & valid_change
        ].copy()

    @staticmethod
    def _call_with_retry(
        func: Callable[..., _T],
        /,
        *args: object,
        retries: int = 3,
        delay_seconds: float = 0.6,
        **kwargs: object,
    ) -> _T:
        if isinstance(retries, bool) or retries <= 0:
            raise ValueError("retries must be a positive integer")
        if not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError("delay_seconds must be finite and non-negative")
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return func(*args, **kwargs)
            except (PermissionError, TushareError):
                raise
            except Exception as exc:  # noqa: BLE001
                if "token daily limit exceeded" in str(exc).casefold():
                    raise TushareError(
                        "Tushare daily quota exhausted; refresh blocked",
                        code="TUSHARE_DAILY_QUOTA_EXHAUSTED",
                    ) from exc
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(delay_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("unexpected retry state")
