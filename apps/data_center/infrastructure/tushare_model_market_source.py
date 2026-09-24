"""Tushare normalization behind the Data Center model-market contract."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Event
from typing import Any, Protocol, TypeVar, cast

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from apps.data_center.domain.model_market_data import ModelDailyBar, TradingCalendarEvidence
from core.exceptions import DataFetchError, TushareError
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
    def suspend_d(self, **kwargs: object) -> Any: ...


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
        self._prepared: dict[tuple[str, date, date], tuple[ModelDailyBar, ...]] = {}

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
        key = (asset_code, start_date, end_date)
        if key in self._prepared:
            return self._prepared[key]
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

    def prepare_stock_history(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> None:
        """Batch comma-separated symbols below the provider row limit for an exact window."""
        if start_date > end_date or any(
            _normalize_tushare_code(code) != code for code in asset_codes
        ):
            raise ValueError("Invalid history preparation scope")
        self._prepared.clear()
        if len(asset_codes) > max(200, (end_date - start_date).days):
            if self._prepare_by_session(asset_codes, start_date, end_date):
                return
        # Calendar days bound trading rows conservatively; retain headroom below 6000 rows.
        batch_size = max(1, min(50, 4800 // ((end_date - start_date).days + 1)))
        codes = tuple(sorted(set(asset_codes)))
        for offset in range(0, len(codes), batch_size):
            batch = codes[offset : offset + batch_size]
            params = {
                "ts_code": ",".join(batch),
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            }
            daily = self._call_with_retry(
                self._pro.daily,
                ts_code=params["ts_code"],
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
            factors = self._call_with_retry(
                self._pro.adj_factor,
                ts_code=params["ts_code"],
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
            if daily is None or factors is None:
                continue
            if len(daily) >= 4800 or len(factors) >= 4800:
                continue  # Fall back to per-symbol requests when completeness is uncertain.
            required = {"ts_code", "trade_date", "adj_factor"}
            if not required.issubset(factors.columns) or "ts_code" not in daily.columns:
                continue
            factor_frame = factors.copy()
            factor_frame["trade_date"] = pd.to_datetime(
                factor_frame["trade_date"], format="%Y%m%d", errors="coerce"
            )
            factor_frame["adj_factor"] = pd.to_numeric(factor_frame["adj_factor"], errors="coerce")
            if factor_frame.duplicated(["ts_code", "trade_date"]).any():
                continue
            for code in batch:
                normalized = self._normalize_daily_frame(
                    daily.loc[daily["ts_code"] == code],
                    requested_code=code,
                    start_date=start_date,
                    end_date=end_date,
                )
                if normalized.empty:
                    continue  # Empty batch members need an individual request before failover.
                joined = normalized.merge(
                    factor_frame.loc[factor_frame["ts_code"] == code, list(required)],
                    on=["ts_code", "trade_date"],
                    how="left",
                    validate="many_to_one",
                )
                self._prepared[(code, start_date, end_date)] = self._rows(
                    joined, volume_multiplier=100.0
                )
            logger.info(
                "Model history prepared: source=%s assets=%d/%d",
                self._source,
                offset + len(batch),
                len(codes),
            )

    def _prepare_by_session(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> bool:
        """Use bounded daily market snapshots when a scope is wider than its time window."""
        days = self.trade_days(start_date, end_date)
        if not days:
            return False
        client = self._pro

        def fetch(day: date) -> tuple[PandasDataFrame, PandasDataFrame]:
            daily = self._call_with_retry(client.daily, trade_date=day.strftime("%Y%m%d"))
            factors = self._call_with_retry(client.adj_factor, trade_date=day.strftime("%Y%m%d"))
            return daily, factors

        daily_frames: list[PandasDataFrame] = []
        factor_frames: list[PandasDataFrame] = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            for day, (daily, factors) in zip(days, executor.map(fetch, days), strict=True):
                if (
                    daily is None
                    or factors is None
                    or daily.empty
                    or factors.empty
                    or len(daily) >= 6000
                    or len(factors) >= 6000
                    or not {"ts_code", "trade_date"}.issubset(daily.columns)
                    or not {"ts_code", "trade_date", "adj_factor"}.issubset(factors.columns)
                ):
                    return False
                # Reject an endpoint that ignored the single-session parameter.
                if any(str(value) != day.strftime("%Y%m%d") for value in daily["trade_date"]):
                    return False
                if any(str(value) != day.strftime("%Y%m%d") for value in factors["trade_date"]):
                    return False
                daily_frames.append(daily.loc[daily["ts_code"].isin(asset_codes)])
                factor_frames.append(factors.loc[factors["ts_code"].isin(asset_codes)])
                logger.info("Model market session prepared: %s %s", self._source, day)
        daily_frame = pd.concat(daily_frames, ignore_index=True)
        factor_frame = pd.concat(factor_frames, ignore_index=True)
        if factor_frame.duplicated(["ts_code", "trade_date"]).any():
            return False
        factor_frame["trade_date"] = pd.to_datetime(
            factor_frame["trade_date"], format="%Y%m%d", errors="coerce"
        )
        factor_frame["adj_factor"] = pd.to_numeric(factor_frame["adj_factor"], errors="coerce")
        factor_groups = dict(iter(factor_frame.groupby("ts_code")))
        for code, frame in daily_frame.groupby("ts_code"):
            normalized = self._normalize_daily_frame(
                frame, requested_code=str(code), start_date=start_date, end_date=end_date
            )
            factors = factor_groups.get(code)
            if normalized.empty or factors is None:
                continue
            joined = normalized.merge(
                factors[["ts_code", "trade_date", "adj_factor"]],
                on=["ts_code", "trade_date"],
                how="left",
                validate="many_to_one",
            )
            self._prepared[(str(code), start_date, end_date)] = self._rows(
                joined, volume_multiplier=100.0
            )
        return True

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

    def trading_calendar_evidence(
        self, start_date: date, end_date: date
    ) -> TradingCalendarEvidence:
        """Fetch every calendar member and reject truncated or conflicting coverage."""

        if start_date > end_date:
            raise ValueError("Trading calendar start_date must not exceed end_date")
        frame = self._call_with_retry(
            self._pro.trade_cal,
            exchange="SSE",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if frame is None or frame.empty or not {"cal_date", "is_open"}.issubset(frame.columns):
            raise DataFetchError(
                "Trading calendar schema is incomplete",
                code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID",
            )
        states: dict[date, bool] = {}
        for row in frame.to_dict("records"):
            parsed = pd.to_datetime(row.get("cal_date"), format="%Y%m%d", errors="coerce")
            if pd.isna(parsed):
                raise DataFetchError(
                    "Trading calendar date is invalid",
                    code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID",
                )
            calendar_date = parsed.date()
            if not start_date <= calendar_date <= end_date:
                continue
            state_value = row.get("is_open")
            raw_state = "" if state_value is None else str(state_value).strip().lower()
            if raw_state not in {"0", "0.0", "false", "1", "1.0", "true"}:
                raise DataFetchError(
                    "Trading calendar state is invalid",
                    code="MODEL_MARKET_CALENDAR_SCHEMA_INVALID",
                )
            is_open = raw_state in {"1", "1.0", "true"}
            if calendar_date in states and states[calendar_date] != is_open:
                raise DataFetchError(
                    "Trading calendar contains conflicting states",
                    code="MODEL_MARKET_CALENDAR_CONFLICT",
                )
            states[calendar_date] = is_open
        expected_dates: set[date] = set()
        current = start_date
        while current <= end_date:
            expected_dates.add(current)
            current += timedelta(days=1)
        if set(states) != expected_dates:
            raise DataFetchError(
                "Trading calendar coverage is incomplete",
                code="MODEL_MARKET_CALENDAR_COVERAGE_INCOMPLETE",
            )
        return TradingCalendarEvidence(
            coverage_start=start_date,
            coverage_end=end_date,
            open_sessions=tuple(day for day in sorted(states) if states[day]),
            source=self._source,
            observed_at=datetime.now(UTC),
        )

    def suspended_days(self, asset_code: str, start_date: date, end_date: date) -> tuple[date, ...]:
        """Accept only explicit full-day S records; intraday halts do not explain gaps."""
        frame = self._call_with_retry(
            self._pro.suspend_d,
            ts_code=asset_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            suspend_type="S",
        )
        if frame is None or frame.empty:
            return ()
        required = {"ts_code", "trade_date", "suspend_type", "suspend_timing"}
        if not required.issubset(frame.columns):
            return ()
        days: set[date] = set()
        for row in frame.to_dict("records"):
            if row["ts_code"] != asset_code or row["suspend_type"] != "S":
                continue
            timing = row["suspend_timing"]
            if timing is not None and not pd.isna(timing) and str(timing).strip():
                continue
            observed = pd.to_datetime(row["trade_date"], format="%Y%m%d", errors="coerce")
            if pd.notna(observed) and start_date <= observed.date() <= end_date:
                days.add(observed.date())
        return tuple(sorted(days))

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
            except DataFetchError as exc:
                # The routed provider transport already spent its shared
                # direct/fallback budget.  Retrying here would multiply the
                # egress attempts and could rotate a route twice.
                if str(getattr(exc, "code", "")).startswith("EGRESS_"):
                    raise
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(delay_seconds * attempt)
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
