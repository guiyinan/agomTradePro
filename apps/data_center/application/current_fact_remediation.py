"""Fail-closed repair use cases for decision-current A-share facts."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from apps.data_center.domain.entities import PriceBar, QuoteSnapshot

from .current_publication_rebuild import (
    CoreCurrentPublicationPreview,
    CoreCurrentPublicationRebuildResult,
    CoreCurrentPublicationRebuildUseCase,
)
from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .dtos import SyncFinancialRequest, SyncPriceRequest, SyncQuoteRequest
from .sync_market_use_cases import SyncPriceUseCase, SyncQuoteUseCase
from .sync_use_cases import SyncFinancialUseCase

CN_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
CN_MARKET_CLOSE = time(15, 0)
_EVIDENCE_ASSET_CODE_LIMIT = 20


@dataclass(frozen=True)
class FinancialAvailabilityBackfillPreview:
    """Bounded evidence for facts whose source report date can restore availability."""

    missing_row_count: int
    eligible_row_count: int
    eligible_asset_count: int
    unresolved_row_count: int
    future_report_date_count: int
    future_available_at_count: int
    oldest_report_date: date | None
    newest_report_date: date | None

    @property
    def safe_to_execute(self) -> bool:
        """Return whether source evidence contains no future boundary."""

        return self.future_report_date_count == 0 and self.future_available_at_count == 0

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe repair evidence."""

        return {
            "safe_to_execute": self.safe_to_execute,
            "missing_row_count": self.missing_row_count,
            "eligible_row_count": self.eligible_row_count,
            "eligible_asset_count": self.eligible_asset_count,
            "unresolved_row_count": self.unresolved_row_count,
            "future_report_date_count": self.future_report_date_count,
            "future_available_at_count": self.future_available_at_count,
            "oldest_report_date": (
                self.oldest_report_date.isoformat() if self.oldest_report_date else None
            ),
            "newest_report_date": (
                self.newest_report_date.isoformat() if self.newest_report_date else None
            ),
        }


class FinancialAvailabilityBackfillRepositoryProtocol(Protocol):
    """Port for evidence-preserving financial availability repair."""

    def preview_availability_backfill(
        self,
        *,
        asset_codes: tuple[str, ...],
        recorded_at: datetime,
    ) -> FinancialAvailabilityBackfillPreview:
        """Inspect missing availability and source report-date evidence."""

    def backfill_available_at_from_report_date(
        self,
        *,
        asset_codes: tuple[str, ...],
        recorded_at: datetime,
    ) -> int:
        """Set only missing availability from an existing source report date."""


@dataclass(frozen=True)
class FinancialAvailabilityBackfillResult:
    """Exact outcome of one atomic source-date availability repair."""

    updated_row_count: int
    before: FinancialAvailabilityBackfillPreview
    after: FinancialAvailabilityBackfillPreview

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe result evidence."""

        return {
            "updated_row_count": self.updated_row_count,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


class FinancialAvailabilityBackfillUseCase:
    """Atomically restore availability from source-provided report dates."""

    def __init__(
        self,
        *,
        repository: FinancialAvailabilityBackfillRepositoryProtocol,
        transaction: Callable[[], AbstractContextManager[None]],
    ) -> None:
        self._repository = repository
        self._transaction = transaction

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        recorded_at: datetime,
    ) -> FinancialAvailabilityBackfillPreview:
        """Return repairable and unresolved counts without writing facts."""

        normalized_codes = _normalize_asset_codes(asset_codes)
        _require_aware(recorded_at, "recorded_at")
        return self._repository.preview_availability_backfill(
            asset_codes=normalized_codes,
            recorded_at=recorded_at,
        )

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        recorded_at: datetime,
    ) -> FinancialAvailabilityBackfillResult:
        """Repair eligible rows or roll back on evidence/count drift."""

        normalized_codes = _normalize_asset_codes(asset_codes)
        _require_aware(recorded_at, "recorded_at")
        with self._transaction():
            before = self._repository.preview_availability_backfill(
                asset_codes=normalized_codes,
                recorded_at=recorded_at,
            )
            if not before.safe_to_execute:
                raise ValueError("financial availability evidence contains a future boundary")
            updated = self._repository.backfill_available_at_from_report_date(
                asset_codes=normalized_codes,
                recorded_at=recorded_at,
            )
            after = self._repository.preview_availability_backfill(
                asset_codes=normalized_codes,
                recorded_at=recorded_at,
            )
            if updated != before.eligible_row_count or after.eligible_row_count != 0:
                raise ValueError("financial availability backfill count drifted")
            if not after.safe_to_execute:
                raise ValueError("financial availability backfill produced a future boundary")
        return FinancialAvailabilityBackfillResult(
            updated_row_count=updated,
            before=before,
            after=after,
        )


class LatestQuoteRepositoryProtocol(Protocol):
    """Port reading one deterministic latest quote per asset."""

    def list_latest_for_asset_codes(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[QuoteSnapshot]:
        """Return latest persisted source snapshots."""


class PriceBarWriterProtocol(Protocol):
    """Port writing canonical daily price facts."""

    def bulk_upsert(self, bars: list[PriceBar]) -> int:
        """Persist validated daily bars idempotently."""


@dataclass(frozen=True)
class CompletedSessionPriceBarPreview:
    """Coverage proof for price bars derived from completed-session quotes."""

    session_date: date
    requested_asset_count: int
    eligible_asset_count: int
    missing_asset_codes: tuple[str, ...]
    invalid_asset_codes: tuple[str, ...]
    oldest_snapshot_at: datetime | None
    newest_snapshot_at: datetime | None

    @property
    def ready(self) -> bool:
        """Return whether every requested asset has a valid closing snapshot."""

        return (
            self.requested_asset_count > 0
            and self.eligible_asset_count == self.requested_asset_count
            and not self.missing_asset_codes
            and not self.invalid_asset_codes
        )

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe preview evidence with bounded code samples."""

        return {
            "ready": self.ready,
            "session_date": self.session_date.isoformat(),
            "requested_asset_count": self.requested_asset_count,
            "eligible_asset_count": self.eligible_asset_count,
            "missing_asset_count": len(self.missing_asset_codes),
            "missing_asset_codes": list(self.missing_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]),
            "missing_asset_codes_truncated": (
                len(self.missing_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "invalid_asset_count": len(self.invalid_asset_codes),
            "invalid_asset_codes": list(self.invalid_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]),
            "invalid_asset_codes_truncated": (
                len(self.invalid_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "oldest_snapshot_at": (
                self.oldest_snapshot_at.isoformat() if self.oldest_snapshot_at else None
            ),
            "newest_snapshot_at": (
                self.newest_snapshot_at.isoformat() if self.newest_snapshot_at else None
            ),
        }


@dataclass(frozen=True)
class _CompletedSessionPriceSelection:
    """Internal materialization selection shared by preview and execute."""

    preview: CompletedSessionPriceBarPreview
    bars: tuple[PriceBar, ...]


@dataclass(frozen=True)
class CompletedSessionPriceBarResult:
    """Exact persisted result for one completed-session materialization."""

    stored_count: int
    preview: CompletedSessionPriceBarPreview

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe result evidence."""

        return {"stored_count": self.stored_count, **self.preview.to_dict()}


class CompletedSessionPriceBarUseCase:
    """Materialize daily bars only from exact post-close source snapshots."""

    def __init__(
        self,
        *,
        quote_repository: LatestQuoteRepositoryProtocol,
        price_repository: PriceBarWriterProtocol,
        transaction: Callable[[], AbstractContextManager[None]],
    ) -> None:
        self._quotes = quote_repository
        self._prices = price_repository
        self._transaction = transaction

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        session_date: date,
        recorded_at: datetime,
    ) -> CompletedSessionPriceBarPreview:
        """Inspect exact completed-session quote coverage without writing bars."""

        return self._select(
            asset_codes=asset_codes,
            session_date=session_date,
            recorded_at=recorded_at,
        ).preview

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        session_date: date,
        recorded_at: datetime,
    ) -> CompletedSessionPriceBarResult:
        """Persist a full-universe daily bar set or leave facts unchanged."""

        selection = self._select(
            asset_codes=asset_codes,
            session_date=session_date,
            recorded_at=recorded_at,
        )
        if not selection.preview.ready:
            raise ValueError("completed-session quote coverage is incomplete or invalid")
        with self._transaction():
            stored = self._prices.bulk_upsert(list(selection.bars))
            if stored != len(selection.bars):
                raise ValueError("completed-session price persistence count drifted")
        return CompletedSessionPriceBarResult(stored_count=stored, preview=selection.preview)

    def _select(
        self,
        *,
        asset_codes: Sequence[str],
        session_date: date,
        recorded_at: datetime,
    ) -> _CompletedSessionPriceSelection:
        """Validate source time and OHLC invariants before materialization."""

        normalized_codes = _normalize_asset_codes(asset_codes)
        _require_aware(recorded_at, "recorded_at")
        quotes = self._quotes.list_latest_for_asset_codes(normalized_codes)
        by_asset = {quote.asset_code.strip().upper(): quote for quote in quotes}
        requested = set(normalized_codes)
        missing = tuple(sorted(requested - set(by_asset)))
        invalid: list[str] = []
        bars: list[PriceBar] = []
        observations: list[datetime] = []
        for asset_code in normalized_codes:
            quote = by_asset.get(asset_code)
            if quote is None:
                continue
            observations.append(quote.snapshot_at)
            local_observed_at = quote.snapshot_at.astimezone(CN_MARKET_TIMEZONE)
            values = (quote.open, quote.high, quote.low, quote.current_price)
            numeric_values = [float(value) for value in values if value is not None]
            invalid_ohlc = (
                len(numeric_values) != 4
                or any(not math.isfinite(value) or value <= 0 for value in numeric_values)
                or numeric_values[1] < max(numeric_values[0], numeric_values[2], numeric_values[3])
                or numeric_values[2] > min(numeric_values[0], numeric_values[1], numeric_values[3])
            )
            invalid_volume = quote.volume is not None and quote.volume < 0
            invalid_amount = quote.amount is not None and quote.amount < 0
            if (
                quote.snapshot_at > recorded_at
                or local_observed_at.date() != session_date
                or local_observed_at.time().replace(tzinfo=None) < CN_MARKET_CLOSE
                or not quote.source.strip()
                or invalid_ohlc
                or invalid_volume
                or invalid_amount
            ):
                invalid.append(asset_code)
                continue
            open_value, high_value, low_value, close_value = numeric_values
            bars.append(
                PriceBar(
                    asset_code=asset_code,
                    bar_date=session_date,
                    open=open_value,
                    high=high_value,
                    low=low_value,
                    close=close_value,
                    volume=quote.volume,
                    amount=quote.amount,
                    source=quote.source,
                    fetched_at=quote.fetched_at or recorded_at,
                )
            )
        preview = CompletedSessionPriceBarPreview(
            session_date=session_date,
            requested_asset_count=len(normalized_codes),
            eligible_asset_count=len(bars),
            missing_asset_codes=missing,
            invalid_asset_codes=tuple(sorted(invalid)),
            oldest_snapshot_at=min(observations) if observations else None,
            newest_snapshot_at=max(observations) if observations else None,
        )
        return _CompletedSessionPriceSelection(preview=preview, bars=tuple(bars))


@dataclass(frozen=True)
class CoreCurrentFactRefreshPreview:
    """Read-only preflight for the current-fact remediation workflow."""

    financial_availability: FinancialAvailabilityBackfillPreview
    completed_session_prices: CompletedSessionPriceBarPreview
    publications: CoreCurrentPublicationPreview

    @property
    def ready_without_provider_refresh(self) -> bool:
        """Return whether existing facts can be repaired and published as-is."""

        return (
            self.financial_availability.safe_to_execute
            and self.completed_session_prices.ready
            and self.publications.ready
        )

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe preflight evidence."""

        return {
            "ready_without_provider_refresh": self.ready_without_provider_refresh,
            "financial_availability": self.financial_availability.to_dict(),
            "completed_session_prices": self.completed_session_prices.to_dict(),
            "publications": self.publications.to_dict(),
        }


@dataclass(frozen=True)
class CoreCurrentFactRefreshResult:
    """Candidate-bound outcome of provider refresh, repair, and publication."""

    quote_stored_count: int
    valuation_stored_count: int
    price_probe_stored_count: int
    financial_probe_stored_count: int
    financial_availability: FinancialAvailabilityBackfillResult
    completed_session_prices: CompletedSessionPriceBarResult
    publications: CoreCurrentPublicationRebuildResult

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe execution evidence."""

        return {
            "quote_stored_count": self.quote_stored_count,
            "valuation_stored_count": self.valuation_stored_count,
            "price_probe_stored_count": self.price_probe_stored_count,
            "financial_probe_stored_count": self.financial_probe_stored_count,
            "financial_availability": self.financial_availability.to_dict(),
            "completed_session_prices": self.completed_session_prices.to_dict(),
            "publications": self.publications.to_dict(),
        }


class CoreCurrentFactRefreshUseCase:
    """Refresh current facts and publish only after full-universe validation."""

    def __init__(
        self,
        *,
        provider_id: int,
        quote_sync_factory: Callable[[], SyncQuoteUseCase],
        price_sync_factory: Callable[[], SyncPriceUseCase],
        valuation_sync_factory: Callable[[], SyncCurrentValuationBatchUseCase],
        financial_sync_factory: Callable[[], SyncFinancialUseCase],
        financial_availability: FinancialAvailabilityBackfillUseCase,
        completed_session_prices: CompletedSessionPriceBarUseCase,
        publications: CoreCurrentPublicationRebuildUseCase,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if provider_id <= 0:
            raise ValueError("provider_id must be positive")
        self._provider_id = provider_id
        self._quote_sync_factory = quote_sync_factory
        self._price_sync_factory = price_sync_factory
        self._valuation_sync_factory = valuation_sync_factory
        self._financial_sync_factory = financial_sync_factory
        self._financial_availability = financial_availability
        self._completed_session_prices = completed_session_prices
        self._publications = publications
        self._clock = clock or (lambda: datetime.now(UTC))

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        session_date: date,
        recorded_at: datetime,
    ) -> CoreCurrentFactRefreshPreview:
        """Inspect existing facts without external calls or writes."""

        normalized_codes = _normalize_asset_codes(asset_codes)
        return CoreCurrentFactRefreshPreview(
            financial_availability=self._financial_availability.preview(
                asset_codes=normalized_codes,
                recorded_at=recorded_at,
            ),
            completed_session_prices=self._completed_session_prices.preview(
                asset_codes=normalized_codes,
                session_date=session_date,
                recorded_at=recorded_at,
            ),
            publications=self._publications.preview(
                asset_codes=normalized_codes,
                published_at=recorded_at,
            ),
        )

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        session_date: date,
        recorded_at: datetime,
        batch_size: int,
    ) -> CoreCurrentFactRefreshResult:
        """Fetch, repair and publish current data while preserving fail-closed state."""

        normalized_codes = _normalize_asset_codes(asset_codes)
        _require_aware(recorded_at, "recorded_at")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= 500
        ):
            raise ValueError("batch_size must be an integer between 1 and 500")

        quote_sync = self._quote_sync_factory()
        price_sync = self._price_sync_factory()
        valuation_sync = self._valuation_sync_factory()
        financial_sync = self._financial_sync_factory()
        probe_code = normalized_codes[0]
        price_probe = price_sync.execute(
            SyncPriceRequest(
                provider_id=self._provider_id,
                asset_code=probe_code,
                start=session_date,
                end=session_date,
            )
        )
        if price_probe.stored_count <= 0:
            raise ValueError("historical-price provider probe produced zero rows")
        financial_probe = financial_sync.execute(
            SyncFinancialRequest(
                provider_id=self._provider_id,
                asset_code=probe_code,
                periods=1,
            )
        )
        if financial_probe.stored_count <= 0:
            raise ValueError("financial provider probe produced zero rows")

        quote_stored = 0
        valuation_stored = 0
        for offset in range(0, len(normalized_codes), batch_size):
            batch_codes = list(normalized_codes[offset : offset + batch_size])
            quote_result = quote_sync.execute(
                SyncQuoteRequest(provider_id=self._provider_id, asset_codes=batch_codes)
            )
            if quote_result.stored_count != len(batch_codes):
                raise ValueError("realtime-quote provider batch incomplete at offset " f"{offset}")
            quote_stored += quote_result.stored_count
            valuation_result = valuation_sync.execute(
                provider_id=self._provider_id,
                asset_codes=batch_codes,
                as_of_date=session_date,
            )
            if set(valuation_result.succeeded_asset_codes) != set(batch_codes):
                raise ValueError("valuation provider batch incomplete at offset " f"{offset}")
            valuation_stored += valuation_result.stored_count

        provider_completed_at = self._clock()
        _require_aware(provider_completed_at, "provider_completed_at")
        if provider_completed_at < recorded_at:
            raise ValueError("completion clock cannot precede the recorded start")
        financial_availability = self._financial_availability.execute(
            asset_codes=normalized_codes,
            recorded_at=provider_completed_at,
        )
        completed_session_prices = self._completed_session_prices.execute(
            asset_codes=normalized_codes,
            session_date=session_date,
            recorded_at=provider_completed_at,
        )
        publication_at = self._clock()
        _require_aware(publication_at, "publication_at")
        if publication_at < provider_completed_at:
            raise ValueError("publication clock cannot precede provider completion")
        publications = self._publications.execute(
            asset_codes=normalized_codes,
            published_at=publication_at,
        )
        return CoreCurrentFactRefreshResult(
            quote_stored_count=quote_stored,
            valuation_stored_count=valuation_stored,
            price_probe_stored_count=price_probe.stored_count,
            financial_probe_stored_count=financial_probe.stored_count,
            financial_availability=financial_availability,
            completed_session_prices=completed_session_prices,
            publications=publications,
        )


def _normalize_asset_codes(asset_codes: Sequence[str]) -> tuple[str, ...]:
    """Return a non-empty deterministic canonical code tuple."""

    normalized = tuple(
        sorted(
            {
                str(asset_code or "").strip().upper()
                for asset_code in asset_codes
                if str(asset_code or "").strip()
            }
        )
    )
    if not normalized:
        raise ValueError("active asset universe cannot be empty")
    return normalized


def _require_aware(value: datetime, field_name: str) -> None:
    """Reject naive operator or observation boundaries."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "CompletedSessionPriceBarPreview",
    "CompletedSessionPriceBarResult",
    "CompletedSessionPriceBarUseCase",
    "CoreCurrentFactRefreshPreview",
    "CoreCurrentFactRefreshResult",
    "CoreCurrentFactRefreshUseCase",
    "FinancialAvailabilityBackfillPreview",
    "FinancialAvailabilityBackfillResult",
    "FinancialAvailabilityBackfillUseCase",
]
