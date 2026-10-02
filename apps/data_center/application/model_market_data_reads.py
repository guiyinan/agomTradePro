"""Read-only model-market provider routing and source consistency checks."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import date
from typing import TypeVar

from apps.data_center.application.model_history_preparation import (
    ModelHistoryPreparationAuditPort,
    ModelHistorySingleFetchAuditPort,
)
from apps.data_center.application.model_market_data_state import (
    ModelMarketDataServiceState,
    ModelMarketRoute,
)
from apps.data_center.domain.model_market_data import (
    ModelDailyBar,
    ModelMarketDataPort,
    ModelSuspensionPort,
    TradingCalendarEvidence,
    TradingCalendarEvidencePort,
)
from core.exceptions import DataFetchError, TushareError

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class ModelMarketDataReads(ModelMarketDataServiceState):
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

    def trading_calendar_evidence(
        self, start_date: date, end_date: date
    ) -> TradingCalendarEvidence:
        """Return the exact provider route and requested coverage for calendar data."""

        last_error: DataFetchError | None = None
        for route in self._routes:
            if route.name in self._disabled:
                last_error = self._disabled[route.name]
                continue
            if not isinstance(route.port, TradingCalendarEvidencePort):
                continue
            try:
                evidence = route.port.trading_calendar_evidence(start_date, end_date)
                if (
                    evidence.coverage_start != start_date
                    or evidence.coverage_end != end_date
                    or not evidence.open_sessions
                ):
                    raise DataFetchError(
                        "Trading calendar coverage is incomplete",
                        code="MODEL_MARKET_CALENDAR_COVERAGE_INCOMPLETE",
                    )
                return evidence
            except PermissionError:
                raise
            except DataFetchError as exc:
                last_error = exc
                self._disable_quota(route, exc)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Trading calendar route %s failed: %s", route.name, type(exc).__name__
                )
        raise last_error or DataFetchError(
            "No trading calendar evidence available",
            code="MODEL_MARKET_CALENDAR_UNAVAILABLE",
        )

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
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
        *,
        is_index: bool,
        audit_fetch: bool = False,
        skip_routes: frozenset[str] = frozenset(),
        allow_per_asset_fetch: bool = False,
    ) -> tuple[ModelDailyBar, ...]:
        if start_date > end_date:
            raise ValueError("History start_date must not exceed end_date")
        reference: tuple[ModelDailyBar, ...] = ()
        last_error: DataFetchError | None = None
        suspended: dict[str, str] | None = None
        full_interval_suspension = False
        observed_history = False
        suspension_conflict: DataFetchError | None = None
        for index, route in enumerate(self._routes):
            if route.name in skip_routes:
                continue
            if route.name in self._disabled:
                last_error = self._disabled[route.name]
                continue
            cache_port = (
                route.port if isinstance(route.port, ModelHistoryPreparationAuditPort) else None
            )
            is_prepared_cache = (
                cache_port.has_prepared_model_history(asset_code, start_date, end_date)
                if cache_port is not None
                else False
            )
            if audit_fetch and not is_prepared_cache and not allow_per_asset_fetch:
                last_error = DataFetchError(
                    "Per-asset model-history fetch requires an explicit configured limit",
                    code="MODEL_MARKET_BULK_PREPARATION_REQUIRED",
                )
                continue
            if (
                audit_fetch
                and not is_prepared_cache
                and not isinstance(route.port, ModelHistorySingleFetchAuditPort)
            ):
                last_error = DataFetchError(
                    "Provider route does not expose an auditable per-asset fetch",
                    code="MODEL_MARKET_BULK_PREPARATION_REQUIRED",
                )
                continue
            fetch_persistence_started = False
            fetch_audit_written = False
            try:
                if audit_fetch and not is_prepared_cache:
                    single_fetch_port: object = route.port
                    if not isinstance(single_fetch_port, ModelHistorySingleFetchAuditPort):
                        raise DataFetchError(
                            "Provider route does not expose an auditable per-asset fetch",
                            code="MODEL_MARKET_BULK_PREPARATION_REQUIRED",
                        )
                    fetch = single_fetch_port.fetch_stock_history(asset_code, start_date, end_date)
                    fetch_persistence_started = True
                    audit_reference = self._persist_prepared_fetch(
                        route,
                        fetch,
                        requested_asset_codes=(asset_code,),
                        snapshot=self._reference_snapshot_for((asset_code,), start_date, end_date),
                    )
                    self._bind_history_rows(fetch.rows, audit_reference)
                    fetch_audit_written = True
                    rows = fetch.rows
                else:
                    read = route.port.index_history if is_index else route.port.stock_history
                    rows = read(asset_code, start_date, end_date)
                if not rows:
                    if (
                        not is_index
                        and not is_prepared_cache
                        and audit_fetch
                        and not fetch_audit_written
                    ):
                        self._record_history_fetch_success(
                            route,
                            (),
                            asset_code=asset_code,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    last_error = DataFetchError(
                        "No model market history available", code="MODEL_MARKET_UNAVAILABLE"
                    )
                    if not is_index and isinstance(route.port, ModelSuspensionPort):
                        calendar = self.trade_days(start_date, end_date)
                        if calendar:
                            calendar_sessions = set(calendar)
                            evidence = set(
                                route.port.suspended_days(asset_code, min(calendar), max(calendar))
                            )
                            if calendar_sessions <= evidence and not observed_history:
                                persisted = self._reference_history_for(
                                    asset_code, start_date, end_date
                                )
                                if any(row.trade_date in calendar_sessions for row in persisted):
                                    suspension_conflict = DataFetchError(
                                        "Persisted history conflicts with full-interval suspension",
                                        code="MODEL_MARKET_SOURCE_CONFLICT",
                                    )
                                else:
                                    suspended = {
                                        "asset_code": asset_code,
                                        "suspended_through": max(calendar).isoformat(),
                                        "source": route.source_type,
                                    }
                                    full_interval_suspension = True
                    continue
                self._validate(rows, asset_code, start_date, end_date, is_index=is_index)
                observed_history = True
                if full_interval_suspension:
                    suspended = None
                    full_interval_suspension = False
                calendar = self.trade_days(start_date, end_date)
                if max(row.trade_date for row in rows) < max(calendar):
                    reference = rows
                    last_error = DataFetchError(
                        "Source observations are stale", code="MODEL_MARKET_STALE"
                    )
                    suspension_proven = False
                    if not is_index and isinstance(route.port, ModelSuspensionPort):
                        latest = max(row.trade_date for row in rows)
                        missing = {day for day in calendar if day > latest}
                        evidence = set(
                            route.port.suspended_days(asset_code, min(missing), end_date)
                        )
                        if missing <= evidence:
                            persisted = self._reference_history_for(
                                asset_code, start_date, end_date
                            )
                            if (
                                index
                                or route.requires_reference
                                or any(row.source != rows[0].source for row in persisted)
                            ):
                                self._check_consistency(persisted, rows)
                            suspended = {
                                "asset_code": asset_code,
                                "last_observed_date": latest.isoformat(),
                                "suspended_through": max(calendar).isoformat(),
                                "source": route.source_type,
                            }
                            suspension_proven = True
                    if not is_index and audit_fetch:
                        if suspension_proven:
                            self._record_history_fetch_success(
                                route,
                                rows,
                                asset_code=asset_code,
                                start_date=start_date,
                                end_date=end_date,
                                cache_port=cache_port,
                            )
                        elif not is_prepared_cache and not fetch_audit_written:
                            self._record_history_fetch_failure(
                                route,
                                asset_codes=(asset_code,),
                                start_date=start_date,
                                end_date=end_date,
                                error=last_error,
                            )
                    continue
                persisted_reference = self._reference_history_for(asset_code, start_date, end_date)
                source_changed = any(row.source != rows[0].source for row in persisted_reference)
                if index or route.requires_reference or source_changed:
                    reference = reference or persisted_reference
                    self._check_consistency(reference, rows)
                if suspension_conflict is not None:
                    if (
                        not is_index
                        and not is_prepared_cache
                        and audit_fetch
                        and not fetch_audit_written
                    ):
                        self._record_history_fetch_failure(
                            route,
                            asset_codes=(asset_code,),
                            start_date=start_date,
                            end_date=end_date,
                            error=suspension_conflict,
                        )
                    continue
                if not is_index and audit_fetch and not fetch_audit_written:
                    self._record_history_fetch_success(
                        route,
                        rows,
                        asset_code=asset_code,
                        start_date=start_date,
                        end_date=end_date,
                        cache_port=cache_port,
                    )
                return tuple(sorted(rows, key=lambda row: row.trade_date))
            except PermissionError as exc:
                if (
                    not is_index
                    and not is_prepared_cache
                    and audit_fetch
                    and not fetch_persistence_started
                ):
                    self._record_history_fetch_failure(
                        route,
                        asset_codes=(asset_code,),
                        start_date=start_date,
                        end_date=end_date,
                        error=exc,
                    )
                raise
            except DataFetchError as exc:
                if (
                    not is_index
                    and not is_prepared_cache
                    and audit_fetch
                    and not fetch_persistence_started
                ):
                    self._record_history_fetch_failure(
                        route,
                        asset_codes=(asset_code,),
                        start_date=start_date,
                        end_date=end_date,
                        error=exc,
                    )
                last_error = exc
                if exc.code in {"MODEL_MARKET_SOURCE_CONFLICT", "MODEL_MARKET_INVALID"}:
                    suspension_conflict = exc
                self._disable_quota(route, exc)
                logger.warning("Model market route %s rejected: %s", route.name, exc.code)
            except Exception as exc:
                if (
                    not is_index
                    and not is_prepared_cache
                    and audit_fetch
                    and not fetch_persistence_started
                ):
                    self._record_history_fetch_failure(
                        route,
                        asset_codes=(asset_code,),
                        start_date=start_date,
                        end_date=end_date,
                        error=exc,
                    )
                logger.warning("Model market route %s failed: %s", route.name, type(exc).__name__)
        if suspended is not None and suspension_conflict is None:
            raise DataFetchError(
                "No current observation: verified full-day suspension",
                code="MODEL_MARKET_SUSPENDED",
                details=suspended,
            )
        if suspension_conflict is not None:
            raise suspension_conflict
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
