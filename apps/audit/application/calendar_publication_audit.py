"""Application contracts for calendar-specific System Audit events and reads.

The module exposes typed builders and a query use case only. It deliberately
does not compose a Data Center publisher, permission provider, HTTP route, or
default reader authority.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
    SystemAuditEventOutboxCorruption,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_BLOCKED_REASON,
    CALENDAR_PUBLICATION_BLOCKED_DETAIL_SCHEMA,
    CALENDAR_PUBLICATION_BLOCKED_EVENT,
    CALENDAR_PUBLICATION_PUBLISHED_DETAIL_SCHEMA,
    CALENDAR_PUBLICATION_PUBLISHED_EVENT,
    CALENDAR_PUBLISH_PERMISSION,
    CALENDAR_PUBLISHED_REASON,
    CalendarPublicationAuditContractError,
    CalendarPublicationAuditEvidence,
    CalendarPublicationBlockedDetail,
    CalendarPublicationPublishedDetail,
    calendar_publication_event_identity,
    calendar_publication_stream_id,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from core.exceptions import (
    AgomTradeProException,
    AuthenticationError,
    AuthorizationError,
    BusinessLogicError,
    DuplicateResourceError,
    MissingConfigError,
)

CALENDAR_AUDIT_READ_PERMISSION = "view_exchange_calendar_publication_audit"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_READER_CONTEXT_CAPABILITY = object()


class CalendarPublicationAuditUnavailable(MissingConfigError):
    """Calendar audit composition or its exact data is unavailable."""

    default_message = "日历审计读取或原子写入能力不可用"
    default_code = "CALENDAR_PUBLICATION_AUDIT_UNAVAILABLE"
    default_status_code = 503


class CalendarPublicationAuditDenied(AuthorizationError):
    """The provider did not issue exact dataset/exchange read authority."""

    default_message = "没有读取该交易所日历审计的权限"
    default_code = "CALENDAR_PUBLICATION_AUDIT_DENIED"


class CalendarPublicationAuditConflict(DuplicateResourceError):
    """A request identity or event/outbox first winner conflicts."""

    default_message = "日历审计请求与已存在记录冲突"
    default_code = "CALENDAR_PUBLICATION_AUDIT_CONFLICT"


class CalendarPublicationAuditCorruption(AgomTradeProException):
    """Persisted calendar Audit event or outbox does not match its contract."""

    default_message = "日历审计记录或 Outbox 完整性校验失败"
    default_code = "CALENDAR_PUBLICATION_AUDIT_CORRUPTION"
    default_status_code = 500


class CalendarPublicationAuditValidationError(BusinessLogicError):
    """A caller supplied an invalid calendar Audit command or event."""

    default_message = "日历审计输入无效"
    default_code = "CALENDAR_PUBLICATION_AUDIT_VALIDATION_ERROR"


class CalendarAuditPublisherPrincipal(Protocol):
    """Lock-scoped session principal supplied by an authoritative provider."""

    @property
    def actor_type(self) -> str:
        """Return the authenticated actor kind while the lease is live."""

        ...

    @property
    def actor_id(self) -> str:
        """Return the canonical authenticated actor identifier."""

        ...

    @property
    def permission_codename(self) -> str:
        """Return the exact publication permission verified under lock."""

        ...

    @property
    def database_alias(self) -> str:
        """Return the alias holding the authorization lease."""

        ...

    @property
    def verified_at(self) -> datetime:
        """Return the aware time at which live permission was checked."""

        ...

    @property
    def user_id(self) -> int:
        """Return the locked authenticated user identifier."""

        ...

    def assert_live(self) -> None:
        """Reject use after the provider's locked authorization lease ends."""


class CalendarAuditEventFactory(Protocol):
    """Internal builder signature used after the exact stream head is locked."""

    def __call__(
        self,
        *,
        sequence_no: int,
        predecessor_hash: str | None,
    ) -> SystemAuditEvent:
        """Build one deterministic calendar event for the selected stream slot."""


@dataclass(frozen=True, slots=True)
class CalendarPublicationPublishedObservation:
    """Publication outcome and exact source evidence for the published event."""

    detail: CalendarPublicationPublishedDetail
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate the typed detail and server knowledge timestamp."""

        if type(self.detail) is not CalendarPublicationPublishedDetail:
            raise ValueError("detail must be CalendarPublicationPublishedDetail")
        CalendarPublicationPublishedDetail.__post_init__(self.detail)
        _require_utc(self.recorded_at, "recorded_at")
        if self.recorded_at < self.detail.snapshot_evidence.snapshot_recorded_at:
            raise ValueError("Audit recorded_at precedes the snapshot knowledge time")


@dataclass(frozen=True, slots=True)
class CalendarPublicationBlockedObservation:
    """Blocked publication attempt and optional exact candidate evidence."""

    detail: CalendarPublicationBlockedDetail
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate the typed detail and server knowledge timestamp."""

        if type(self.detail) is not CalendarPublicationBlockedDetail:
            raise ValueError("detail must be CalendarPublicationBlockedDetail")
        CalendarPublicationBlockedDetail.__post_init__(self.detail)
        _require_utc(self.recorded_at, "recorded_at")
        evidence = self.detail.snapshot_evidence
        if evidence is not None and self.recorded_at < evidence.snapshot_recorded_at:
            raise ValueError("Audit recorded_at precedes the candidate snapshot knowledge time")


def build_calendar_publication_published_event(
    observation: CalendarPublicationPublishedObservation,
    *,
    principal: CalendarAuditPublisherPrincipal,
    database_alias: str,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build the exact unscoped event for one published calendar snapshot."""

    observation = _validated_published_observation(observation)
    actor = _validated_publisher_actor(
        principal=principal,
        database_alias=database_alias,
        recorded_at=observation.recorded_at,
    )
    detail = observation.detail
    identity, idempotency_key = calendar_publication_event_identity(
        event_kind="published",
        dataset_key=detail.dataset_key,
        exchange=detail.exchange,
        request_identity=detail.publication_id,
    )
    evidence = detail.snapshot_evidence
    event = SystemAuditEvent.create(
        event_id=identity,
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=CALENDAR_PUBLICATION_PUBLISHED_EVENT,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.PUBLISHED,
        severity=AuditSeverity.INFO,
        reason_codes=(CALENDAR_PUBLISHED_REASON,),
        occurred_at=observation.recorded_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=actor,
        source_app="data_center",
        source_component="calendar_publication",
        source_surface="internal",
        correlations=AuditCorrelations(
            dataset_key=detail.dataset_key,
            capability="calendar.publication",
            publication_id=detail.publication_id,
            evidence_ref=_snapshot_correlation(evidence),
        ),
        resource=AuditResourceRef(
            "canonical_publication", detail.publication_id, detail.publication_hash
        ),
        dataset_key=detail.dataset_key,
        provider_key=None,
        capability="calendar.publication",
        publication_id=detail.publication_id,
        evidence_refs=(_audit_evidence_ref(evidence),),
        detail_schema=CALENDAR_PUBLICATION_PUBLISHED_DETAIL_SCHEMA,
        detail=detail.to_payload(),
        stream_id=calendar_publication_stream_id(detail.dataset_key, detail.exchange),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=idempotency_key,
        scope=None,
    )
    try:
        validate_calendar_publication_event(event)
    except CalendarPublicationAuditContractError as error:
        raise CalendarPublicationAuditValidationError(str(error), code=error.code) from error
    return event


def build_calendar_publication_blocked_event(
    observation: CalendarPublicationBlockedObservation,
    *,
    principal: CalendarAuditPublisherPrincipal,
    database_alias: str,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build the exact unscoped event for one blocked calendar request."""

    observation = _validated_blocked_observation(observation)
    actor = _validated_publisher_actor(
        principal=principal,
        database_alias=database_alias,
        recorded_at=observation.recorded_at,
    )
    detail = observation.detail
    identity, idempotency_key = calendar_publication_event_identity(
        event_kind="blocked",
        dataset_key=detail.dataset_key,
        exchange=detail.exchange,
        request_identity=detail.request_id,
    )
    evidence_ref = (
        _snapshot_correlation(detail.snapshot_evidence)
        if detail.snapshot_evidence is not None
        else f"calendar-publication-attempt:{detail.request_id}"
    )
    evidence_refs: tuple[AuditEvidenceRef, ...] = (
        (_audit_evidence_ref(detail.snapshot_evidence),)
        if detail.snapshot_evidence is not None
        else ()
    )
    resource = (
        AuditResourceRef("canonical_publication", detail.publication_id)
        if detail.publication_id is not None
        else AuditResourceRef("calendar_publication_attempt", detail.request_id)
    )
    event = SystemAuditEvent.create(
        event_id=identity,
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=CALENDAR_PUBLICATION_BLOCKED_EVENT,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.BLOCKED,
        severity=AuditSeverity.WARNING,
        reason_codes=(CALENDAR_BLOCKED_REASON,),
        occurred_at=observation.recorded_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=actor,
        source_app="data_center",
        source_component="calendar_publication",
        source_surface="internal",
        correlations=AuditCorrelations(
            request_id=detail.request_id,
            dataset_key=detail.dataset_key,
            capability="calendar.publication",
            publication_id=detail.publication_id,
            evidence_ref=evidence_ref,
        ),
        resource=resource,
        dataset_key=detail.dataset_key,
        provider_key=None,
        capability="calendar.publication",
        publication_id=detail.publication_id,
        evidence_refs=evidence_refs,
        detail_schema=CALENDAR_PUBLICATION_BLOCKED_DETAIL_SCHEMA,
        detail=detail.to_payload(),
        stream_id=calendar_publication_stream_id(detail.dataset_key, detail.exchange),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=idempotency_key,
        scope=None,
    )
    try:
        validate_calendar_publication_event(event)
    except CalendarPublicationAuditContractError as error:
        raise CalendarPublicationAuditValidationError(str(error), code=error.code) from error
    return event


class CalendarPublicationAuditReadAuthorityProvider(Protocol):
    """Trusted provider that holds live, selector-bound reader authority."""

    def lock_reader(
        self,
        *,
        request_proof: object,
        dataset_key: str,
        exchange: str,
        database_alias: str,
    ) -> AbstractContextManager[CalendarPublicationAuditReaderContext] | None:
        """Hold current permission locks across query and result verification.

        ``None`` means this process has no configured trusted reader provider.
        The event knowledge cutoff is deliberately absent: permission tables do
        not provide historical grant intervals.
        """


class CalendarPublicationAuditReaderRepository(Protocol):
    """Narrow exact selector for only the requested calendar event stream."""

    @property
    def database_alias(self) -> str:
        """Return the alias on which events are read."""

    def list_calendar_publication_events(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> tuple[SystemAuditEvent, ...]:
        """Return one fully validated, knowable calendar publication stream."""


_READER_CONTEXT_SEAL = object()


class CalendarAuditReaderPrincipal(Protocol):
    """Live session principal lease exposed by the trusted provider."""

    @property
    def actor_type(self) -> str:
        """Return the authenticated actor kind while the lease is live."""

        ...

    @property
    def actor_id(self) -> str:
        """Return the canonical authenticated actor identifier."""

        ...

    @property
    def permission_codename(self) -> str:
        """Return the exact read permission verified under lock."""

        ...

    @property
    def database_alias(self) -> str:
        """Return the alias holding the authorization lease."""

        ...

    @property
    def authority_content_hash(self) -> str:
        """Return the current lock-bound authority observation digest."""

        ...

    @property
    def verified_at(self) -> datetime:
        """Return the current lock-time permission verification instant."""

        ...

    @property
    def session_expires_at(self) -> datetime:
        """Return the locked Django session expiry instant."""

        ...

    @property
    def user_id(self) -> int:
        """Return the authenticated user identifier bound to the lease."""

        ...

    def assert_live(self) -> None:
        """Reject a revoked, expired, moved, or out-of-context lease."""


@dataclass(frozen=True, slots=True)
class CalendarPublicationAuditReaderContext:
    """Provider-issued live permission evidence bound to one dataset/exchange.

    The private in-process seal prevents a plain DTO or user id from becoming
    read authority. Only an injected trusted provider should call
    ``_from_authority`` while holding the exact current permission lease. The
    verification time describes the live check, never a historical grant.
    """

    authority_source_id: str
    authority_source_version: str
    authority_content_hash: str
    dataset_key: str
    exchange: str
    user_id: int
    actor_id: str
    database_alias: str
    authority_state: str
    verified_at: datetime
    session_expires_at: datetime
    permission_codename: str = CALENDAR_AUDIT_READ_PERMISSION
    is_authenticated: bool = True
    _principal: CalendarAuditReaderPrincipal | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate bounded exact authority fields without issuing capability."""

        for field_name in (
            "authority_source_id",
            "authority_source_version",
            "dataset_key",
            "exchange",
            "database_alias",
            "authority_state",
            "permission_codename",
        ):
            _require_token(getattr(self, field_name), field_name)
        if (
            type(self.authority_content_hash) is not str
            or _DIGEST_RE.fullmatch(self.authority_content_hash) is None
        ):
            raise ValueError("authority_content_hash must be sha256-prefixed lowercase digest")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if self.actor_id != f"django-user:{self.user_id}":
            raise ValueError("reader actor_id must match its authenticated user")
        if (
            self.authority_state != "active"
            or self.permission_codename != CALENDAR_AUDIT_READ_PERMISSION
        ):
            raise ValueError("calendar reader permission is not active and exact")
        if type(self.is_authenticated) is not bool or not self.is_authenticated:
            raise ValueError("calendar reader must be authenticated")
        _require_utc(self.verified_at, "verified_at")
        _require_utc(self.session_expires_at, "session_expires_at")
        if self.verified_at >= self.session_expires_at:
            raise ValueError("reader authority validity window is empty")

    @classmethod
    def _from_authority(
        cls,
        *,
        principal: CalendarAuditReaderPrincipal,
        dataset_key: str,
        exchange: str,
    ) -> CalendarPublicationAuditReaderContext:
        """Seal exact selectors around an already locked live principal."""

        if principal.actor_type != "django_user":
            raise ValueError("calendar reader actor must be an authenticated Django user")
        if principal.permission_codename != CALENDAR_AUDIT_READ_PERMISSION:
            raise ValueError("calendar reader permission is not exact")
        if (
            type(principal.authority_content_hash) is not str
            or _DIGEST_RE.fullmatch(principal.authority_content_hash) is None
        ):
            raise ValueError("authority_content_hash must be sha256-prefixed lowercase digest")
        principal.assert_live()
        context = cls(
            authority_source_id="data-center.calendar-audit-permission",
            authority_source_version="v1",
            authority_content_hash=principal.authority_content_hash,
            dataset_key=dataset_key,
            exchange=exchange,
            user_id=principal.user_id,
            actor_id=principal.actor_id,
            database_alias=principal.database_alias,
            authority_state="active",
            verified_at=principal.verified_at,
            session_expires_at=principal.session_expires_at,
            permission_codename=principal.permission_codename,
        )
        object.__setattr__(context, "_principal", principal)
        object.__setattr__(context, "_seal", _READER_CONTEXT_SEAL)
        context.assert_live()
        return context

    def assert_live(self) -> None:
        """Recheck the exact locked principal without comparing event ``as_of``."""

        principal = self._principal
        if (
            self._seal is not _READER_CONTEXT_SEAL
            or principal is None
            or self.permission_codename != CALENDAR_AUDIT_READ_PERMISSION
            or self.authority_state != "active"
            or not self.is_authenticated
            or self.actor_id != f"django-user:{self.user_id}"
            or principal.actor_type != "django_user"
            or principal.actor_id != self.actor_id
            or principal.user_id != self.user_id
            or principal.permission_codename != self.permission_codename
            or principal.database_alias != self.database_alias
            or principal.authority_content_hash != self.authority_content_hash
            or principal.verified_at != self.verified_at
            or principal.session_expires_at != self.session_expires_at
        ):
            raise CalendarPublicationAuditDenied()
        try:
            principal.assert_live()
        except CalendarPublicationAuditDenied:
            raise
        except AuthorizationError as error:
            raise CalendarPublicationAuditDenied() from error


@dataclass(frozen=True, slots=True)
class ListCalendarPublicationAuditEventsCommand:
    """Exact dataset, exchange, and PIT query with opaque request proof."""

    dataset_key: str
    exchange: str
    as_of: datetime
    request_proof: object

    def __post_init__(self) -> None:
        """Reject unbounded selectors before consulting the authority provider."""

        _require_token(self.dataset_key, "dataset_key")
        _require_token(self.exchange, "exchange")
        _require_utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class ListCalendarPublicationAuditEventsResult:
    """One exact, fully verified event stream, possibly empty at the PIT."""

    dataset_key: str
    exchange: str
    as_of: datetime
    events: tuple[SystemAuditEvent, ...]


class ListCalendarPublicationAuditEventsUseCase:
    """Authorize and return only one provider-bound calendar audit stream."""

    __slots__ = ("_authority_provider", "_repository")

    def __init__(
        self,
        *,
        authority_provider: CalendarPublicationAuditReadAuthorityProvider,
        repository: CalendarPublicationAuditReaderRepository,
    ) -> None:
        self._authority_provider = authority_provider
        self._repository = repository

    def execute(
        self,
        command: ListCalendarPublicationAuditEventsCommand,
    ) -> ListCalendarPublicationAuditEventsResult:
        """Require live exact permission before the dedicated stream selector."""

        if type(command) is not ListCalendarPublicationAuditEventsCommand:
            raise CalendarPublicationAuditValidationError("calendar audit query is invalid")
        try:
            lease = self._authority_provider.lock_reader(
                request_proof=command.request_proof,
                dataset_key=command.dataset_key,
                exchange=command.exchange,
                database_alias=self._repository.database_alias,
            )
        except CalendarPublicationAuditDenied:
            raise
        except AuthorizationError as error:
            raise CalendarPublicationAuditDenied() from error
        except Exception as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication audit authority provider failed"
            ) from error
        if lease is None:
            raise CalendarPublicationAuditUnavailable(
                "no trusted calendar publication audit reader is configured"
            )
        try:
            with lease as context:
                if type(context) is not CalendarPublicationAuditReaderContext:
                    raise CalendarPublicationAuditUnavailable(
                        "reader provider yielded an invalid authority context"
                    )
                if (
                    context.dataset_key != command.dataset_key
                    or context.exchange != command.exchange
                    or context.database_alias != self._repository.database_alias
                ):
                    raise CalendarPublicationAuditDenied(
                        "reader authority does not match the exact selector"
                    )
                context.assert_live()
                try:
                    events = self._repository.list_calendar_publication_events(
                        dataset_key=command.dataset_key,
                        exchange=command.exchange,
                        as_of=command.as_of,
                    )
                except Exception as error:
                    if isinstance(
                        error,
                        (CalendarPublicationAuditUnavailable, CalendarPublicationAuditCorruption),
                    ):
                        raise
                    raise CalendarPublicationAuditUnavailable(
                        "calendar publication audit selector failed"
                    ) from error
                _validate_calendar_reader_result(
                    events=events,
                    dataset_key=command.dataset_key,
                    exchange=command.exchange,
                    as_of=command.as_of,
                )
                context.assert_live()
                return ListCalendarPublicationAuditEventsResult(
                    dataset_key=command.dataset_key,
                    exchange=command.exchange,
                    as_of=command.as_of,
                    events=events,
                )
        except CalendarPublicationAuditDenied:
            raise
        except (CalendarPublicationAuditUnavailable, CalendarPublicationAuditCorruption):
            raise
        except AuthorizationError as error:
            raise CalendarPublicationAuditDenied() from error
        except Exception as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar publication audit reader lease failed"
            ) from error


class CalendarPublicationAuditOutboxWriter(Protocol):
    """Same-alias, caller-owned transactional writer required by a publisher."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by both Audit event and outbox."""

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Join the publisher's existing outer transaction on this alias."""

    def append_and_enqueue_calendar_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        principal: CalendarAuditPublisherPrincipal,
    ) -> SystemAuditEventOutboxCommit:
        """Append only one fully matching calendar event and its exact outbox."""

    def lock_stream(self, stream_id: str) -> None:
        """Serialize the exact stream before the caller selects its head."""

    def get_calendar_publication_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Lock one identity winner after validating its calendar selector."""

    def get_calendar_publication_head_targeted(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Lock the exact dataset/exchange stream head, never a global head."""

    def get_exact_outbox_winner_targeted(
        self,
        event: SystemAuditEvent,
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read only the exact outbox paired with one canonical event."""


class AppendCalendarPublicationAuditUseCase:
    """Build, append, or prove an exact calendar Audit event/outbox replay.

    The use case can only join an already-open publisher transaction. It does
    not create a publication authority provider or default production wiring.
    """

    __slots__ = ("_writer",)

    def __init__(self, writer: CalendarPublicationAuditOutboxWriter) -> None:
        self._writer = writer

    def execute_published_in_caller_transaction(
        self,
        observation: CalendarPublicationPublishedObservation,
        *,
        principal: CalendarAuditPublisherPrincipal,
        exact_replay: bool,
    ) -> SystemAuditEventOutboxCommit:
        """Append the first published pair or prove its exact persisted replay."""

        observation = _validated_published_observation(observation)
        return self._execute(
            event_kind="published",
            dataset_key=observation.detail.dataset_key,
            exchange=observation.detail.exchange,
            request_identity=observation.detail.publication_id,
            recorded_at=observation.recorded_at,
            principal=principal,
            exact_replay=exact_replay,
            event_factory=lambda *, sequence_no, predecessor_hash: (
                build_calendar_publication_published_event(
                    observation,
                    principal=principal,
                    database_alias=self._writer.database_alias,
                    sequence_no=sequence_no,
                    predecessor_hash=predecessor_hash,
                )
            ),
        )

    def execute_blocked_in_caller_transaction(
        self,
        observation: CalendarPublicationBlockedObservation,
        *,
        principal: CalendarAuditPublisherPrincipal,
        exact_replay: bool,
    ) -> SystemAuditEventOutboxCommit:
        """Append the first blocked pair or prove its exact persisted replay."""

        observation = _validated_blocked_observation(observation)
        return self._execute(
            event_kind="blocked",
            dataset_key=observation.detail.dataset_key,
            exchange=observation.detail.exchange,
            request_identity=observation.detail.request_id,
            recorded_at=observation.recorded_at,
            principal=principal,
            exact_replay=exact_replay,
            event_factory=lambda *, sequence_no, predecessor_hash: (
                build_calendar_publication_blocked_event(
                    observation,
                    principal=principal,
                    database_alias=self._writer.database_alias,
                    sequence_no=sequence_no,
                    predecessor_hash=predecessor_hash,
                )
            ),
        )

    def _execute(
        self,
        *,
        event_kind: str,
        dataset_key: str,
        exchange: str,
        request_identity: str,
        recorded_at: datetime,
        principal: CalendarAuditPublisherPrincipal,
        exact_replay: bool,
        event_factory: CalendarAuditEventFactory,
    ) -> SystemAuditEventOutboxCommit:
        """Serialize one event stream and require both replay rows to match."""

        if type(exact_replay) is not bool:
            raise CalendarPublicationAuditValidationError("exact_replay must be a boolean")
        try:
            principal.assert_live()
            _validated_publisher_actor(
                principal=principal,
                database_alias=self._writer.database_alias,
                recorded_at=recorded_at,
            )
            event_id, idempotency_key = calendar_publication_event_identity(
                event_kind=event_kind,
                dataset_key=dataset_key,
                exchange=exchange,
                request_identity=request_identity,
            )
            stream_id = calendar_publication_stream_id(dataset_key, exchange)
            with self._writer.caller_owned_atomic():
                principal.assert_live()
                self._writer.lock_stream(stream_id)
                winner = self._writer.get_calendar_publication_winner_targeted(
                    event_id=event_id,
                    event_version="1",
                    dataset_key=dataset_key,
                    exchange=exchange,
                    as_of=recorded_at,
                )
                if exact_replay:
                    if winner is None:
                        raise CalendarPublicationAuditCorruption(
                            "exact calendar Audit replay has no event winner"
                        )
                    if type(winner) is not SystemAuditEvent:
                        raise CalendarPublicationAuditCorruption(
                            "calendar Audit winner selector returned an invalid event"
                        )
                    try:
                        validate_calendar_publication_event(winner)
                    except (AttributeError, TypeError, ValueError) as error:
                        raise CalendarPublicationAuditCorruption(
                            "calendar Audit winner violates its closed event contract"
                        ) from error
                    expected = _call_event_factory(
                        event_factory,
                        sequence_no=winner.sequence_no,
                        predecessor_hash=winner.predecessor_hash,
                    )
                    if winner != expected:
                        raise CalendarPublicationAuditConflict(
                            "calendar Audit identity already has another event"
                        )
                    outbox = self._writer.get_exact_outbox_winner_targeted(expected)
                    if type(outbox) is not ExactSystemAuditOutboxWinner:
                        raise CalendarPublicationAuditCorruption(
                            "calendar Audit winner has no exact outbox row"
                        )
                    try:
                        ExactSystemAuditOutboxWinner.__post_init__(outbox)
                    except (AttributeError, TypeError, ValueError) as error:
                        raise CalendarPublicationAuditCorruption(
                            "calendar Audit outbox winner is malformed"
                        ) from error
                    if (
                        outbox.event != expected
                        or outbox.event_id != expected.event_id
                        or outbox.idempotency_key != expected.idempotency_key
                        or outbox.payload_hash != expected.content_hash
                    ):
                        raise CalendarPublicationAuditCorruption(
                            "calendar Audit outbox is not an exact event pair"
                        )
                    return SystemAuditEventOutboxCommit(
                        event=expected,
                        outbox_id=outbox.outbox_id,
                        event_id=outbox.event_id,
                        idempotency_key=outbox.idempotency_key,
                    )
                if winner is not None:
                    raise CalendarPublicationAuditConflict(
                        "calendar Audit request already has a first winner"
                    )
                head = self._writer.get_calendar_publication_head_targeted(
                    dataset_key=dataset_key,
                    exchange=exchange,
                    as_of=recorded_at,
                )
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
                event = _call_event_factory(
                    event_factory,
                    sequence_no=sequence_no,
                    predecessor_hash=predecessor_hash,
                )
                if event.event_id != event_id or event.idempotency_key != idempotency_key:
                    raise CalendarPublicationAuditCorruption(
                        "calendar Audit builder changed deterministic event identity"
                    )
                orphan = self._writer.get_exact_outbox_winner_targeted(event)
                if orphan is not None:
                    raise CalendarPublicationAuditCorruption(
                        "calendar Audit outbox exists without its event winner"
                    )
                principal.assert_live()
                commit = self._writer.append_and_enqueue_calendar_targeted(
                    event,
                    expected_predecessor_hash=predecessor_hash,
                    recorded_at=recorded_at,
                    principal=principal,
                )
                if commit.event != event:
                    raise CalendarPublicationAuditCorruption(
                        "calendar Audit writer substituted the first event"
                    )
                return commit
        except (
            CalendarPublicationAuditUnavailable,
            CalendarPublicationAuditDenied,
            CalendarPublicationAuditConflict,
            CalendarPublicationAuditCorruption,
            CalendarPublicationAuditValidationError,
        ):
            raise
        except AuthorizationError as error:
            raise CalendarPublicationAuditDenied() from error
        except SystemAuditEventOutboxConflict as error:
            raise CalendarPublicationAuditConflict() from error
        except SystemAuditEventOutboxCorruption as error:
            raise CalendarPublicationAuditCorruption() from error
        except Exception as error:
            raise CalendarPublicationAuditUnavailable(
                "calendar Audit event/outbox append failed"
            ) from error


def _validated_publisher_actor(
    *,
    principal: CalendarAuditPublisherPrincipal,
    database_alias: str,
    recorded_at: datetime,
) -> AuditActorRef:
    """Recheck the live session lease before reading its attribution fields."""

    if type(database_alias) is not str or not database_alias:
        raise CalendarPublicationAuditDenied("calendar Audit database alias is missing")
    if not callable(getattr(principal, "assert_live", None)):
        raise CalendarPublicationAuditDenied("calendar Audit principal is not a live lease")
    try:
        principal.assert_live()
    except (AuthenticationError, AuthorizationError) as error:
        raise CalendarPublicationAuditDenied() from error
    user_id = getattr(principal, "user_id", None)
    actor_type = getattr(principal, "actor_type", None)
    actor_id = getattr(principal, "actor_id", None)
    permission_codename = getattr(principal, "permission_codename", None)
    principal_alias = getattr(principal, "database_alias", None)
    verified_at = getattr(principal, "verified_at", None)
    if (
        type(user_id) is not int
        or user_id <= 0
        or actor_type != "django_user"
        or actor_id != f"django-user:{user_id}"
        or permission_codename != CALENDAR_PUBLISH_PERMISSION
        or principal_alias != database_alias
        or type(verified_at) is not datetime
        or not _is_aware_utc(verified_at)
        or not _is_aware_utc(recorded_at)
    ):
        raise CalendarPublicationAuditDenied(
            "calendar Audit principal is not authorized for this alias and event time"
        )
    return AuditActorRef(actor_type=actor_type, actor_id=actor_id)


def _validated_published_observation(
    value: object,
) -> CalendarPublicationPublishedObservation:
    """Recheck a published observation and map Domain errors to an app error."""

    if type(value) is not CalendarPublicationPublishedObservation:
        raise CalendarPublicationAuditValidationError("published observation is invalid")
    try:
        CalendarPublicationPublishedObservation.__post_init__(value)
    except CalendarPublicationAuditContractError as error:
        raise CalendarPublicationAuditValidationError(str(error), code=error.code) from error
    except (TypeError, ValueError) as error:
        raise CalendarPublicationAuditValidationError(
            "published observation violates its typed contract"
        ) from error
    return value


def _validated_blocked_observation(
    value: object,
) -> CalendarPublicationBlockedObservation:
    """Recheck a blocked observation and map Domain errors to an app error."""

    if type(value) is not CalendarPublicationBlockedObservation:
        raise CalendarPublicationAuditValidationError("blocked observation is invalid")
    try:
        CalendarPublicationBlockedObservation.__post_init__(value)
    except CalendarPublicationAuditContractError as error:
        raise CalendarPublicationAuditValidationError(str(error), code=error.code) from error
    except (TypeError, ValueError) as error:
        raise CalendarPublicationAuditValidationError(
            "blocked observation violates its typed contract"
        ) from error
    return value


def _audit_evidence_ref(evidence: CalendarPublicationAuditEvidence) -> AuditEvidenceRef:
    """Build the exact evidence reference from the immutable fact-row hash."""

    return AuditEvidenceRef(
        owner="data_center",
        artifact_type="exchange_calendar_snapshot_fact",
        artifact_id=evidence.snapshot_id,
        artifact_version=evidence.snapshot_record_digest,
        content_hash=evidence.fact_content_hash,
    )


def _snapshot_correlation(evidence: CalendarPublicationAuditEvidence) -> str:
    """Return the exact snapshot-to-fact correlation value."""

    return f"calendar-snapshot:{evidence.snapshot_id}:{evidence.fact_content_hash}"


def _validate_calendar_reader_result(
    *,
    events: tuple[SystemAuditEvent, ...],
    dataset_key: str,
    exchange: str,
    as_of: datetime,
) -> None:
    """Verify a complete ordered event stream returned for one exact selector."""

    if type(events) is not tuple:
        raise CalendarPublicationAuditCorruption("calendar audit result is not a tuple")
    expected_stream = calendar_publication_stream_id(dataset_key, exchange)
    prior: SystemAuditEvent | None = None
    for event in events:
        if type(event) is not SystemAuditEvent:
            raise CalendarPublicationAuditCorruption("calendar audit result has a non-event row")
        try:
            validate_calendar_publication_event(event)
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationAuditCorruption(
                "calendar audit result failed its closed event contract"
            ) from error
        if (
            event.dataset_key != dataset_key
            or event.stream_id != expected_stream
            or event.recorded_at > as_of
            or event.scope is not None
        ):
            raise CalendarPublicationAuditCorruption(
                "calendar audit repository returned an event outside the exact selector"
            )
        if prior is None:
            if event.sequence_no != 1 or event.predecessor_hash is not None:
                raise CalendarPublicationAuditCorruption(
                    "calendar audit stream does not begin with its root event"
                )
        elif (
            event.sequence_no != prior.sequence_no + 1
            or event.predecessor_hash != prior.content_hash
            or event.recorded_at < prior.recorded_at
        ):
            raise CalendarPublicationAuditCorruption(
                "calendar audit stream sequence or predecessor chain is broken"
            )
        prior = event


def _call_event_factory(
    factory: CalendarAuditEventFactory,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Call one internal builder without accepting a dynamic caller callback."""

    event = factory(sequence_no=sequence_no, predecessor_hash=predecessor_hash)
    if type(event) is not SystemAuditEvent:
        raise CalendarPublicationAuditCorruption("calendar event factory returned an invalid event")
    return event


def _require_token(value: object, field_name: str) -> None:
    """Require one bounded, whitespace-free canonical selector token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise CalendarPublicationAuditValidationError(
            f"{field_name} must be a bounded canonical token"
        )


def _require_utc(value: datetime, field_name: str) -> None:
    """Require an aware UTC timestamp for authority and PIT boundaries."""

    if type(value) is not datetime or not _is_aware_utc(value):
        raise CalendarPublicationAuditValidationError(f"{field_name} must be UTC-aware")


def _is_aware_utc(value: datetime) -> bool:
    """Return whether ``value`` is an aware UTC instant."""

    offset = value.utcoffset()
    return value.tzinfo is not None and offset is not None and offset.total_seconds() == 0


__all__ = [
    "CALENDAR_AUDIT_READ_PERMISSION",
    "AppendCalendarPublicationAuditUseCase",
    "CalendarAuditReaderPrincipal",
    "CalendarAuditPublisherPrincipal",
    "CalendarPublicationAuditConflict",
    "CalendarPublicationAuditCorruption",
    "CalendarPublicationAuditDenied",
    "CalendarPublicationAuditOutboxWriter",
    "CalendarPublicationAuditReadAuthorityProvider",
    "CalendarPublicationAuditReaderContext",
    "CalendarPublicationAuditReaderRepository",
    "CalendarPublicationAuditUnavailable",
    "CalendarPublicationAuditValidationError",
    "CalendarPublicationBlockedObservation",
    "CalendarPublicationPublishedObservation",
    "ListCalendarPublicationAuditEventsCommand",
    "ListCalendarPublicationAuditEventsResult",
    "ListCalendarPublicationAuditEventsUseCase",
    "build_calendar_publication_blocked_event",
    "build_calendar_publication_published_event",
]
