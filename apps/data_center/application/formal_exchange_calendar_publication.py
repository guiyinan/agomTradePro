"""Application ports for formal exchange-calendar publication and exact reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
    CalendarFormalPublicationSeal,
    CalendarPublicationPointerExpectation,
    CalendarPublicationTransition,
    calendar_formal_seals_have_same_evidence,
    exchange_calendar_publication_key,
    validate_current_calendar_publication,
)
from core.exceptions import DataValidationError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")


class CalendarFormalPublicationApplicationError(DataValidationError):
    """Typed fail-closed error for formal calendar publication application ports."""

    default_message = "Formal exchange-calendar publication validation failed"
    default_code = "CALENDAR_FORMAL_PUBLICATION_INVALID"

    def __init__(self, message: str, *, code: str) -> None:
        """Expose a stable application code through the project exception hierarchy."""

        super().__init__(message, code=code, status_code=422)


@dataclass(frozen=True, slots=True)
class CalendarFormalPublicationRequest:
    """Propose one sealed snapshot under an explicit expected pointer identity."""

    proposed_seal: CalendarFormalPublicationSeal
    expected_pointer: CalendarPublicationPointerExpectation
    activation_id: str

    def __post_init__(self) -> None:
        """Reject scope drift or malformed CAS inputs before repository access."""

        self.validate()

    @property
    def dataset_key(self) -> str:
        """Return the exact contract dataset key sealed into the proposal."""

        self.validate()
        return self.proposed_seal.dataset.value

    @property
    def exchange(self) -> str:
        """Return the exact exchange token sealed into the proposal."""

        self.validate()
        return self.proposed_seal.exchange

    @property
    def publication_key(self) -> str:
        """Return the exact exchange-scoped canonical pointer key."""

        self.validate()
        return self.proposed_seal.publication_key

    def validate(self) -> None:
        """Revalidate nested frozen values at the Application trust boundary."""

        if type(self.proposed_seal) is not CalendarFormalPublicationSeal:
            raise CalendarFormalPublicationApplicationError(
                "proposal must be a typed formal calendar seal",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        if type(self.expected_pointer) is not CalendarPublicationPointerExpectation:
            raise CalendarFormalPublicationApplicationError(
                "expected pointer must be a typed pointer expectation",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        try:
            self.proposed_seal.validate()
            self.expected_pointer.validate()
        except CalendarFormalPublicationError as error:
            raise _from_domain_error(error) from error
        if (
            type(self.activation_id) is not str
            or _TEXT_TOKEN_RE.fullmatch(self.activation_id) is None
        ):
            raise CalendarFormalPublicationApplicationError(
                "activation_id must be a canonical bounded token",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        expected_scope = (self.proposed_seal.dataset.value, self.proposed_seal.publication_key)
        actual_scope = (
            self.expected_pointer.dataset_key,
            self.expected_pointer.publication_key,
        )
        if expected_scope != actual_scope:
            raise CalendarFormalPublicationApplicationError(
                "expected pointer belongs to another dataset or exchange",
                code="CALENDAR_PUBLICATION_REQUEST_SCOPE_INVALID",
            )


@dataclass(frozen=True, slots=True)
class CalendarPublicationAuditPair:
    """Receipt proving the exact published event and outbox share one identity."""

    database_alias: str
    dataset_key: str
    exchange: str
    publication_id: str
    publication_hash: str
    event_id: str
    event_content_hash: str
    actor_user_id: int
    outbox_id: UUID
    idempotency_key: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject partial event/outbox receipts or mismatched publication identity."""

        for field_name in ("database_alias", "dataset_key", "exchange", "event_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value.strip() != value:
                raise CalendarFormalPublicationApplicationError(
                    f"Audit receipt {field_name} is invalid",
                    code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
                )
        for field_name in ("publication_id",):
            _require_uuid(getattr(self, field_name), field_name)
        _require_sha256(self.publication_hash, "publication_hash")
        _require_sha256(self.event_content_hash, "event_content_hash")
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise CalendarFormalPublicationApplicationError(
                "Audit receipt publisher identity is invalid",
                code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
            )
        if type(self.outbox_id) is not UUID:
            raise CalendarFormalPublicationApplicationError(
                "Audit receipt outbox id must be a UUID",
                code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
            )
        if (
            type(self.idempotency_key) is not str
            or self.idempotency_key != self.event_id
            or _TEXT_TOKEN_RE.fullmatch(self.idempotency_key) is None
        ):
            raise CalendarFormalPublicationApplicationError(
                "Audit event and outbox idempotency identities differ",
                code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
            )
        _require_utc(self.recorded_at, "Audit recorded_at")


@dataclass(frozen=True, slots=True)
class CalendarFormalPublicationCommit:
    """Verified current publication, pointer, paired Audit receipt, and final clock."""

    record: CalendarFormalPublicationRecord
    pointer: CalendarPublicationPointerExpectation
    transition: CalendarPublicationTransition
    audit_pair: CalendarPublicationAuditPair
    post_audit_checked_at: datetime

    def __post_init__(self) -> None:
        """Require the returned commit to be current, exact, and still within TTL."""

        if type(self.record) is not CalendarFormalPublicationRecord:
            raise CalendarFormalPublicationApplicationError(
                "repository returned an invalid publication record",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        if type(self.pointer) is not CalendarPublicationPointerExpectation:
            raise CalendarFormalPublicationApplicationError(
                "repository returned an invalid pointer identity",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        if type(self.transition) is not CalendarPublicationTransition:
            raise CalendarFormalPublicationApplicationError(
                "repository returned an invalid transition",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        if type(self.audit_pair) is not CalendarPublicationAuditPair:
            raise CalendarFormalPublicationApplicationError(
                "repository returned no exact Audit event/outbox pair",
                code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
            )
        try:
            self.record.validate()
            self.pointer.validate()
            self.audit_pair.__post_init__()
        except CalendarFormalPublicationError as error:
            raise _from_domain_error(error) from error
        if self.record.lifecycle is not CalendarPublicationLifecycle.PUBLISHED:
            raise CalendarFormalPublicationApplicationError(
                "commit must identify the current published lifecycle",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        if (
            self.pointer.dataset_key != self.record.seal.dataset.value
            or self.pointer.publication_key != self.record.seal.publication_key
            or self.pointer.publication_id != self.record.publication_id
            or self.pointer.publication_hash != self.record.seal.publication_hash
            or self.pointer.activation_id != self.record.activation_id
            or self.pointer.updated_at != self.record.published_at
        ):
            raise CalendarFormalPublicationApplicationError(
                "pointer does not identify the exact publication commit",
                code="CALENDAR_PUBLICATION_POINTER_BINDING_INVALID",
            )
        if (
            self.audit_pair.dataset_key != self.record.seal.dataset.value
            or self.audit_pair.exchange != self.record.seal.exchange
            or self.audit_pair.publication_id != self.record.publication_id
            or self.audit_pair.publication_hash != self.record.seal.publication_hash
            or self.audit_pair.recorded_at != self.record.published_at
        ):
            raise CalendarFormalPublicationApplicationError(
                "Audit event/outbox receipt does not bind the exact publication and time",
                code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
            )
        _require_utc(self.post_audit_checked_at, "post_audit_checked_at")
        if self.post_audit_checked_at < self.record.published_at:
            raise CalendarFormalPublicationApplicationError(
                "post-Audit clock precedes the publication knowledge time",
                code="CALENDAR_PUBLICATION_POST_AUDIT_TIME_INVALID",
            )
        try:
            if not self.record.is_effective_at(self.post_audit_checked_at):
                raise CalendarFormalPublicationApplicationError(
                    "calendar response TTL expired before the transaction could commit",
                    code="CALENDAR_FORMAL_TTL_EXPIRED",
                )
        except CalendarFormalPublicationError as error:
            raise _from_domain_error(error) from error

    @property
    def must_not_execute(self) -> bool:
        """Return the fixed non-execution capability of this publication receipt."""

        return True


class CalendarFormalPublicationWriterPort(Protocol):
    """Same-alias writer joining the locked publisher's outer transaction."""

    def publish(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Revalidate catalog/source/CAS and commit exact Audit/outbox evidence.

        Infrastructure must not open a nested transaction. New and forward
        publication revalidate source TTL after Audit I/O and propagate failures
        so the authority-owned outer transaction rolls back. An exact-current
        replay must re-read the complete old event/outbox/pointer winner and
        return its original clocks and ids; it must never append or repair a
        missing Audit half.
        """


class PublishExchangeCalendarSnapshotUseCase:
    """Publish one exact sealed snapshot under a live session permission lease."""

    def __init__(self, writer: CalendarFormalPublicationWriterPort) -> None:
        """Bind the use case to an explicit formal-calendar writer port."""

        self._writer = writer

    def execute(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Delegate one exact publication without swallowing transaction failures."""

        if type(request) is not CalendarFormalPublicationRequest:
            raise CalendarFormalPublicationApplicationError(
                "publish requires a typed request",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        request.validate()
        _validate_principal_fields(principal)
        _assert_principal_live(principal)
        commit = self._writer.publish(request, principal=principal)
        _validate_principal_fields(principal)
        _assert_principal_live(principal)
        if type(commit) is not CalendarFormalPublicationCommit:
            raise CalendarFormalPublicationApplicationError(
                "writer returned no typed publication commit",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        commit.__post_init__()
        if commit.audit_pair.database_alias != principal.database_alias:
            raise CalendarFormalPublicationApplicationError(
                "Audit event/outbox and publisher authority use different database aliases",
                code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
            )
        if (
            not calendar_formal_seals_have_same_evidence(commit.record.seal, request.proposed_seal)
            or commit.record.activation_id != request.activation_id
            or commit.pointer.dataset_key != request.dataset_key
            or commit.pointer.publication_key != request.publication_key
        ):
            raise CalendarFormalPublicationApplicationError(
                "writer returned a different proposal or pointer scope",
                code="CALENDAR_PUBLICATION_COMMIT_BINDING_INVALID",
            )
        if commit.transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if not request.expected_pointer.is_absent:
                raise CalendarFormalPublicationApplicationError(
                    "first publication requires the exact absent-pointer expectation",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
        elif request.expected_pointer.is_absent:
            raise CalendarFormalPublicationApplicationError(
                "forward publication or replay requires an existing pointer expectation",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )
        elif (
            commit.transition is CalendarPublicationTransition.FORWARD_PUBLISH
            and commit.pointer == request.expected_pointer
        ):
            raise CalendarFormalPublicationApplicationError(
                "forward publication did not advance the expected pointer identity",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )
        if commit.transition is CalendarPublicationTransition.FORWARD_PUBLISH:
            if commit.pointer.pointer_id != request.expected_pointer.pointer_id:
                raise CalendarFormalPublicationApplicationError(
                    "forward publication must update the existing pointer row",
                    code="CALENDAR_PUBLICATION_POINTER_BINDING_INVALID",
                )
            previous_time = request.expected_pointer.updated_at
            if previous_time is None or commit.record.published_at <= previous_time:
                raise CalendarFormalPublicationApplicationError(
                    "forward publication time must advance beyond the previous pointer",
                    code="CALENDAR_PUBLICATION_FORWARD_TIME_INVALID",
                )
        if commit.post_audit_checked_at < principal.verified_at:
            raise CalendarFormalPublicationApplicationError(
                "post-Audit verification clock precedes locked publisher verification",
                code="CALENDAR_PUBLICATION_POST_AUDIT_TIME_INVALID",
            )
        if commit.transition is not CalendarPublicationTransition.EXACT_CURRENT_REPLAY:
            if commit.record.published_at < principal.verified_at:
                raise CalendarFormalPublicationApplicationError(
                    "new publication knowledge time precedes locked authority verification",
                    code="CALENDAR_PUBLICATION_AUTHORITY_TIME_INVALID",
                )
        elif commit.pointer != request.expected_pointer:
            raise CalendarFormalPublicationApplicationError(
                "exact-current replay must preserve the complete expected pointer epoch",
                code="CALENDAR_CURRENT_REPLAY_MISMATCH",
            )
        if commit.audit_pair.actor_user_id != principal.user_id:
            raise CalendarFormalPublicationApplicationError(
                "publisher identity differs from the actor bound to the stored event",
                code="CALENDAR_PUBLICATION_AUDIT_ACTOR_MISMATCH",
            )
        return commit


@dataclass(frozen=True, slots=True)
class ReadCurrentExchangeCalendarPublicationQuery:
    """Request an exact current-pointer calendar read at an aware UTC cutoff."""

    dataset_key: str
    exchange: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Require an exact dataset/exchange scope without a latest fallback."""

        if (
            type(self.dataset_key) is not str
            or not self.dataset_key
            or self.dataset_key.strip() != self.dataset_key
            or len(self.dataset_key) > 160
            or any(character.isspace() for character in self.dataset_key)
        ):
            raise CalendarFormalPublicationApplicationError(
                "dataset_key must be explicit",
                code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            )
        try:
            expected_key = exchange_calendar_publication_key(self.exchange)
        except CalendarFormalPublicationError as error:
            raise _from_domain_error(error) from error
        if not expected_key:
            raise CalendarFormalPublicationApplicationError(
                "exchange must be explicit",
                code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            )
        _require_utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class CurrentPublishedExchangeCalendar:
    """Exact current publication and its validity checked at one cutoff.

    This result describes formal calendar reference data only. It does not
    describe an intraday session, a security's trading status, or broker
    execution authorization. The reader does not reconstruct historical
    pointer state from superseded publication rows.
    """

    record: CalendarFormalPublicationRecord
    pointer: CalendarPublicationPointerExpectation
    as_of: datetime

    def __post_init__(self) -> None:
        """Require the persisted current winner and exact pointer to agree."""

        try:
            validate_current_calendar_publication(self.record, self.pointer, as_of=self.as_of)
        except CalendarFormalPublicationError as error:
            raise _from_domain_error(error) from error

    @property
    def must_not_execute(self) -> bool:
        """Return the fixed capability boundary of a calendar reference read."""

        return True


class CalendarCurrentPublicationReaderPort(Protocol):
    """Exact-current pointer reader with no latest or historical fallback."""

    def read_current(
        self,
        query: ReadCurrentExchangeCalendarPublicationQuery,
    ) -> CurrentPublishedExchangeCalendar | None:
        """Return the pointer's exact current record, or None when no pointer exists."""


class ReadCurrentExchangeCalendarPublicationUseCase:
    """Read one currently pointed formal calendar publication without PIT claims."""

    def __init__(self, reader: CalendarCurrentPublicationReaderPort) -> None:
        """Bind the read use case to an explicit current-pointer reader."""

        self._reader = reader

    def execute(
        self,
        query: ReadCurrentExchangeCalendarPublicationQuery,
    ) -> CurrentPublishedExchangeCalendar:
        """Return only the exact current pointer that remains effective at cutoff."""

        if type(query) is not ReadCurrentExchangeCalendarPublicationQuery:
            raise CalendarFormalPublicationApplicationError(
                "read requires a typed exact-current query",
                code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            )
        query.__post_init__()
        result = self._reader.read_current(query)
        if result is None:
            raise CalendarFormalPublicationApplicationError(
                "no exact current exchange-calendar publication is available",
                code="CALENDAR_CURRENT_PUBLICATION_MISSING",
            )
        if type(result) is not CurrentPublishedExchangeCalendar:
            raise CalendarFormalPublicationApplicationError(
                "reader returned an invalid current calendar result",
                code="CALENDAR_CURRENT_READ_RESULT_INVALID",
            )
        result.__post_init__()
        if (
            result.record.seal.dataset.value != query.dataset_key
            or result.record.seal.exchange != query.exchange
            or result.as_of != query.as_of
        ):
            raise CalendarFormalPublicationApplicationError(
                "reader returned another dataset, exchange, or cutoff",
                code="CALENDAR_CURRENT_READ_SCOPE_MISMATCH",
            )
        return result


def _from_domain_error(
    error: CalendarFormalPublicationError,
) -> CalendarFormalPublicationApplicationError:
    """Preserve a stable Domain reason code in the Application exception type."""

    return CalendarFormalPublicationApplicationError(str(error), code=error.code)


def _validate_principal_fields(principal: LockedCalendarPublisherPrincipal) -> None:
    """Verify the locked session principal is exact before invoking a writer."""

    try:
        actor_type = principal.actor_type
        actor_id = principal.actor_id
        permission_codename = principal.permission_codename
        database_alias = principal.database_alias
        user_id = principal.user_id
        permission_id = principal.permission_id
        verified_at = principal.verified_at
    except (AttributeError, TypeError) as error:
        raise CalendarFormalPublicationApplicationError(
            "publisher principal is incomplete",
            code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
        ) from error
    if (
        type(actor_type) is not str
        or actor_type != "django_user"
        or type(user_id) is not int
        or user_id <= 0
        or type(actor_id) is not str
        or actor_id != f"django-user:{user_id}"
        or type(permission_codename) is not str
        or permission_codename != CALENDAR_PUBLISH_PERMISSION_CODENAME
        or type(permission_id) is not int
        or permission_id <= 0
        or type(database_alias) is not str
        or not database_alias
        or database_alias.strip() != database_alias
    ):
        raise CalendarFormalPublicationApplicationError(
            "publisher principal is not bound to the exact user, permission, and database",
            code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
        )
    _require_utc(verified_at, "principal.verified_at")


def _assert_principal_live(principal: LockedCalendarPublisherPrincipal) -> None:
    """Call the live-lock witness and reject a structurally absent capability."""

    try:
        assert_live = principal.assert_live
    except (AttributeError, TypeError) as error:
        raise CalendarFormalPublicationApplicationError(
            "publisher principal has no live-lock witness",
            code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
        ) from error
    if not callable(assert_live):
        raise CalendarFormalPublicationApplicationError(
            "publisher principal live-lock witness is not callable",
            code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
        )
    assert_live()


def _require_uuid(value: object, field_name: str) -> None:
    """Require a canonical UUID string for persisted publication identity."""

    if type(value) is not str:
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be a canonical UUID",
            code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
        )
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be a canonical UUID",
            code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
        ) from error
    if str(parsed) != value:
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be a canonical UUID",
            code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
        )


def _require_sha256(value: object, field_name: str) -> None:
    """Require one lowercase unprefixed SHA-256 receipt digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be a lowercase SHA-256 digest",
            code="CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID",
        )


def _require_utc(value: object, field_name: str) -> None:
    """Require an aware UTC instant without altering the caller's timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be an aware UTC instant",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )
    offset = value.utcoffset()
    if offset is None or offset != timedelta(0):
        raise CalendarFormalPublicationApplicationError(
            f"{field_name} must be an aware UTC instant",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )


__all__ = [
    "CalendarCurrentPublicationReaderPort",
    "CalendarFormalPublicationApplicationError",
    "CalendarFormalPublicationCommit",
    "CalendarFormalPublicationRequest",
    "CalendarFormalPublicationWriterPort",
    "CalendarPublicationAuditPair",
    "CalendarPublicationTransition",
    "CurrentPublishedExchangeCalendar",
    "PublishExchangeCalendarSnapshotUseCase",
    "ReadCurrentExchangeCalendarPublicationQuery",
    "ReadCurrentExchangeCalendarPublicationUseCase",
]
