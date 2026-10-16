"""Core bridge between Data Center calendar publication and Audit v1.

This adapter composes only public Application contracts. Data Center remains
the owner of the publication record and Audit remains the owner of canonical
event/outbox validation and persistence.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from apps.audit.application.calendar_publication_audit import (
    AppendCalendarPublicationAuditUseCase,
    CalendarPublicationAuditUnavailable,
    CalendarPublicationPublishedObservation,
)
from apps.audit.application.calendar_publication_integrity import (
    CalendarPublicationAuditIntegrityReceipt,
    VerifyPublishedCalendarPublicationIntegrityUseCase,
)
from apps.audit.application.calendar_publication_replay_verifier import (
    VerifyCurrentCalendarPublicationAuditReplayUseCase,
)
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.calendar_publication_composition import (
    CalendarPublicationAuditCoordinator,
    build_calendar_publication_audit_coordinator,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_PUBLICATION_PUBLISHED_EVENT,
    CalendarPublicationAuditContractError,
    CalendarPublicationAuditEvidence,
    CalendarPublicationPublishedDetail,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent
from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarPublicationAuditPair,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
)

_ACTOR_RE = re.compile(r"^django-user:([1-9][0-9]{0,18})$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class CalendarPublicationAuditCoordinatorFactory(Protocol):
    """Alias-bound public Audit composition factory accepted by the bridge."""

    def __call__(self, *, using: str) -> CalendarPublicationAuditCoordinator:
        """Build the exact same-alias Audit Application reader/writer adapter."""


class CoreCalendarFormalPublicationAuditBridge(CalendarFormalPublicationAuditPort):
    """Implement the Data Center Audit port through canonical Audit use cases."""

    __slots__ = ("_using", "_coordinator")

    def __init__(
        self,
        *,
        using: str,
        coordinator: CalendarPublicationAuditCoordinator | None = None,
        coordinator_factory: CalendarPublicationAuditCoordinatorFactory | None = None,
    ) -> None:
        """Bind one Audit coordinator to the explicit Data Center database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication Audit requires an explicit database alias"
            )
        if coordinator is not None and coordinator_factory is not None:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication Audit accepts one composition source"
            )
        if coordinator is None:
            selected_factory = coordinator_factory or build_calendar_publication_audit_coordinator
            try:
                coordinator = selected_factory(using=using)
            except Exception as error:
                raise CalendarPublicationAuditUnavailable(
                    "calendar publication Audit composition is unavailable"
                ) from error
        if coordinator.database_alias != using:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication Audit coordinator uses another database alias"
            )
        self._using = using
        self._coordinator = coordinator

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the caller-owned Data Center transaction."""

        return self._using

    def record_published(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarPublicationAuditPair:
        """Append an exact new publication event/outbox under the live publisher lease."""

        self._validate_record(record)
        self._validate_principal(principal)
        if record.published_at < principal.verified_at:
            raise CalendarFormalPublicationApplicationError(
                "new calendar Audit event time precedes the locked publisher check",
                code="CALENDAR_PUBLICATION_AUTHORITY_TIME_INVALID",
            )
        principal.assert_live()
        observation = _observation_from_record(record)
        commit = AppendCalendarPublicationAuditUseCase(
            self._coordinator
        ).execute_published_in_caller_transaction(
            observation,
            principal=principal,
            exact_replay=False,
        )
        principal.assert_live()
        return self._pair_from_commit(
            record,
            observation,
            commit,
            expected_actor_id=principal.actor_id,
            expected_actor_user_id=principal.user_id,
        )

    def verify_current_replay(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarPublicationAuditPair:
        """Verify an exact current replay by its original actor's live permission."""

        self._validate_record(record)
        self._validate_principal(principal)
        principal.assert_live()
        observation = _observation_from_record(record)
        commit = VerifyCurrentCalendarPublicationAuditReplayUseCase(self._coordinator).execute(
            observation, principal=principal
        )
        principal.assert_live()
        return self._pair_from_commit(
            record,
            observation,
            commit,
            expected_actor_id=principal.actor_id,
            expected_actor_user_id=principal.user_id,
        )

    def verify_published_integrity(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Verify one exact pair inside the caller's authorized current-read UOW.

        This method does not issue publication or Audit browsing permission. Its
        caller must already be within the same-alias Data Center transaction and
        must independently authorize the requested current calendar read.
        """

        self._validate_record(record)
        _require_utc(as_of, "as_of")
        if record.published_at > as_of:
            raise CalendarFormalPublicationApplicationError(
                "calendar publication is not knowable at the requested cutoff",
                code="CALENDAR_PUBLICATION_AUDIT_CUTOFF_INVALID",
            )
        observation = _observation_from_record(record)
        receipt = VerifyPublishedCalendarPublicationIntegrityUseCase(self._coordinator).execute(
            observation, as_of=as_of
        )
        return self._pair_from_integrity_receipt(record, receipt, as_of=as_of)

    def _validate_record(self, record: CalendarFormalPublicationRecord) -> None:
        """Revalidate exact record identity and require the active lifecycle."""

        if type(record) is not CalendarFormalPublicationRecord:
            raise CalendarFormalPublicationApplicationError(
                "calendar Audit bridge requires a typed formal record",
                code="CALENDAR_PUBLICATION_AUDIT_RECORD_INVALID",
            )
        try:
            record.validate()
        except CalendarFormalPublicationError as error:
            raise CalendarFormalPublicationApplicationError(str(error), code=error.code) from error
        if record.lifecycle is not CalendarPublicationLifecycle.PUBLISHED:
            raise CalendarFormalPublicationApplicationError(
                "only the current published calendar record can bind this Audit event",
                code="CALENDAR_PUBLICATION_AUDIT_RECORD_INVALID",
            )

    def _validate_principal(self, principal: LockedCalendarPublisherPrincipal) -> None:
        """Require the exact live session-backed publisher and configured alias."""

        try:
            principal.assert_live()
            valid = (
                type(principal.actor_type) is str
                and principal.actor_type == "django_user"
                and type(principal.user_id) is int
                and principal.user_id > 0
                and type(principal.actor_id) is str
                and principal.actor_id == f"django-user:{principal.user_id}"
                and type(principal.permission_codename) is str
                and principal.permission_codename == CALENDAR_PUBLISH_PERMISSION_CODENAME
                and type(principal.permission_id) is int
                and principal.permission_id > 0
                and type(principal.database_alias) is str
                and principal.database_alias == self._using
                and _is_utc(principal.verified_at)
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarFormalPublicationApplicationError(
                "calendar Audit bridge received an incomplete publisher lease",
                code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
            ) from error
        if not valid:
            raise CalendarFormalPublicationApplicationError(
                "calendar Audit bridge received another actor, permission, or database",
                code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
            )

    def _pair_from_commit(
        self,
        record: CalendarFormalPublicationRecord,
        observation: CalendarPublicationPublishedObservation,
        commit: SystemAuditEventOutboxCommit,
        *,
        expected_actor_id: str,
        expected_actor_user_id: int,
    ) -> CalendarPublicationAuditPair:
        """Map only a complete, exact Audit event/outbox commit to DC's receipt."""

        if type(commit) is not SystemAuditEventOutboxCommit:
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit use case returned no exact event/outbox commit"
            )
        try:
            SystemAuditEventOutboxCommit.__post_init__(commit)
            event = commit.event
            validate_calendar_publication_event(event)
            parsed_detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
        except (
            AttributeError,
            TypeError,
            ValueError,
            CalendarPublicationAuditContractError,
        ) as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit event/outbox commit failed exact verification"
            ) from error
        actor = _actor_user_id(event.actor.actor_id)
        if (
            type(event) is not SystemAuditEvent
            or event.event_type != CALENDAR_PUBLICATION_PUBLISHED_EVENT
            or event.scope is not None
            or event.dataset_key != record.seal.dataset.value
            or event.recorded_at != record.published_at
            or event.occurred_at != record.published_at
            or event.observed_at is not None
            or event.actor.actor_type != "django_user"
            or event.actor.actor_id != expected_actor_id
            or actor != expected_actor_user_id
            or event.detail != observation.detail.to_payload()
            or parsed_detail != observation.detail
            or event.event_id != commit.event_id
            or event.idempotency_key != commit.idempotency_key
            or event.idempotency_key != event.event_id
            or type(commit.outbox_id) is not UUID
            or type(event.content_hash) is not str
            or _DIGEST_RE.fullmatch(event.content_hash) is None
        ):
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit event/outbox does not bind the exact publication and actor"
            )
        return CalendarPublicationAuditPair(
            database_alias=self._using,
            dataset_key=record.seal.dataset.value,
            exchange=record.seal.exchange,
            publication_id=record.publication_id,
            publication_hash=record.seal.publication_hash,
            event_id=event.event_id,
            event_content_hash=event.content_hash,
            actor_user_id=actor,
            outbox_id=commit.outbox_id,
            idempotency_key=event.idempotency_key,
            recorded_at=event.recorded_at,
        )

    def _pair_from_integrity_receipt(
        self,
        record: CalendarFormalPublicationRecord,
        receipt: CalendarPublicationAuditIntegrityReceipt,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Map the minimal Audit integrity receipt without exposing its event."""

        if type(receipt) is not CalendarPublicationAuditIntegrityReceipt:
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit returned no minimal integrity receipt"
            )
        try:
            CalendarPublicationAuditIntegrityReceipt.__post_init__(receipt)
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit integrity receipt is malformed"
            ) from error
        if (
            receipt.database_alias != self._using
            or receipt.dataset_key != record.seal.dataset.value
            or receipt.exchange != record.seal.exchange
            or receipt.publication_id != record.publication_id
            or receipt.publication_hash != record.seal.publication_hash
            or receipt.recorded_at != record.published_at
            or receipt.recorded_at > as_of
        ):
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit integrity receipt differs from the exact current record"
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


def _observation_from_record(
    record: CalendarFormalPublicationRecord,
) -> CalendarPublicationPublishedObservation:
    """Map a frozen DC record into Audit's exact v1 published event detail."""

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


def _actor_user_id(actor_id: str) -> int:
    """Parse only the exact Django-user actor identity from a stored event."""

    match = _ACTOR_RE.fullmatch(actor_id) if type(actor_id) is str else None
    if match is None:
        raise CalendarPublicationAuditUnavailable("calendar Audit event actor is not a Django user")
    return int(match.group(1))


def _require_utc(value: object, field_name: str) -> None:
    """Reject naive and non-UTC knowledge cutoffs without normalization."""

    if not _is_utc(value):
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be an aware UTC instant",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )


def _is_utc(value: object) -> bool:
    """Return whether a datetime is aware and has zero UTC offset."""

    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
    )


__all__ = [
    "CoreCalendarFormalPublicationAuditBridge",
    "CalendarPublicationAuditCoordinatorFactory",
]
