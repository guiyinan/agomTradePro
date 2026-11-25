"""READ COMMITTED ORM writer and session-bound Owner authority for C2.

The local apply/revoke rows are Data Center configuration evidence only. This
module neither writes SystemAudit/outbox records nor proves calendar or E1
publication authority.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Literal, cast
from uuid import uuid4

from django.db import (
    IntegrityError,
    connections,
    transaction,
)
from django.db.backends.base.base import BaseDatabaseWrapper

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
    FinancialAvailabilitySourceReaderPort,
    LockedFinancialAvailabilityPrincipal,
)
from apps.data_center.domain.financial_availability_governance import (
    FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL,
    FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
    FinancialAvailabilityContent,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceDateEvidence
from apps.data_center.infrastructure.financial_availability_governance_authority import (
    _FinancialAvailabilityPrincipalLease,
)
from apps.data_center.infrastructure.financial_availability_governance_codec import (
    deserialize_financial_availability_owner_event,
    deserialize_financial_availability_record,
    serialize_financial_availability_owner_event,
    serialize_financial_availability_record,
)
from apps.data_center.infrastructure.financial_availability_governance_models import (
    FinancialAvailabilityGovernanceRecordModel,
    FinancialAvailabilityOwnerEventModel,
)
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
)
from core.exceptions import (
    AuthorizationError,
    DataValidationError,
    ExternalServiceError,
)
from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    ScopedAdvisoryLockUnavailableError,
    try_acquire_scoped_advisory_exclusive,
    try_acquire_scoped_advisory_shared,
)

_DATABASE_SESSION_ENGINE = "django.contrib.sessions.backends.db"
_C2_PERMISSION = (
    f"{FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL}."
    f"{FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME}"
)
_FINANCIAL_AVAILABILITY_SCOPE_LOCK_DOMAIN = "data-center.financial-availability-governance"


def _utc(value: object, name: str) -> datetime:
    """Require an aware zero-offset UTC instant without inventing a clock."""

    if type(value) is not datetime or value.tzinfo is None:
        raise DataValidationError(f"{name} must be an aware UTC datetime.")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise DataValidationError(f"{name} must be an explicit UTC datetime.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise DataValidationError(f"{name} is outside the UTC range.") from error


def _record_payload(record: FinancialAvailabilityGovernanceRecord) -> dict[str, object]:
    """Decode the exact strict-codec envelope to a JSONField-compatible object."""

    raw = serialize_financial_availability_record(record)
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise DataValidationError("C2 record codec did not produce one JSON object.")
    return cast(dict[str, object], value)


def _decode_record_row(
    row: FinancialAvailabilityGovernanceRecordModel,
) -> FinancialAvailabilityGovernanceRecord:
    """Rehash one stored JSON payload and compare every indexed identity field."""

    try:
        raw = json.dumps(
            row.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        record = deserialize_financial_availability_record(raw)
    except (TypeError, ValueError, UnicodeError) as error:
        raise DataValidationError("Stored C2 configuration payload is invalid.") from error
    if (
        record.record_id != row.record_id
        or record.record_version != row.record_version
        or record.exchange != row.exchange
        or record.kind.value != row.kind
        or record.recorded_at != _utc(row.recorded_at, "record.recorded_at")
        or record.content_sha256 != row.content_sha256
        or (record.source.capture_id if record.source is not None else None)
        != row.source_capture_id
    ):
        raise DataValidationError("Stored C2 configuration columns differ from its payload hash.")
    return record


def _source_date_matches(
    row: StatutorySourceDocumentRevisionModel,
    *,
    prefix: Literal["publication", "effective"],
    expected: StatutorySourceDateEvidence,
) -> bool:
    """Compare native precision/date/instant fields without coercing precision."""

    expected.__post_init__()
    if prefix == "publication":
        actual_precision = row.publication_precision
        actual_date = row.publication_date
        actual_instant = row.publication_instant
    else:
        actual_precision = row.effective_precision
        actual_date = row.effective_date
        actual_instant = row.effective_instant
    return (
        actual_precision == expected.precision.value
        and actual_date == expected.date_value
        and actual_instant == expected.instant_value
    )


def _verify_source_capture_row(
    source: StatutorySourceCaptureReference,
    *,
    using: str,
) -> StatutorySourceDocumentCaptureModel:
    """Require the exact bound capture and native revision row identities."""

    try:
        capture = (
            StatutorySourceDocumentCaptureModel._default_manager.using(using)
            .select_related("revision")
            .get(capture_id=source.capture_id)
        )
    except StatutorySourceDocumentCaptureModel.DoesNotExist as error:
        raise DataValidationError("C2 source capture row is missing.") from error
    revision = capture.revision
    if (
        revision.issuer != source.issuer
        or revision.document_id != source.document_id
        or revision.source_version != source.source_version
        or revision.title != source.title
        or revision.legal_number != source.legal_number
        or revision.canonical_url != source.canonical_url
        or revision.source_revision_sha256 != source.source_revision_sha256
        or revision.body_sha256 != source.body_sha256
        or revision.body_size_bytes != source.body_size_bytes
        or not _source_date_matches(
            row=revision, prefix="publication", expected=source.publication_date
        )
        or not _source_date_matches(
            row=revision,
            prefix="effective",
            expected=source.source_effective_date,
        )
        or _utc(revision.recorded_at, "source.revision_recorded_at") != source.revision_recorded_at
        or capture.content_type != source.capture_content_type
        or capture.body_reference != source.body_reference
        or _utc(capture.captured_at, "source.capture_observed_at") != source.capture_observed_at
        or _utc(capture.recorded_at, "source.capture_recorded_at") != source.capture_recorded_at
    ):
        raise DataValidationError("C2 source capture differs from its exact native revision.")
    return capture


def _require_read_committed_uow(using: str) -> None:
    """Join an existing PostgreSQL READ COMMITTED transaction without nesting."""

    connection = connections[using]
    if connection.vendor != "postgresql" or not connection.in_atomic_block:
        raise DataValidationError("C2 Owner writes require a PostgreSQL caller-owned UOW.")
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        row = cursor.fetchone()
    if row is None or row[0] != "read committed":
        raise DataValidationError("C2 Owner writes require READ COMMITTED isolation.")


def _require_single_read_committed_uow(
    connection: BaseDatabaseWrapper,
    using: str,
) -> None:
    """Require exactly one ambient transaction for calendar-current composition."""

    if (
        connection.alias != using
        or not connection.in_atomic_block
        or connection.get_autocommit()
        or len(connection.atomic_blocks) != 1
    ):
        raise DataValidationError(
            "C2 current resolution requires one caller-owned same-alias transaction.",
            code="FIN_AVAILABILITY_CURRENT_UOW_INVALID",
        )
    _require_read_committed_uow(using)


def _lock_change_scope(
    using: str,
    kind: FinancialAvailabilityRecordKind,
    exchange: str,
) -> None:
    """Acquire the one exclusive C2 key shared by all apply/revoke writers."""

    _require_read_committed_uow(using)
    key = _scope_lock_key(kind, exchange)
    try:
        try_acquire_scoped_advisory_exclusive(using=using, keys=(key,))
    except ScopedAdvisoryLockUnavailableError as error:
        raise DataValidationError(
            "C2 scope is being resolved by a current financial consumer.",
            code="FIN_AVAILABILITY_SCOPE_LOCK_BUSY",
        ) from error


class DjangoFinancialAvailabilityGovernanceRepository:
    """Append and reread exact C2 record rows on one explicit database alias."""

    def __init__(self, *, using: str) -> None:
        """Bind the ordinary governance repository to one database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataValidationError("C2 governance repository requires one explicit alias.")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias holding the immutable governance rows."""

        return self._using

    def atomic(self) -> AbstractContextManager[None]:
        """Return an atomic context on this alias; nested use preserves isolation."""

        return transaction.atomic(using=self._using)

    def now(self) -> datetime:
        """Sample PostgreSQL wall time for validation and record clocks only."""

        return self._database_now()

    def require_caller_owned_current_uow(self) -> None:
        """Require one ambient same-alias PostgreSQL READ COMMITTED transaction."""

        connection = connections[self._using]
        _require_single_read_committed_uow(connection, self._using)

    def lock_current_scopes(
        self,
        scopes: tuple[tuple[FinancialAvailabilityRecordKind, str], ...],
    ) -> None:
        """Acquire shared C2 scope locks before any current row/event selection."""

        self.require_caller_owned_current_uow()
        if type(scopes) is not tuple or not scopes:
            raise DataValidationError(
                "C2 current resolution requires explicit scopes.",
                code="FIN_AVAILABILITY_CURRENT_SCOPE_INVALID",
            )
        keys = tuple(_scope_lock_key(kind, exchange) for kind, exchange in scopes)
        try:
            try_acquire_scoped_advisory_shared(using=self._using, keys=keys)
        except ScopedAdvisoryLockUnavailableError as error:
            raise DataValidationError(
                "C2 current scope is being changed by another transaction.",
                code="FIN_AVAILABILITY_SCOPE_LOCK_BUSY",
            ) from error

    def lock_change_scope(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
    ) -> None:
        """Acquire the scope's exclusive lock before apply or revoke appends."""

        _lock_change_scope(self._using, kind, exchange)

    def _database_now(self) -> datetime:
        """Read ``clock_timestamp`` without using transaction start as a cutoff."""

        with connections[self._using].cursor() as cursor:
            cursor.execute("SELECT clock_timestamp()")
            row = cursor.fetchone()
        if row is None:
            raise ExternalServiceError("C2 database clock is unavailable.")
        return _utc(row[0], "database_clock")

    def append_record(
        self,
        record: FinancialAvailabilityGovernanceRecord,
    ) -> FinancialAvailabilityGovernanceRecord:
        """Stamp the row with actual DB wall time and append exact record payload.

        The input value supplies the reviewed configuration fields. Its
        ``recorded_at`` is not persisted as an externally supplied source
        clock; this repository samples a fresh database clock and returns the
        resulting record whose row and policy hashes bind that clock.
        """

        _require_read_committed_uow(self._using)
        if type(record) is not FinancialAvailabilityGovernanceRecord:
            raise DataValidationError("C2 append requires an exact typed record.")
        try:
            record.__post_init__()
            self.lock_change_scope(kind=record.kind, exchange=record.exchange)
            persisted = _restamp_record(record, recorded_at=self._database_now())
        except (TypeError, ValueError) as error:
            raise DataValidationError("C2 configuration value is invalid.") from error
        source_capture = (
            _verify_source_capture_row(persisted.source, using=self._using)
            if persisted.source is not None
            else None
        )
        row = FinancialAvailabilityGovernanceRecordModel(
            record_id=persisted.record_id,
            record_version=persisted.record_version,
            exchange=persisted.exchange,
            kind=persisted.kind.value,
            payload=_record_payload(persisted),
            content_sha256=persisted.content_sha256,
            recorded_at=persisted.recorded_at,
            source_capture=source_capture,
        )
        try:
            row.save(force_insert=True, using=self._using)
        except IntegrityError as error:
            raise DataValidationError("C2 configuration version already exists.") from error
        return _decode_record_row(row)

    def get_exact(
        self,
        *,
        record_id: str,
        record_version: str,
        expected_content_sha256: str,
        known_at: datetime,
    ) -> FinancialAvailabilityGovernanceRecord | None:
        """Read one exact version visible at cutoff and rehash its full payload."""

        cutoff = _utc(known_at, "known_at")
        rows = tuple(
            FinancialAvailabilityGovernanceRecordModel._default_manager.using(self._using).filter(
                record_id=record_id,
                record_version=record_version,
                recorded_at__lte=cutoff,
            )[:2]
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise DataValidationError("C2 exact configuration selector is ambiguous.")
        record = _decode_record_row(rows[0])
        if record.content_sha256 != expected_content_sha256:
            raise DataValidationError("C2 exact configuration hash differs from the selector.")
        return record

    def list_for_effective_date(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
        effective_on: date,
        known_at: datetime,
    ) -> tuple[FinancialAvailabilityGovernanceRecord, ...]:
        """Return all scope rows recorded by cutoff without choosing a winner."""

        if type(kind) is not FinancialAvailabilityRecordKind:
            raise DataValidationError("C2 record kind selector is invalid.")
        if (
            type(exchange) is not str
            or not exchange
            or exchange.strip() != exchange
            or type(effective_on) is not date
        ):
            raise DataValidationError("C2 effective scope selector is invalid.")
        cutoff = _utc(known_at, "known_at")
        rows = (
            FinancialAvailabilityGovernanceRecordModel._default_manager.using(self._using)
            .filter(kind=kind.value, exchange=exchange, recorded_at__lte=cutoff)
            .order_by("record_id", "record_version", "row_id")
        )
        return tuple(_decode_record_row(row) for row in rows)

    def list_scope_for_current_update(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
    ) -> tuple[FinancialAvailabilityGovernanceRecord, ...]:
        """Lock every immutable scope row and rebuild its exact typed identity."""

        self.require_caller_owned_current_uow()
        if type(kind) is not FinancialAvailabilityRecordKind:
            raise DataValidationError(
                "C2 current record kind is invalid.",
                code="FIN_AVAILABILITY_CURRENT_SCOPE_INVALID",
            )
        if type(exchange) is not str or not exchange or exchange.strip() != exchange:
            raise DataValidationError(
                "C2 current exchange is invalid.",
                code="FIN_AVAILABILITY_CURRENT_SCOPE_INVALID",
            )
        rows = (
            FinancialAvailabilityGovernanceRecordModel._default_manager.using(self._using)
            .select_for_update()
            .filter(kind=kind.value, exchange=exchange)
            .order_by("record_id", "record_version", "row_id")
        )
        return tuple(_decode_record_row(row) for row in rows)


class DjangoFinancialAvailabilityOwnerEventRepository:
    """Append and verify the local C2 apply/revoke lifecycle event stream."""

    def __init__(
        self,
        *,
        using: str,
        source_reader: FinancialAvailabilitySourceReaderPort,
    ) -> None:
        """Bind Owner events and exact source rereads to the same alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataValidationError("C2 Owner event repository requires one explicit alias.")
        if source_reader.database_alias != using:
            raise DataValidationError("C2 source reader and Owner events use different aliases.")
        self._using = using
        self._source_reader = source_reader

    @property
    def database_alias(self) -> str:
        """Return the alias holding configuration and Owner event rows."""

        return self._using

    def append_apply_event(
        self,
        *,
        record: FinancialAvailabilityGovernanceRecord,
        principal: LockedFinancialAvailabilityPrincipal,
        reason: str,
        known_at: datetime,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        """Append one Owner apply event after exact source and actor revalidation."""

        _require_read_committed_uow(self._using)
        lease = _require_local_principal(principal, self._using)
        _lock_change_scope(self._using, record.kind, record.exchange)
        cutoff = _utc(known_at, "known_at")
        if cutoff > _db_clock(self._using):
            raise DataValidationError("C2 Owner source cutoff is in the future.")
        if record.kind is FinancialAvailabilityRecordKind.OPENING_RULE:
            source = record.source
            if source is None:
                raise DataValidationError("C2 opening rule has no exact source capture.")
            source_read = self._source_reader.read_exact_capture(
                issuer=source.issuer,
                document_id=source.document_id,
                source_version=source.source_version,
                capture_id=source.capture_id,
                known_at=cutoff,
            )
            if source_read is None or type(source_read) is not FinancialAvailabilitySourceRead:
                raise DataValidationError("C2 exact official source is unavailable at cutoff.")
            try:
                source_read.__post_init__()
            except (TypeError, ValueError) as error:
                raise DataValidationError(
                    "C2 exact official source read failed validation."
                ) from error
            if source_read.reference != source:
                raise DataValidationError("C2 exact official source identity changed at cutoff.")
        lease.assert_live()
        record_row = _lock_exact_record(record, using=self._using)
        existing = tuple(
            FinancialAvailabilityOwnerEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(governance_record=record_row)
            .order_by("event_id")[:2]
        )
        if existing:
            raise DataValidationError("C2 configuration already has an Owner lifecycle event.")
        occurred_at = _db_clock(self._using)
        resulting_hash = record.resulting_content_sha256(approved_at=occurred_at)
        recorded_at = _db_clock(self._using)
        event = FinancialAvailabilityOwnerEventIdentity.create(
            action=FinancialAvailabilityOwnerEventAction.APPLY,
            event_id=uuid4(),
            record=record,
            resulting_content_sha256=resulting_hash,
            actor_user_id=lease.user_id,
            permission_id=lease.permission_id,
            permission_verified_at=lease.verified_at,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            reason=reason,
        )
        _append_event_row(
            event,
            record_row=record_row,
            actor_user_id=lease.user_id,
            permission_id=lease.permission_id,
            using=self._using,
        )
        lease.assert_live()
        return event

    def append_revoke_event(
        self,
        *,
        record: FinancialAvailabilityGovernanceRecord,
        apply_event: FinancialAvailabilityOwnerEventIdentity,
        principal: LockedFinancialAvailabilityPrincipal,
        reason: str,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        """Append one revoke linked to a stored exact apply event, without mutation."""

        _require_read_committed_uow(self._using)
        lease = _require_local_principal(principal, self._using)
        _lock_change_scope(self._using, record.kind, record.exchange)
        record_row = _lock_exact_record(record, using=self._using)
        try:
            apply_row = (
                FinancialAvailabilityOwnerEventModel._default_manager.using(self._using)
                .select_for_update()
                .select_related("governance_record", "actor", "permission__content_type")
                .get(event_id=apply_event.event_id, governance_record=record_row, action="apply")
            )
        except FinancialAvailabilityOwnerEventModel.DoesNotExist as error:
            raise DataValidationError("C2 revoke must reference one stored apply event.") from error
        stored_apply = _decode_event_row(apply_row, using=self._using)
        if stored_apply != apply_event:
            raise DataValidationError("C2 revoke selector differs from stored apply evidence.")
        existing_revoke = (
            FinancialAvailabilityOwnerEventModel._default_manager.using(self._using)
            .select_for_update()
            .filter(governance_record=record_row, action="revoke")
            .exists()
        )
        if existing_revoke:
            raise DataValidationError("C2 configuration already has a revoke event.")
        lease.assert_live()
        occurred_at = _db_clock(self._using)
        recorded_at = _db_clock(self._using)
        event = FinancialAvailabilityOwnerEventIdentity.create(
            action=FinancialAvailabilityOwnerEventAction.REVOKE,
            event_id=uuid4(),
            record=record,
            resulting_content_sha256=stored_apply.resulting_content_sha256,
            actor_user_id=lease.user_id,
            permission_id=lease.permission_id,
            permission_verified_at=lease.verified_at,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            reason=reason,
            predecessor_apply_event_id=stored_apply.event_id,
            predecessor_apply_event_sha256=stored_apply.event_sha256,
        )
        _append_event_row(
            event,
            record_row=record_row,
            actor_user_id=lease.user_id,
            permission_id=lease.permission_id,
            predecessor_apply_event=apply_row,
            using=self._using,
        )
        lease.assert_live()
        return event

    def list_complete_history(
        self,
        *,
        record_id: str,
        record_version: str,
    ) -> tuple[FinancialAvailabilityOwnerEventIdentity, ...]:
        """Read every event for one record and revalidate its real User/Permission FKs."""

        rows = (
            FinancialAvailabilityOwnerEventModel._default_manager.using(self._using)
            .select_related(
                "governance_record",
                "actor",
                "permission__content_type",
                "predecessor_apply_event",
            )
            .filter(
                governance_record__record_id=record_id,
                governance_record__record_version=record_version,
            )
            .order_by("recorded_at", "event_id")
        )
        return tuple(_decode_event_row(row, using=self._using) for row in rows)

    def list_complete_history_for_update(
        self,
        *,
        record_id: str,
        record_version: str,
    ) -> tuple[FinancialAvailabilityOwnerEventIdentity, ...]:
        """Lock and re-decode the complete current lifecycle stream for a row."""

        _require_single_read_committed_uow(connections[self._using], self._using)
        rows = (
            FinancialAvailabilityOwnerEventModel._default_manager.using(self._using)
            .select_for_update(of=("self",))
            .select_related(
                "governance_record",
                "actor",
                "permission__content_type",
                "predecessor_apply_event",
            )
            .filter(
                governance_record__record_id=record_id,
                governance_record__record_version=record_version,
            )
            .order_by("recorded_at", "event_id")
        )
        return tuple(_decode_event_row(row, using=self._using) for row in rows)


def _scope_lock_key(
    kind: FinancialAvailabilityRecordKind,
    exchange: str,
) -> ScopedAdvisoryLockKey:
    """Build the shared stable key for C2 current reads, apply and revoke."""

    if type(kind) is not FinancialAvailabilityRecordKind:
        raise DataValidationError(
            "C2 scope kind is invalid.", code="FIN_AVAILABILITY_CURRENT_SCOPE_INVALID"
        )
    if type(exchange) is not str or not exchange or exchange.strip() != exchange:
        raise DataValidationError(
            "C2 scope exchange is invalid.", code="FIN_AVAILABILITY_CURRENT_SCOPE_INVALID"
        )
    return ScopedAdvisoryLockKey(
        domain=_FINANCIAL_AVAILABILITY_SCOPE_LOCK_DOMAIN,
        components=(kind.value, exchange),
    )


def _restamp_record(
    record: FinancialAvailabilityGovernanceRecord,
    *,
    recorded_at: datetime,
) -> FinancialAvailabilityGovernanceRecord:
    """Rebuild exact row and policy hashes from the actual insert-time clock."""

    clock = _utc(recorded_at, "recorded_at")
    content: FinancialAvailabilityContent = record.content
    if type(content) is FinancialDisclosureAvailabilityPolicy:
        content = FinancialDisclosureAvailabilityPolicy.create(
            policy_id=content.policy_id,
            policy_version=content.policy_version,
            exchange=content.exchange,
            opening_phase=content.opening_phase,
            effective_start=content.effective_start,
            effective_end=content.effective_end,
            calendar_response_max_age_seconds=content.calendar_response_max_age_seconds,
            first_seen_at=content.first_seen_at,
            recorded_at=clock,
        )
    persisted = replace(record, content=content, recorded_at=clock)
    persisted.__post_init__()
    return persisted


def _db_clock(using: str) -> datetime:
    """Sample actual PostgreSQL wall time for an Owner event clock."""

    with connections[using].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    if row is None:
        raise ExternalServiceError("C2 Owner event clock is unavailable.")
    return _utc(row[0], "owner_event_database_clock")


def _lock_exact_record(
    record: FinancialAvailabilityGovernanceRecord,
    *,
    using: str,
) -> FinancialAvailabilityGovernanceRecordModel:
    """Lock and rehash the exact persisted row before lifecycle append."""

    try:
        row = (
            FinancialAvailabilityGovernanceRecordModel._default_manager.using(using)
            .select_for_update()
            .get(
                record_id=record.record_id,
                record_version=record.record_version,
                content_sha256=record.content_sha256,
            )
        )
    except FinancialAvailabilityGovernanceRecordModel.DoesNotExist as error:
        raise DataValidationError(
            "C2 Owner event references no exact persisted version."
        ) from error
    if _decode_record_row(row) != record:
        raise DataValidationError("C2 Owner event input differs from its persisted version.")
    return row


def _require_local_principal(
    principal: LockedFinancialAvailabilityPrincipal,
    using: str,
) -> _FinancialAvailabilityPrincipalLease:
    """Reject hand-built principals and require this writer's live authority lease."""

    if type(principal) is not _FinancialAvailabilityPrincipalLease:
        raise AuthorizationError("C2 Owner event requires the live Django User lease.")
    principal.assert_live()
    if (
        principal.database_alias != using
        or principal.permission_app_label != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL
        or principal.permission_codename != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME
    ):
        raise AuthorizationError("C2 Owner lease is bound to another permission or database.")
    return principal


def _append_event_row(
    event: FinancialAvailabilityOwnerEventIdentity,
    *,
    record_row: FinancialAvailabilityGovernanceRecordModel,
    actor_user_id: int,
    permission_id: int,
    using: str,
    predecessor_apply_event: FinancialAvailabilityOwnerEventModel | None = None,
) -> None:
    """Persist one typed event using only locked, real FK identities."""

    raw = serialize_financial_availability_owner_event(event)
    decoded = deserialize_financial_availability_owner_event(raw)
    if decoded != event:
        raise DataValidationError("C2 Owner event failed strict codec self-check.")
    row = FinancialAvailabilityOwnerEventModel(
        event_id=event.event_id,
        governance_record=record_row,
        action=event.action.value,
        event_sha256=event.event_sha256,
        record_content_sha256=event.record_content_sha256,
        resulting_content_sha256=event.resulting_content_sha256,
        actor_id=actor_user_id,
        permission_id=permission_id,
        permission_app_label=event.permission_app_label,
        permission_codename=event.permission_codename,
        permission_verified_at=event.permission_verified_at,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        reason=event.reason,
        predecessor_apply_event=predecessor_apply_event,
        predecessor_apply_event_sha256=event.predecessor_apply_event_sha256,
    )
    try:
        row.save(force_insert=True, using=using)
    except IntegrityError as error:
        raise DataValidationError(
            "C2 Owner event is duplicate or violates row identity."
        ) from error


def _decode_event_row(
    row: FinancialAvailabilityOwnerEventModel,
    *,
    using: str,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Rebuild and rehash one event while checking its User and Permission FKs."""

    record = _decode_record_row(row.governance_record)
    if (
        row._state.db != using
        or row.governance_record._state.db != using
        or row.actor._state.db != using
        or row.permission._state.db != using
    ):
        raise DataValidationError("C2 Owner event FK rows cross the configured alias.")
    permission_content_type = row.permission.content_type
    if (
        permission_content_type._state.db != using
        or permission_content_type.app_label
        != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL
        or permission_content_type.model
        != FinancialAvailabilityGovernanceRecordModel._meta.model_name
        or row.permission.codename != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME
        or row.permission_app_label != permission_content_type.app_label
        or row.permission_codename != row.permission.codename
        or record.record_id != row.governance_record.record_id
        or record.record_version != row.governance_record.record_version
        or record.content_sha256 != row.record_content_sha256
    ):
        raise DataValidationError("C2 Owner event FK identity differs from the recorded snapshot.")
    predecessor_id = None
    if row.predecessor_apply_event_id is not None:
        predecessor = row.predecessor_apply_event
        if predecessor is None:
            raise DataValidationError("C2 revoke is missing its exact apply event.")
        predecessor_id = predecessor.event_id
        if (
            predecessor.action != FinancialAvailabilityOwnerEventModel.APPLY
            or predecessor.governance_record_id != row.governance_record_id
            or predecessor.event_sha256 != row.predecessor_apply_event_sha256
        ):
            raise DataValidationError("C2 revoke FK differs from its exact apply event.")
    payload: dict[str, object] = {
        "schema": "data_center.financial-availability-owner-event.v1",
        "action": row.action,
        "event_id": str(row.event_id),
        "event_sha256": row.event_sha256,
        "record_id": record.record_id,
        "record_version": record.record_version,
        "record_content_sha256": row.record_content_sha256,
        "resulting_content_sha256": row.resulting_content_sha256,
        "actor_user_id": row.actor_id,
        "permission_id": row.permission_id,
        "permission_app_label": row.permission_app_label,
        "permission_codename": row.permission_codename,
        "permission_verified_at": _utc(
            row.permission_verified_at, "event.permission_verified_at"
        ).isoformat(timespec="microseconds"),
        "occurred_at": _utc(row.occurred_at, "event.occurred_at").isoformat(
            timespec="microseconds"
        ),
        "recorded_at": _utc(row.recorded_at, "event.recorded_at").isoformat(
            timespec="microseconds"
        ),
        "reason": row.reason,
        "predecessor_apply_event_id": str(predecessor_id) if predecessor_id is not None else None,
        "predecessor_apply_event_sha256": row.predecessor_apply_event_sha256,
    }
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        event = deserialize_financial_availability_owner_event(raw)
    except (TypeError, ValueError, UnicodeError) as error:
        raise DataValidationError("Stored C2 Owner event failed exact codec validation.") from error
    if event.actor_user_id != row.actor_id or event.permission_id != row.permission_id:
        raise DataValidationError("Stored C2 Owner event FK IDs changed.")
    return event


__all__ = [
    "DjangoFinancialAvailabilityGovernanceRepository",
    "DjangoFinancialAvailabilityOwnerEventRepository",
]
