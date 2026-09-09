"""Data Center owns model-market routing, freshness and source consistency."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import TypeVar

from apps.data_center.domain.model_market_data import ModelDailyBar, ModelMarketDataPort
from core.exceptions import DataFetchError, TushareError

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass(frozen=True)
class ModelMarketRoute:
    """One configured, capability-qualified Data Center provider route."""

    name: str
    port: ModelMarketDataPort
    requires_reference: bool = False


class ModelMarketDataService:
    """Expose normalized inputs while keeping all source decisions in Data Center."""

    def __init__(
        self,
        routes: tuple[ModelMarketRoute, ...],
        *,
        enable_failover: bool,
        tolerance: float,
        reference_history: Callable[[str, date, date], tuple[ModelDailyBar, ...]],
        store_history: Callable[[tuple[ModelDailyBar, ...]], None] | None = None,
    ) -> None:
        if not math.isfinite(tolerance) or not 0 <= tolerance <= 1:
            raise ValueError("Invalid source consistency tolerance")
        self._routes = routes if enable_failover else routes[:1]
        self._tolerance = tolerance
        self._reference_history = reference_history
        self._store_history = store_history
        self._calendar_cache: dict[tuple[date, date], tuple[date, ...]] = {}
        self._calendar_lock = Lock()
        self._disabled: dict[str, DataFetchError] = {}
        self._lock = Lock()

    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Read raw prices and factors together; stale results continue failover."""
        return self._history(asset_code, start_date, end_date, is_index=False)

    def index_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Read unadjusted index observations through the same routing policy."""
        return self._history(asset_code, start_date, end_date, is_index=True)

    def trade_days(self, start_date: date, end_date: date) -> tuple[date, ...]:
        """Return exchange dates, without substituting a weekday calendar."""
        with self._calendar_lock:
            key = (start_date, end_date)
            if key not in self._calendar_cache:
                self._calendar_cache[key] = self._lookup(
                    lambda port: port.trade_days(start_date, end_date)
                )
            return self._calendar_cache[key]

    def index_members(self, index_code: str, target_date: date) -> tuple[str, ...]:
        """Resolve historical membership inside Data Center."""
        return self._lookup(lambda port: port.index_members(index_code, target_date))

    def _lookup(self, read: Callable[[ModelMarketDataPort], tuple[_T, ...]]) -> tuple[_T, ...]:
        last_error: DataFetchError | None = None
        for route in self._routes:
            if route.name in self._disabled:
                last_error = self._disabled[route.name]
                continue
            try:
                result = read(route.port)
                if result:
                    return result
            except PermissionError:
                raise
            except DataFetchError as exc:
                last_error = exc
                self._disable_quota(route, exc)
            except Exception as exc:
                logger.warning("Model market route %s failed: %s", route.name, type(exc).__name__)
        raise last_error or DataFetchError(
            "No model market data available", code="MODEL_MARKET_UNAVAILABLE"
        )

    def _disable_quota(self, route: ModelMarketRoute, exc: DataFetchError) -> None:
        if isinstance(exc, TushareError) and exc.code == "TUSHARE_DAILY_QUOTA_EXHAUSTED":
            with self._lock:
                self._disabled[route.name] = exc

    def _history(
        self, asset_code: str, start_date: date, end_date: date, *, is_index: bool
    ) -> tuple[ModelDailyBar, ...]:
        if start_date > end_date:
            raise ValueError("History start_date must not exceed end_date")
        reference: tuple[ModelDailyBar, ...] = ()
        last_error: DataFetchError | None = None
        for index, route in enumerate(self._routes):
            if route.name in self._disabled:
                last_error = self._disabled[route.name]
                continue
            try:
                read = route.port.index_history if is_index else route.port.stock_history
                rows = read(asset_code, start_date, end_date)
                if not rows:
                    continue
                self._validate(rows, asset_code, start_date, end_date, is_index=is_index)
                calendar = self.trade_days(start_date, end_date)
                if max(row.trade_date for row in rows) < max(calendar):
                    reference = rows
                    last_error = DataFetchError(
                        "Source observations are stale", code="MODEL_MARKET_STALE"
                    )
                    continue
                persisted_reference = self._reference_history(asset_code, start_date, end_date)
                source_changed = any(row.source != rows[0].source for row in persisted_reference)
                if index or route.requires_reference or source_changed:
                    reference = reference or persisted_reference
                    self._check_consistency(reference, rows)
                if self._store_history is not None:
                    self._store_history(rows)
                return tuple(sorted(rows, key=lambda row: row.trade_date))
            except PermissionError:
                raise
            except DataFetchError as exc:
                last_error = exc
                self._disable_quota(route, exc)
                logger.warning("Model market route %s rejected: %s", route.name, exc.code)
            except Exception as exc:
                logger.warning("Model market route %s failed: %s", route.name, type(exc).__name__)
        raise last_error or DataFetchError(
            "No model market history available", code="MODEL_MARKET_UNAVAILABLE"
        )

    @staticmethod
    def _validate(
        rows: tuple[ModelDailyBar, ...], asset_code: str, start: date, end: date, *, is_index: bool
    ) -> None:
        seen: set[date] = set()
        for row in rows:
            prices = (row.open, row.high, row.low, row.close)
            if (
                row.asset_code != asset_code
                or not start <= row.trade_date <= end
                or row.trade_date in seen
                or not row.source
                or row.source != rows[0].source
                or any(not math.isfinite(value) or value <= 0 for value in prices)
                or row.high < max(prices)
                or row.low > min(prices)
                or not math.isfinite(row.volume)
                or row.volume < 0
                or not math.isfinite(row.change_percent)
                or (
                    not is_index
                    and (
                        row.adjustment_factor is None
                        or not math.isfinite(row.adjustment_factor)
                        or row.adjustment_factor <= 0
                    )
                )
            ):
                raise DataFetchError(
                    "Invalid normalized model history", code="MODEL_MARKET_INVALID"
                )
            seen.add(row.trade_date)

    def _check_consistency(
        self, reference: tuple[ModelDailyBar, ...], candidate: tuple[ModelDailyBar, ...]
    ) -> None:
        prior = {row.trade_date: row for row in reference}
        pairs = [(prior[row.trade_date], row) for row in candidate if row.trade_date in prior]
        if not pairs:
            raise DataFetchError(
                "No overlap to verify source switch", code="MODEL_MARKET_UNVERIFIED_FAILOVER"
            )
        for left, right in pairs:
            for old, new in zip(
                (left.open, left.high, left.low, left.close),
                (right.open, right.high, right.low, right.close),
                strict=True,
            ):
                if not math.isfinite(old) or old <= 0 or abs(new / old - 1) > self._tolerance:
                    raise DataFetchError(
                        "Source prices disagree", code="MODEL_MARKET_SOURCE_CONFLICT"
                    )
            if (
                not math.isfinite(left.volume)
                or left.volume < 0
                or (left.volume == 0 and right.volume != 0)
                or (left.volume > 0 and abs(right.volume / left.volume - 1) > self._tolerance)
            ):
                raise DataFetchError("Source volumes disagree", code="MODEL_MARKET_SOURCE_CONFLICT")
        factor_pairs = [
            (a.adjustment_factor, b.adjustment_factor)
            for a, b in pairs
            if a.adjustment_factor is not None and b.adjustment_factor is not None
        ]
        if factor_pairs:
            anchor_old, anchor_new = factor_pairs[0]
            assert anchor_old is not None and anchor_new is not None
            for old_factor, new_factor in factor_pairs:
                assert old_factor is not None and new_factor is not None
                ratio = (new_factor / anchor_new) / (old_factor / anchor_old)
                if abs(ratio - 1) > self._tolerance:
                    raise DataFetchError(
                        "Source adjustments disagree", code="MODEL_MARKET_SOURCE_CONFLICT"
                    )
