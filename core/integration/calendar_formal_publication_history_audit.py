"""Core bridge for the exact historical formal-calendar Audit pair."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditUnavailable,
    CalendarPublicationPublishedObservation,
)
from apps.audit.application.calendar_publication_integrity import (
    CalendarPublicationAuditIntegrityReceipt,
    VerifyPublishedCalendarPublicationIntegrityUseCase,
)
from apps.audit.calendar_publication_composition import CalendarPublicationAuditCoordinator
from apps.audit.domain.calendar_publication_audit import (
    CalendarPublicationAuditEvidence,
    CalendarPublicationPublishedDetail,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarPublicationAuditPair,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalCalendarPublicationRecord,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
)

_ALLOWED_HISTORY_LIFECYCLES: Final[frozenset[CalendarPublicationLifecycle]] = frozenset(
    {
        CalendarPublicationLifecycle.PUBLISHED,
        CalendarPublicationLifecycle.SUPERSEDED,
    }
)


class CoreCalendarFormalPublicationHistoricalAuditBridge:
    """Verify historical publication event/outbox integrity without pointer claims."""

    __slots__ = ("_using", "_coordinator")

    def __init__(
        self,
        *,
        using: str,
        coordinator: CalendarPublicationAuditCoordinator,
    ) -> None:
        """Bind the existing exact Audit reader to the publication database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise CalendarPublicationAuditUnavailable(
                "historical calendar Audit verification requires an explicit database alias"
            )
        if coordinator.database_alias != using:
            raise CalendarPublicationAuditUnavailable(
                "historical calendar Audit coordinator uses another database alias"
            )
        self._using = using
        self._coordinator = coordinator

    @property
    def database_alias(self) -> str:
        """Return the exact alias required for the caller-owned read transaction."""

        return self._using

    def verify_historical_published_integrity(
        self,
        record: HistoricalCalendarPublicationRecord,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Verify one immutable published event/outbox pair at its historical cutoff.

        The Audit v1 published detail binds the source, publication UUID and
        seal hash. It has no pointer or activation field; this method neither
        creates nor infers either identity.
        """

        if type(record) is not HistoricalCalendarPublicationRecord:
            raise CalendarFormalPublicationApplicationError(
                "historical Audit verification requires a typed record",
                code="CALENDAR_PUBLICATION_AUDIT_RECORD_INVALID",
            )
        try:
            record.__post_init__()
            _require_utc(as_of)
        except (AttributeError, TypeError, ValueError, CalendarFormalPublicationError) as error:
            raise CalendarFormalPublicationApplicationError(
                "historical Audit record is malformed",
                code="CALENDAR_PUBLICATION_AUDIT_RECORD_INVALID",
            ) from error
        if (
            record.lifecycle not in _ALLOWED_HISTORY_LIFECYCLES
            or record.published_at > as_of
            or not record.is_effective_at(as_of)
        ):
            raise CalendarFormalPublicationApplicationError(
                "historical publication is not effective at its Audit cutoff",
                code="CALENDAR_PUBLICATION_AUDIT_CUTOFF_INVALID",
            )
        observation = _observation_from_historical_record(record)
        receipt = VerifyPublishedCalendarPublicationIntegrityUseCase(self._coordinator).execute(
            observation, as_of=as_of
        )
        return _pair_from_receipt(record, receipt, using=self._using, as_of=as_of)


def _observation_from_historical_record(
    record: HistoricalCalendarPublicationRecord,
) -> CalendarPublicationPublishedObservation:
    """Build the canonical Audit v1 observation from a verified immutable seal."""

    seal = record.seal
    snapshot = seal.snapshot
    raw = snapshot.raw_reference
    evidence = CalendarPublicationAuditEvidence(
        snapshot_id=snapshot.snapshot_id,
        exchange=snapshot.exchange,
        coverage_start=snapshot.coverage_start,
        coverage_end=snapshot.coverage_end,
        provider_name=seal.snapshot_provider_name,
        first_seen_at=seal.snapshot_first_seen_at,
        snapshot_recorded_at=seal.snapshot_recorded_at,
        source_published_at=snapshot.source_published_at,
        fact_content_hash=seal.member_reference.member.fact_content_hash,
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
        raw_payload_id=raw.payload_id,
        raw_payload_hash=raw.payload_hash,
        raw_record_digest=raw.record_digest,
        raw_body_sha256=raw.body_sha256,
        raw_retained_content_sha256=raw.retained_content_sha256,
        raw_request_scope_sha256=raw.request_scope_sha256,
        original_body_retained=raw.original_body_retained,
        response_completed_at=raw.response_completed_at,
        raw_provider_name=raw.provider_name,
        raw_dataset_key=raw.dataset_key,
        raw_transport=raw.transport,
    )

    detail = CalendarPublicationPublishedDetail(
        dataset_key=seal.dataset.value,
        exchange=seal.exchange,
        publication_id=record.publication_id,
        publication_key=seal.publication_key,
        policy_version=seal.policy_version,
        publication_hash=seal.publication_hash,
        snapshot_evidence=evidence,
    )
    return CalendarPublicationPublishedObservation(detail=detail, recorded_at=record.published_at)


def _pair_from_receipt(
    record: HistoricalCalendarPublicationRecord,
    receipt: CalendarPublicationAuditIntegrityReceipt,
    *,
    using: str,
    as_of: datetime,
) -> CalendarPublicationAuditPair:
    """Map the verified event/outbox receipt to the Data Center public contract."""

    if type(receipt) is not CalendarPublicationAuditIntegrityReceipt:
        raise CalendarPublicationAuditUnavailable(
            "historical calendar Audit returned no exact integrity receipt"
        )
    try:
        CalendarPublicationAuditIntegrityReceipt.__post_init__(receipt)
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditUnavailable(
            "historical calendar Audit integrity receipt is malformed"
        ) from error
    seal = record.seal
    if (
        receipt.database_alias != using
        or receipt.dataset_key != seal.dataset.value
        or receipt.exchange != seal.exchange
        or receipt.publication_id != record.publication_id
        or receipt.publication_hash != seal.publication_hash
        or receipt.recorded_at != record.published_at
        or receipt.recorded_at > as_of
    ):
        raise CalendarPublicationAuditUnavailable(
            "historical calendar Audit receipt differs from the immutable publication"
        )
    return CalendarPublicationAuditPair(
        database_alias=receipt.database_alias,
        dataset_key=receipt.dataset_key,
        exchange=receipt.exchange,
        publication_id=receipt.publication_id,
        publication_hash=receipt.publication_hash,
        event_id=receipt.event_id,
        event_content_hash=receipt.event_content_hash,
        actor_user_id=receipt.actor_user_id,
        outbox_id=receipt.outbox_id,
        idempotency_key=receipt.idempotency_key,
        recorded_at=receipt.recorded_at,
    )


def _require_utc(value: object) -> None:
    """Reject naive and non-UTC Audit cutoffs without normalization."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CalendarFormalPublicationApplicationError(
            "historical Audit cutoff must be an aware UTC instant",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )


__all__ = ["CoreCalendarFormalPublicationHistoricalAuditBridge"]
