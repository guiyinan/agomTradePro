"""On-demand data hydration and quality gates for Data Center facts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

from django.utils import timezone

from apps.data_center.application.dtos import (
    SyncFinancialRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncValuationRequest,
)
from apps.data_center.domain.entities import (
    FinancialFact,
    PriceBar,
    QuoteSnapshot,
    ValuationFact,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
QualityStatus = str


@dataclass(frozen=True)
class DataQualityReport:
    """Small quality summary attached to on-demand Data Center reads."""

    status: QualityStatus
    source: str | None = None
    fetched_at: datetime | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    points_count: int = 0
    errors: tuple[str, ...] = ()
    hydrated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "points_count": self.points_count,
            "errors": list(self.errors),
            "hydrated": self.hydrated,
        }


@dataclass(frozen=True)
class EnsureDataResult(Generic[T]):
    """Result of an on-demand Data Center read-through operation."""

    asset_code: str
    records: list[T]
    quality: DataQualityReport


@dataclass(frozen=True)
class EnsurePolicy:
    """Quality thresholds for a single-asset read."""

    stale_days: int
    min_points: int


class OnDemandDataCenterService:
    """Read-through facade for single-asset data required by interactive pages."""

    def __init__(
        self,
        *,
        price_repo,
        valuation_repo,
        financial_repo,
        quote_repo,
        sync_price_use_case,
        sync_valuation_use_case,
        sync_financial_use_case,
        sync_quote_use_case,
        provider_id_resolver: Callable[[str], int | None],
    ) -> None:
        self._price_repo = price_repo
        self._valuation_repo = valuation_repo
        self._financial_repo = financial_repo
        self._quote_repo = quote_repo
        self._sync_price = sync_price_use_case
        self._sync_valuation = sync_valuation_use_case
        self._sync_financial = sync_financial_use_case
        self._sync_quote = sync_quote_use_case
        self._provider_id_resolver = provider_id_resolver

    def ensure_price_bars(
        self,
        asset_code: str,
        start: date,
        end: date,
        frequency: str = "1d",
    ) -> EnsureDataResult[PriceBar]:
        policy = EnsurePolicy(
            stale_days=10,
            min_points=_minimum_points_for_window(start, end),
        )
        bars = self._query_price_bars(asset_code, start, end, frequency)
        quality = self._quality_for_dated_records(
            bars,
            date_getter=lambda item: item.bar_date,
            policy=policy,
            expected_end=end,
        )
        if quality.status in {"fresh"}:
            return EnsureDataResult(asset_code, bars, quality)

        errors = self._sync_sources(
            ("tushare", "akshare"),
            lambda provider_id: self._sync_price.execute(
                SyncPriceRequest(
                    provider_id=provider_id,
                    asset_code=asset_code,
                    start=start,
                    end=end,
                )
            ),
        )
        refreshed = self._query_price_bars(asset_code, start, end, frequency)
        refreshed_quality = self._quality_for_dated_records(
            refreshed,
            date_getter=lambda item: item.bar_date,
            policy=policy,
            expected_end=end,
            hydrated=True,
            errors=errors,
        )
        return EnsureDataResult(asset_code, refreshed, refreshed_quality)

    def ensure_valuations(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> EnsureDataResult[ValuationFact]:
        policy = EnsurePolicy(
            stale_days=10,
            min_points=_minimum_points_for_window(start, end),
        )
        facts = self._query_valuations(asset_code, start, end)
        quality = self._quality_for_dated_records(
            facts,
            date_getter=lambda item: item.val_date,
            policy=policy,
            expected_end=end,
        )
        if quality.status == "fresh":
            return EnsureDataResult(asset_code, facts, quality)

        errors = self._sync_sources(
            ("tushare", "akshare"),
            lambda provider_id: self._sync_valuation.execute(
                SyncValuationRequest(
                    provider_id=provider_id,
                    asset_code=asset_code,
                    start=start,
                    end=end,
                )
            ),
        )
        refreshed = self._query_valuations(asset_code, start, end)
        refreshed_quality = self._quality_for_dated_records(
            refreshed,
            date_getter=lambda item: item.val_date,
            policy=policy,
            expected_end=end,
            hydrated=True,
            errors=errors,
        )
        return EnsureDataResult(asset_code, refreshed, refreshed_quality)

    def ensure_financials(
        self,
        asset_code: str,
        periods: int = 8,
    ) -> EnsureDataResult[FinancialFact]:
        facts = self._query_financials(asset_code, periods)
        quality = self._quality_for_dated_records(
            facts,
            date_getter=lambda item: item.period_end,
            policy=EnsurePolicy(stale_days=370, min_points=max(periods, 1)),
            expected_end=timezone.localdate(),
        )
        if quality.status == "fresh":
            return EnsureDataResult(asset_code, facts, quality)

        errors = self._sync_sources(
            ("akshare", "tushare"),
            lambda provider_id: self._sync_financial.execute(
                SyncFinancialRequest(
                    provider_id=provider_id,
                    asset_code=asset_code,
                    periods=periods,
                )
            ),
        )
        refreshed = self._query_financials(asset_code, periods)
        refreshed_quality = self._quality_for_dated_records(
            refreshed,
            date_getter=lambda item: item.period_end,
            policy=EnsurePolicy(stale_days=370, min_points=max(periods, 1)),
            expected_end=timezone.localdate(),
            hydrated=True,
            errors=errors,
        )
        return EnsureDataResult(asset_code, refreshed, refreshed_quality)

    def ensure_intraday(self, asset_code: str) -> EnsureDataResult[QuoteSnapshot]:
        quotes = self._query_quotes(asset_code)
        quality = self._quote_quality(quotes)
        if quality.status == "fresh":
            return EnsureDataResult(asset_code, quotes, quality)

        errors = self._sync_sources(
            ("akshare",),
            lambda provider_id: self._sync_quote.execute(
                SyncQuoteRequest(provider_id=provider_id, asset_codes=[asset_code])
            ),
        )
        refreshed = self._query_quotes(asset_code)
        refreshed_quality = self._quote_quality(refreshed, hydrated=True, errors=errors)
        return EnsureDataResult(asset_code, refreshed, refreshed_quality)

    def assess_price_bars(
        self,
        asset_code: str,
        start: date,
        end: date,
        frequency: str = "1d",
    ) -> EnsureDataResult[PriceBar]:
        bars = self._query_price_bars(asset_code, start, end, frequency)
        quality = self._quality_for_dated_records(
            bars,
            date_getter=lambda item: item.bar_date,
            policy=EnsurePolicy(10, _minimum_points_for_window(start, end)),
            expected_end=end,
        )
        return EnsureDataResult(asset_code, bars, quality)

    def assess_valuations(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> EnsureDataResult[ValuationFact]:
        facts = self._query_valuations(asset_code, start, end)
        quality = self._quality_for_dated_records(
            facts,
            date_getter=lambda item: item.val_date,
            policy=EnsurePolicy(10, _minimum_points_for_window(start, end)),
            expected_end=end,
        )
        return EnsureDataResult(asset_code, facts, quality)

    def assess_financials(self, asset_code: str, periods: int = 8) -> EnsureDataResult[FinancialFact]:
        facts = self._query_financials(asset_code, periods)
        quality = self._quality_for_dated_records(
            facts,
            date_getter=lambda item: item.period_end,
            policy=EnsurePolicy(370, max(periods, 1)),
            expected_end=timezone.localdate(),
        )
        return EnsureDataResult(asset_code, facts, quality)

    def assess_intraday(self, asset_code: str) -> EnsureDataResult[QuoteSnapshot]:
        quotes = self._query_quotes(asset_code)
        return EnsureDataResult(asset_code, quotes, self._quote_quality(quotes))

    def _query_price_bars(
        self,
        asset_code: str,
        start: date,
        end: date,
        frequency: str,
    ) -> list[PriceBar]:
        limit = max((end - start).days + 10, 120)
        bars = self._price_repo.get_bars(asset_code, start=start, end=end, limit=limit)
        return sorted((bar for bar in bars if bar.freq == frequency), key=lambda item: item.bar_date)

    def _query_valuations(
        self,
        asset_code: str,
        start: date,
        end: date,
    ) -> list[ValuationFact]:
        facts = self._valuation_repo.get_series(asset_code, start=start, end=end)
        return sorted(facts, key=lambda item: item.val_date)

    def _query_financials(self, asset_code: str, periods: int) -> list[FinancialFact]:
        return self._financial_repo.get_facts(asset_code, limit=max(periods * 12, 40))

    def _query_quotes(self, asset_code: str) -> list[QuoteSnapshot]:
        quotes = self._quote_repo.get_series(asset_code, limit=600)
        return sorted(quotes, key=lambda item: item.snapshot_at)

    def _sync_sources(
        self,
        source_order: tuple[str, ...],
        sync_call: Callable[[int], object],
    ) -> tuple[str, ...]:
        errors: list[str] = []
        for source in source_order:
            provider_id = self._provider_id_resolver(source)
            if provider_id is None:
                errors.append(f"{source}: provider not active")
                continue
            try:
                result = sync_call(provider_id)
                stored_count = getattr(result, "stored_count", 0)
                if stored_count > 0:
                    return tuple(errors)
                errors.append(f"{source}: no records")
            except Exception as exc:
                logger.warning("On-demand Data Center sync failed via %s: %s", source, exc)
                errors.append(f"{source}: {exc}")
        return tuple(errors)

    def _quality_for_dated_records(
        self,
        records: list[T],
        *,
        date_getter: Callable[[T], date],
        policy: EnsurePolicy,
        expected_end: date,
        hydrated: bool = False,
        errors: tuple[str, ...] = (),
    ) -> DataQualityReport:
        if not records:
            status = "provider_failed" if hydrated and errors else "missing"
            return DataQualityReport(status=status, errors=errors, hydrated=hydrated)

        dates = [date_getter(item) for item in records]
        coverage_start = min(dates)
        coverage_end = max(dates)
        latest_item = max(records, key=date_getter)
        source = str(getattr(latest_item, "source", "") or "") or None
        fetched_at = getattr(latest_item, "fetched_at", None)
        age_days = max((min(expected_end, timezone.localdate()) - coverage_end).days, 0)

        if len(records) < policy.min_points:
            status = "sparse"
        elif age_days > policy.stale_days:
            status = "stale"
        else:
            status = "fresh"

        return DataQualityReport(
            status=status,
            source=source,
            fetched_at=fetched_at,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            points_count=len(records),
            errors=errors,
            hydrated=hydrated,
        )

    def _quote_quality(
        self,
        quotes: list[QuoteSnapshot],
        *,
        hydrated: bool = False,
        errors: tuple[str, ...] = (),
    ) -> DataQualityReport:
        if not quotes:
            status = "provider_failed" if hydrated and errors else "missing"
            return DataQualityReport(status=status, errors=errors, hydrated=hydrated)

        latest = quotes[-1]
        market_tz = timezone.get_current_timezone()
        latest_date = latest.snapshot_at.astimezone(market_tz).date()
        age_days = max((timezone.localdate() - latest_date).days, 0)
        same_session_count = sum(
            1 for quote in quotes if quote.snapshot_at.astimezone(market_tz).date() == latest_date
        )
        if same_session_count < 3:
            status = "sparse"
        elif age_days > 5:
            status = "stale"
        else:
            status = "fresh"

        return DataQualityReport(
            status=status,
            source=latest.source or None,
            fetched_at=latest.snapshot_at,
            coverage_start=latest_date,
            coverage_end=latest_date,
            points_count=same_session_count,
            errors=errors,
            hydrated=hydrated,
        )


def _minimum_points_for_window(start: date, end: date) -> int:
    calendar_days = max((end - start).days + 1, 1)
    if calendar_days <= 45:
        return 1
    expected_trading_days = max(int(calendar_days * 0.55), 1)
    return min(60, max(8, expected_trading_days // 4))
