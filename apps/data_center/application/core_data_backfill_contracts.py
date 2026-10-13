"""Typed ports and injected services for resumable core-data backfills."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
)
from shared.domain.task_outcomes import TaskBusinessOutcome

from .backfill_control_plane import BackfillAuthorityBinding
from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .sync_market_use_cases import SyncQuoteUseCase
from .sync_use_cases import SyncFinancialUseCase, SyncPriceUseCase


class PersistBackfillControlPlane(Protocol):
    """Port for persisting one durable backfill lifecycle record."""

    def __call__(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        outcome: TaskBusinessOutcome,
        requested: int,
        succeeded: int,
        failed: int,
        stored: int,
        published: int,
        checkpoint: Mapping[str, object],
        window_start: date | None,
        window_end: date | None,
        started_at: datetime,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        """Persist a normalized run, batch, and checkpoint."""


class RebuildCurrentPublications(Protocol):
    """Port for atomically publishing the complete core asset universe."""

    def __call__(
        self,
        *,
        asset_codes: list[str],
        published_at: datetime,
    ) -> object:
        """Publish complete current snapshots or raise without partial commit."""


class BackfillItemAttemptStore(Protocol):
    """Port for durable per-asset DATA-02 execution evidence."""

    def begin(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        asset_code: str,
        phase: SyncItemAttemptPhase,
        execution_token: str,
        started_at: datetime,
        universe_hash: str,
        authority_content_hash: str,
        requested: int,
    ) -> SyncItemAttempt:
        """Persist one RUNNING item attempt before its external write."""

    def finish(
        self,
        attempt: SyncItemAttempt,
        *,
        state: SyncItemAttemptState,
        finished_at: datetime,
        stored_count: int = 0,
        error_code: str = "",
        error_message: str = "",
        evidence_hash: str = "",
    ) -> SyncItemAttempt:
        """Persist the single terminal transition for one item attempt."""

    def begin_many(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        asset_codes: Sequence[str],
        phase: SyncItemAttemptPhase,
        execution_token: str,
        started_at: datetime,
        universe_hash: str,
        authority_content_hash: str,
        requested: int,
    ) -> list[SyncItemAttempt]:
        """Persist one bounded phase batch of RUNNING item attempts atomically."""

    def finish_many(
        self,
        attempts: Sequence[SyncItemAttempt],
    ) -> list[SyncItemAttempt]:
        """Persist prepared terminal transitions for one phase batch atomically."""


class PublicationEvidenceHash(Protocol):
    """Port for binding a rebuild result to immutable Publication identities."""

    def __call__(self, result: object, expected_asset_count: int) -> str:
        """Return a canonical SHA-256 for committed Publication evidence."""


@dataclass(frozen=True)
class CoreDataBackfillServices:
    """Injected ports and use-case factories for one backfill batch."""

    list_active_stock_codes: Callable[[], list[str]]
    get_active_provider_id: Callable[[str], int | None]
    latest_completed_market_session: Callable[[datetime], date | None]
    current_time: Callable[[], datetime]
    make_sync_quote_use_case: Callable[[], SyncQuoteUseCase]
    make_sync_price_use_case: Callable[[], SyncPriceUseCase]
    make_sync_valuation_batch_use_case: Callable[[], SyncCurrentValuationBatchUseCase]
    make_sync_financial_use_case: Callable[[], SyncFinancialUseCase]
    rebuild_current_publications: RebuildCurrentPublications
    published_count_from_result: Callable[[object], int]
    publication_evidence_hash: PublicationEvidenceHash
    persist_control_plane: PersistBackfillControlPlane
    item_attempt_store: BackfillItemAttemptStore
    authority_binding: BackfillAuthorityBinding
    revalidate_authority: Callable[[datetime], bool]
    universe_evidence: Callable[[], Mapping[str, object]] | None = None
