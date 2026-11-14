"""Compose exact retained historical price reads without current-pointer authority."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime

from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from apps.data_center.application.retained_historical_price_source import (
    ReadRetainedHistoricalPriceSource,
    RetainedHistoricalActivationReader,
    RetainedHistoricalPriceActivation,
    RetainedHistoricalPriceSourceRequest,
    RetainedHistoricalPriceSourceResult,
)
from apps.data_center.composition import get_canonical_publication_repository
from apps.data_center.infrastructure.publication_read_snapshot import (
    stabilize_caller_owned_publication_read,
)
from apps.data_center.infrastructure.published_price_source_repository import (
    DjangoPublishedPriceSourceRepository,
)
from core.exceptions import DataFetchError, DataValidationError
from core.integration.data_center_audit import (
    AuditScopeRef,
    RetainedSystemAuditPair,
    SystemAuditCompositionUnavailable,
    SystemAuditEvent,
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
    SystemAuditQueryCorruption,
    SystemAuditQueryUnavailable,
    preflight_data_reliability_audit_runtime,
    read_data_center_retained_system_audit_stream,
)

_DATASET_KEY = "equity.price.bar"
_PUBLICATION_STREAM_ID = f"data.publication:{_DATASET_KEY}"
_MAX_RETAINED_AUDIT_PAIRS = 10_000


class _DjangoRetainedHistoricalActivationReader(RetainedHistoricalActivationReader):
    """Resolve one original M1 activation through the scoped Audit/Core facades."""

    def __init__(self, *, environment: str, using: str) -> None:
        """Bind read-only Audit scope and the single supported database alias."""
        self._environment = environment
        self._using = using

    def read_original_activation(
        self, publication_id: str, *, knowledge_cutoff: datetime
    ) -> RetainedHistoricalPriceActivation | None:
        """Read one original activation and its independently verified Outbox pair."""
        context = preflight_data_reliability_audit_runtime(
            environment=self._environment,
            using=self._using,
            as_of=knowledge_cutoff,
        )
        pairs = read_data_center_retained_system_audit_stream(
            stream_id=_PUBLICATION_STREAM_ID,
            scope=context.scope,
            using=self._using,
            as_of=knowledge_cutoff,
        )
        events = _verified_publication_stream_events(
            pairs,
            scope=context.scope,
            as_of=knowledge_cutoff,
        )
        related_rollbacks = tuple(
            event
            for event in events
            if event.event_type == "data.publication.rolled_back"
            and (
                event.publication_id == publication_id
                or event.detail.get("previous_publication_id") == publication_id
            )
        )
        if related_rollbacks:
            raise SystemAuditQueryCorruption(
                "selected publication is involved in an explicit rollback"
            )
        matches = tuple(
            pair
            for pair in pairs
            if pair.event.event_type == "data.publication.published"
            and pair.event.publication_id == publication_id
            and pair.event.correlations.publication_id == publication_id
        )
        if len(matches) != 1:
            return None
        return RetainedHistoricalPriceActivation(matches[0])


def _verified_publication_stream_events(
    pairs: tuple[RetainedSystemAuditPair, ...],
    *,
    scope: AuditScopeRef,
    as_of: datetime,
) -> tuple[SystemAuditEvent, ...]:
    """Require one complete, ordered, cutoff-known retained publication prefix."""
    if type(pairs) is not tuple or len(pairs) > _MAX_RETAINED_AUDIT_PAIRS:
        raise SystemAuditEventOutboxCorruption(
            "retained publication Audit stream is unbounded or untyped"
        )
    events: list[SystemAuditEvent] = []
    previous: SystemAuditEvent | None = None
    for expected_sequence, pair in enumerate(pairs, start=1):
        if type(pair) is not RetainedSystemAuditPair:
            raise SystemAuditEventOutboxCorruption(
                "retained publication Audit stream contains an untyped pair"
            )
        pair.verify_at_cutoff(as_of=as_of)
        event = pair.event
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise SystemAuditEventOutboxCorruption(
                "retained publication Audit stream event hash is invalid"
            ) from error
        if (
            type(event) is not SystemAuditEvent
            or event.stream_id != _PUBLICATION_STREAM_ID
            or event.scope != scope
            or event.sequence_no != expected_sequence
            or (previous is None and event.predecessor_hash is not None)
            or (
                previous is not None
                and (
                    event.predecessor_hash != previous.content_hash
                    or event.recorded_at < previous.recorded_at
                )
            )
        ):
            raise SystemAuditEventOutboxCorruption(
                "retained publication Audit stream is incomplete or crossed"
            )
        events.append(event)
        previous = event
    return tuple(events)


def read_retained_historical_price_source(
    asset_code: str,
    *,
    trade_date: date,
    publication_id: str,
    expected_publication_key: str,
    knowledge_cutoff: datetime,
    environment: str,
    using: str = "default",
) -> RetainedHistoricalPriceSourceResult:
    """Read one exact historical M1 raw close with original source and Audit evidence.

    The result is explicitly historical/current-knowledge evidence. This reader
    does not consult the current pointer, capture/repair a source, or authorize
    trading, valuation completeness, or a financial action.
    """
    if using != "default":
        return RetainedHistoricalPriceSourceResult(None, "retained_price_alias_unsupported")
    try:
        request = RetainedHistoricalPriceSourceRequest(
            asset_code=asset_code,
            trade_date=trade_date,
            publication_id=publication_id,
            expected_publication_key=expected_publication_key,
            knowledge_cutoff=knowledge_cutoff,
        )
        started_at = timezone.now()
        if knowledge_cutoff > started_at:
            return RetainedHistoricalPriceSourceResult(None, "retained_price_cutoff_in_future")
        connection = connections[using]
        boundary = nullcontext() if connection.in_atomic_block else transaction.atomic(using=using)
        with boundary:
            stabilize_caller_owned_publication_read(_DATASET_KEY)
            result = _read_retained_source_snapshot(
                request,
                environment=environment,
                using=using,
            )
        completed_at = timezone.now()
        if completed_at < started_at or knowledge_cutoff > completed_at:
            return RetainedHistoricalPriceSourceResult(None, "retained_price_clock_invalid")
        return result
    except (DataValidationError, TypeError, ValueError):
        return RetainedHistoricalPriceSourceResult(None, "retained_price_request_invalid")
    except (
        DataFetchError,
        DatabaseError,
        SystemAuditCompositionUnavailable,
        SystemAuditEventOutboxCorruption,
        SystemAuditEventOutboxUnavailable,
        SystemAuditQueryCorruption,
        SystemAuditQueryUnavailable,
    ):
        return RetainedHistoricalPriceSourceResult(None, "retained_price_read_unavailable")


def _read_retained_source_snapshot(
    request: RetainedHistoricalPriceSourceRequest,
    *,
    environment: str,
    using: str,
) -> RetainedHistoricalPriceSourceResult:
    """Keep exact publication, source rows, and Audit/Outbox reads in one snapshot."""
    return ReadRetainedHistoricalPriceSource(
        publications=get_canonical_publication_repository(),
        prices=DjangoPublishedPriceSourceRepository(),
        activations=_DjangoRetainedHistoricalActivationReader(
            environment=environment,
            using=using,
        ),
    ).execute(request)


__all__ = ["read_retained_historical_price_source"]
