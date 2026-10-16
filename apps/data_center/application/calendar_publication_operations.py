"""Typed Application intents for capturing and formally publishing a calendar.

These use cases coordinate injected source, preparation, clock and publication
ports. They do not open transactions, configure a provider, authorize a user or
make a calendar usable for an execution decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarCurrentPublicationReaderPort,
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
    CalendarPublicationWindow,
    CalendarPublicationWindowError,
)
from apps.data_center.domain.contracts import (
    MAX_CATALOG_TTL_SECONDS,
    DatasetContract,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarPublicationMemberReference
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationSeal,
    CalendarPublicationPointerExpectation,
    calendar_formal_seals_have_same_evidence,
    create_calendar_formal_publication_seal,
)
from core.exceptions import AuthorizationError, DataValidationError, MissingConfigError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")
_ACTOR_RE = re.compile(r"^django-user:([1-9][0-9]*)$")
_PREVIEW_SCHEMA = "exchange-calendar-publication-preview-v1"


class CalendarPublicationOperationsError(DataValidationError):
    """Recognized fail-closed input or stale-preview error for calendar operations."""

    default_message = "Exchange calendar publication operation is invalid"
    default_code = "CALENDAR_PUBLICATION_OPERATION_INVALID"

    def __init__(self, message: str, *, code: str, status_code: int = 422) -> None:
        """Expose a stable code while preserving the shared application exception type."""

        super().__init__(message, code=code, status_code=status_code)


class CalendarOperationsClock(Protocol):
    """Supply the server knowledge time without reading a global clock implicitly."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class CalendarActivationIdFactory(Protocol):
    """Generate a unique business activation identity for one preview."""

    def new_id(self) -> str:
        """Return one canonical bounded activation token."""


class CalendarSnapshotCapturePort(Protocol):
    """Capture an exact exchange/date range through configured source plumbing."""

    def execute(
        self,
        exchange: str,
        coverage_start: date,
        coverage_end: date,
    ) -> ExchangeCalendarSnapshot:
        """Return one saved immutable snapshot without activating it."""


@dataclass(frozen=True, slots=True)
class CalendarPublicationPreparationContext:
    """Exact persisted source, catalog evidence, row hash and current pointer.

    The repository adapter must derive ``member_reference.member.fact_content_hash``
    from the exact persisted fact row. ``snapshot.record_digest`` is a different
    digest domain and must never be substituted for that row hash.
    """

    snapshot: ExchangeCalendarSnapshot
    contract: DatasetContract
    contract_recorded_at: datetime
    policy: PublicationPolicy
    policy_recorded_at: datetime
    member_reference: CalendarPublicationMemberReference
    current_pointer: CalendarPublicationPointerExpectation

    def __post_init__(self) -> None:
        """Validate typed preparation data before it reaches Domain sealing."""

        self.validate()

    def validate(self) -> None:
        """Revalidate nested evidence at every Application trust boundary."""

        if type(self.snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarPublicationOperationsError(
                "Preparation context has no exact persisted snapshot",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        if type(self.contract) is not DatasetContract:
            raise CalendarPublicationOperationsError(
                "Preparation context has no exact dataset contract",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        if type(self.policy) is not PublicationPolicy:
            raise CalendarPublicationOperationsError(
                "Preparation context has no exact publication policy",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        if type(self.member_reference) is not CalendarPublicationMemberReference:
            raise CalendarPublicationOperationsError(
                "Preparation context has no exact calendar member evidence",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        if type(self.current_pointer) is not CalendarPublicationPointerExpectation:
            raise CalendarPublicationOperationsError(
                "Preparation context has no complete current-pointer identity",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        try:
            self.snapshot.__post_init__()
            self.contract.__post_init__()
            self.policy.__post_init__()
            self.member_reference.__post_init__()
            self.current_pointer.validate()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationOperationsError(
                "Preparation context contains invalid nested evidence",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            ) from error
        _require_utc(self.contract_recorded_at, "contract_recorded_at")
        _require_utc(self.policy_recorded_at, "policy_recorded_at")


class CalendarPublicationPreparationPort(Protocol):
    """Resolve exact persisted evidence and current catalog/pointer state.

    A repository implementation must use the exact snapshot reference and the
    supplied knowledge cutoff. It must not choose a latest source or silently
    infer a missing contract, policy, TTL, row hash or pointer.
    """

    def load_exact(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> CalendarPublicationPreparationContext | None:
        """Return one exact preparation context, or None when it is unavailable."""


class CalendarFormalPublicationPort(Protocol):
    """Invoke the verified formal Application publisher in its caller transaction.

    The composition must adapt the existing
    ``PublishExchangeCalendarSnapshotUseCase``; it must not implement this port
    by wiring a repository directly. That use case owns the Audit/outbox binding,
    CAS and current-principal replay checks.
    """

    def execute(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Return the exact publication receipt or propagate the transaction failure."""


@dataclass(frozen=True, slots=True)
class CaptureExchangeCalendarSnapshotIntent:
    """Request capture for one explicit exchange and complete date range."""

    exchange: str
    coverage_start: date
    coverage_end: date

    def __post_init__(self) -> None:
        """Reject missing scope and datetime values masquerading as dates."""

        if (
            type(self.exchange) is not str
            or not self.exchange
            or self.exchange.strip() != self.exchange
            or any(character.isspace() for character in self.exchange)
        ):
            raise CalendarPublicationOperationsError(
                "Capture exchange must be explicit",
                code="CALENDAR_CAPTURE_INTENT_INVALID",
            )
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise CalendarPublicationOperationsError(
                "Capture coverage must use exact dates",
                code="CALENDAR_CAPTURE_INTENT_INVALID",
            )
        if self.coverage_start > self.coverage_end:
            raise CalendarPublicationOperationsError(
                "Capture coverage start must not follow its end",
                code="CALENDAR_CAPTURE_INTENT_INVALID",
            )


@dataclass(frozen=True, slots=True)
class CapturedExchangeCalendarSnapshot:
    """User-facing capture receipt for one unpublished exact snapshot."""

    snapshot_reference: ExchangeCalendarSnapshotReference
    first_seen_at: datetime
    recorded_at: datetime
    source_published_at: datetime | None

    def __post_init__(self) -> None:
        """Keep source and local knowledge clocks separate."""

        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise CalendarPublicationOperationsError(
                "Capture receipt requires an exact snapshot reference",
                code="CALENDAR_CAPTURE_RESULT_INVALID",
            )
        self.snapshot_reference.__post_init__()
        _require_utc(self.first_seen_at, "first_seen_at")
        _require_utc(self.recorded_at, "recorded_at")
        if self.recorded_at < self.first_seen_at:
            raise CalendarPublicationOperationsError(
                "Snapshot record time cannot precede response completion",
                code="CALENDAR_CAPTURE_RESULT_INVALID",
            )
        if self.source_published_at is not None:
            _require_utc(self.source_published_at, "source_published_at")

    @property
    def must_not_execute(self) -> bool:
        """Return the fixed capability boundary for an unpublished snapshot."""

        return True


class CaptureExchangeCalendarSnapshotUseCase:
    """Capture and return a reference without accepting provider or actor input."""

    def __init__(self, source: CalendarSnapshotCapturePort) -> None:
        """Bind capture to an explicitly configured source-use-case port."""

        self._source = source

    def execute(
        self,
        intent: CaptureExchangeCalendarSnapshotIntent,
    ) -> CapturedExchangeCalendarSnapshot:
        """Persist one complete source response without publishing or activating it."""

        if type(intent) is not CaptureExchangeCalendarSnapshotIntent:
            raise CalendarPublicationOperationsError(
                "Capture requires a typed explicit intent",
                code="CALENDAR_CAPTURE_INTENT_INVALID",
            )
        intent.__post_init__()
        snapshot = self._source.execute(
            intent.exchange,
            intent.coverage_start,
            intent.coverage_end,
        )
        if type(snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarPublicationOperationsError(
                "Calendar source returned no typed persisted snapshot",
                code="CALENDAR_CAPTURE_RESULT_INVALID",
            )
        try:
            snapshot.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationOperationsError(
                "Calendar source returned an invalid snapshot",
                code="CALENDAR_CAPTURE_RESULT_INVALID",
            ) from error
        if (
            snapshot.exchange != intent.exchange
            or snapshot.coverage_start != intent.coverage_start
            or snapshot.coverage_end != intent.coverage_end
        ):
            raise CalendarPublicationOperationsError(
                "Captured snapshot differs from the requested exchange or date range",
                code="CALENDAR_CAPTURE_SCOPE_MISMATCH",
            )
        return CapturedExchangeCalendarSnapshot(
            snapshot_reference=snapshot.reference(),
            first_seen_at=snapshot.first_seen_at,
            recorded_at=snapshot.recorded_at,
            source_published_at=snapshot.source_published_at,
        )


@dataclass(frozen=True, slots=True)
class PreviewCalendarPublicationIntent:
    """Request preview for one exact captured snapshot reference."""

    snapshot_reference: ExchangeCalendarSnapshotReference

    def __post_init__(self) -> None:
        """Reject loose IDs or untyped source identities."""

        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise CalendarPublicationOperationsError(
                "Preview requires an exact typed snapshot reference",
                code="CALENDAR_PUBLICATION_PREVIEW_INTENT_INVALID",
            )
        try:
            self.snapshot_reference.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationOperationsError(
                "Preview snapshot reference is invalid",
                code="CALENDAR_PUBLICATION_PREVIEW_INTENT_INVALID",
            ) from error


@dataclass(frozen=True, slots=True)
class CalendarPublicationPreviewIdentity:
    """Exact dataset contract, policy and response-age settings shown in preview."""

    dataset_key: str
    contract_version: str
    schema_version: str
    policy_identity: str
    policy_version: str
    calendar_response_max_age_seconds: int

    def __post_init__(self) -> None:
        """Validate all versioned identity fields without applying defaults."""

        for field_name in (
            "dataset_key",
            "contract_version",
            "schema_version",
            "policy_identity",
            "policy_version",
        ):
            _require_bounded_text(getattr(self, field_name), field_name)
        if (
            type(self.calendar_response_max_age_seconds) is not int
            or self.calendar_response_max_age_seconds < 1
            or self.calendar_response_max_age_seconds > MAX_CATALOG_TTL_SECONDS
        ):
            raise CalendarPublicationOperationsError(
                "Preview response-age TTL must be an explicit positive integer",
                code="CALENDAR_PUBLICATION_IDENTITY_INVALID",
            )


@dataclass(frozen=True, slots=True)
class CalendarPublicationPreview:
    """Machine-echoable preview data; it contains no seal or authority claim.

    ``preview_hash`` is an unkeyed content checksum for stale-preview detection.
    It is neither a signature nor a capability token; confirmation still needs
    a live publisher principal and a full server-side re-read.
    """

    snapshot_reference: ExchangeCalendarSnapshotReference
    identity: CalendarPublicationPreviewIdentity
    expected_pointer: CalendarPublicationPointerExpectation
    activation_id: str
    expected_publication_hash: str
    first_seen_at: datetime
    snapshot_recorded_at: datetime
    source_published_at: datetime | None
    response_expires_at: datetime
    previewed_at: datetime
    preview_hash: str

    def __post_init__(self) -> None:
        """Validate the complete confirmation echo and preview digest shape."""

        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise CalendarPublicationOperationsError(
                "Preview contains no exact source reference",
                code="CALENDAR_PUBLICATION_PREVIEW_INVALID",
            )
        if type(self.identity) is not CalendarPublicationPreviewIdentity:
            raise CalendarPublicationOperationsError(
                "Preview contains no exact catalog identity",
                code="CALENDAR_PUBLICATION_PREVIEW_INVALID",
            )
        if type(self.expected_pointer) is not CalendarPublicationPointerExpectation:
            raise CalendarPublicationOperationsError(
                "Preview contains no complete pointer expectation",
                code="CALENDAR_PUBLICATION_PREVIEW_INVALID",
            )
        self.snapshot_reference.__post_init__()
        self.identity.__post_init__()
        self.expected_pointer.validate()
        _require_activation_id(self.activation_id)
        _require_sha256(self.expected_publication_hash, "expected_publication_hash")
        _require_sha256(self.preview_hash, "preview_hash")
        _require_utc(self.first_seen_at, "first_seen_at")
        _require_utc(self.snapshot_recorded_at, "snapshot_recorded_at")
        _require_utc(self.response_expires_at, "response_expires_at")
        _require_utc(self.previewed_at, "previewed_at")
        if self.source_published_at is not None:
            _require_utc(self.source_published_at, "source_published_at")
        if not self.first_seen_at <= self.snapshot_recorded_at <= self.previewed_at:
            raise CalendarPublicationOperationsError(
                "Preview knowledge clocks are inconsistent",
                code="CALENDAR_PUBLICATION_PREVIEW_INVALID",
            )
        if self.previewed_at >= self.response_expires_at:
            raise CalendarPublicationOperationsError(
                "Preview was produced after the source response expired",
                code="CALENDAR_PUBLICATION_RESPONSE_EXPIRED",
                status_code=409,
            )

    @property
    def must_not_execute(self) -> bool:
        """Return the fixed non-execution boundary for publication previews."""

        return True

    def confirmation_intent(self) -> ConfirmCalendarPublicationIntent:
        """Return the exact fields the client may echo for confirmation."""

        self.__post_init__()
        return ConfirmCalendarPublicationIntent(
            snapshot_reference=self.snapshot_reference,
            expected_identity=self.identity,
            expected_pointer=self.expected_pointer,
            activation_id=self.activation_id,
            expected_publication_hash=self.expected_publication_hash,
            preview_hash=self.preview_hash,
        )


class PreviewCalendarPublicationUseCase:
    """Resolve exact source/catalog state and create a non-persistent preview."""

    def __init__(
        self,
        *,
        preparation: CalendarPublicationPreparationPort,
        clock: CalendarOperationsClock,
        activation_ids: CalendarActivationIdFactory,
    ) -> None:
        """Bind the exact preparation reader and explicit server factories."""

        self._preparation = preparation
        self._clock = clock
        self._activation_ids = activation_ids

    def execute(
        self,
        intent: PreviewCalendarPublicationIntent,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarPublicationPreview:
        """Create a checksum-bound preview while the publisher lease is live."""

        if type(intent) is not PreviewCalendarPublicationIntent:
            raise CalendarPublicationOperationsError(
                "Preview requires a typed intent",
                code="CALENDAR_PUBLICATION_PREVIEW_INTENT_INVALID",
            )
        intent.__post_init__()
        _validate_publisher(principal)
        previewed_at = _read_server_clock(self._clock)
        _ensure_clock_after_authorization(previewed_at, principal)
        context = self._load_context(intent.snapshot_reference, known_at=previewed_at)
        seal = _build_seal(context, intent.snapshot_reference)
        response_expires_at = _response_expiry(seal)
        if previewed_at >= response_expires_at:
            raise CalendarPublicationOperationsError(
                "Calendar response-age TTL expired before preview",
                code="CALENDAR_PUBLICATION_RESPONSE_EXPIRED",
                status_code=409,
            )
        _validate_pointer_scope(context.current_pointer, seal)
        pointer = context.current_pointer
        if (
            not pointer.is_absent
            and pointer.publication_hash == seal.publication_hash
            and pointer.activation_id is not None
        ):
            # Reuse the identity of an exact current winner so a fresh preview
            # can drive the formal publisher's exact-current replay path.
            activation_id = pointer.activation_id
        else:
            activation_id = self._activation_ids.new_id()
        _require_activation_id(activation_id)
        identity = _identity_from_seal(seal)
        preview_hash = _preview_hash(
            reference=intent.snapshot_reference,
            identity=identity,
            pointer=context.current_pointer,
            activation_id=activation_id,
            publication_hash=seal.publication_hash,
            first_seen_at=seal.snapshot_first_seen_at,
            snapshot_recorded_at=seal.snapshot_recorded_at,
            source_published_at=seal.snapshot.source_published_at,
            response_expires_at=response_expires_at,
        )
        _assert_publisher_live(principal)
        return CalendarPublicationPreview(
            snapshot_reference=intent.snapshot_reference,
            identity=identity,
            expected_pointer=context.current_pointer,
            activation_id=activation_id,
            expected_publication_hash=seal.publication_hash,
            first_seen_at=seal.snapshot_first_seen_at,
            snapshot_recorded_at=seal.snapshot_recorded_at,
            source_published_at=seal.snapshot.source_published_at,
            response_expires_at=response_expires_at,
            previewed_at=previewed_at,
            preview_hash=preview_hash,
        )

    def _load_context(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> CalendarPublicationPreparationContext:
        """Load one exact trusted context or fail closed when it is unavailable."""

        context = self._preparation.load_exact(reference, known_at=known_at)
        if context is None:
            raise MissingConfigError(
                "Exact calendar source or versioned publication configuration is unavailable",
                code="CALENDAR_PUBLICATION_PREPARATION_UNAVAILABLE",
            )
        if type(context) is not CalendarPublicationPreparationContext:
            raise CalendarPublicationOperationsError(
                "Preparation provider returned an invalid context type",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        context.validate()
        _ensure_context_known(context, known_at)
        return context


@dataclass(frozen=True, slots=True)
class ConfirmCalendarPublicationIntent:
    """Echo only the exact reference, catalog identity, CAS and preview hashes."""

    snapshot_reference: ExchangeCalendarSnapshotReference
    expected_identity: CalendarPublicationPreviewIdentity
    expected_pointer: CalendarPublicationPointerExpectation
    activation_id: str
    expected_publication_hash: str
    preview_hash: str

    def __post_init__(self) -> None:
        """Reject incomplete or loose confirmation data before provider access."""

        if type(self.snapshot_reference) is not ExchangeCalendarSnapshotReference:
            raise CalendarPublicationOperationsError(
                "Confirmation requires an exact snapshot reference",
                code="CALENDAR_PUBLICATION_CONFIRMATION_INVALID",
            )
        if type(self.expected_identity) is not CalendarPublicationPreviewIdentity:
            raise CalendarPublicationOperationsError(
                "Confirmation requires an exact catalog identity",
                code="CALENDAR_PUBLICATION_CONFIRMATION_INVALID",
            )
        if type(self.expected_pointer) is not CalendarPublicationPointerExpectation:
            raise CalendarPublicationOperationsError(
                "Confirmation requires a complete pointer CAS",
                code="CALENDAR_PUBLICATION_CONFIRMATION_INVALID",
            )
        self.snapshot_reference.__post_init__()
        self.expected_identity.__post_init__()
        self.expected_pointer.validate()
        _require_activation_id(self.activation_id)
        _require_sha256(self.expected_publication_hash, "expected_publication_hash")
        _require_sha256(self.preview_hash, "preview_hash")


class ConfirmCalendarPublicationUseCase:
    """Rebuild every preview input and delegate exact publish inside the caller transaction."""

    def __init__(
        self,
        *,
        preparation: CalendarPublicationPreparationPort,
        publisher: CalendarFormalPublicationPort,
        clock: CalendarOperationsClock,
    ) -> None:
        """Bind trusted preparation, existing formal publisher and server clock."""

        self._preparation = preparation
        self._publisher = publisher
        self._clock = clock

    def execute(
        self,
        intent: ConfirmCalendarPublicationIntent,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Re-read, re-seal and publish only an unchanged preview under live authority.

        The returned commit is still inside the caller-owned authority transaction.
        The caller must let that outer context exit successfully before returning
        the result to an HTTP client; this use case never commits or catches errors.
        """

        if type(intent) is not ConfirmCalendarPublicationIntent:
            raise CalendarPublicationOperationsError(
                "Confirmation requires a typed intent",
                code="CALENDAR_PUBLICATION_CONFIRMATION_INVALID",
            )
        intent.__post_init__()
        _validate_publisher(principal)
        confirmed_at = _read_server_clock(self._clock)
        _ensure_clock_after_authorization(confirmed_at, principal)
        context = self._preparation.load_exact(
            intent.snapshot_reference,
            known_at=confirmed_at,
        )
        if context is None:
            raise CalendarPublicationOperationsError(
                "Preview source or publication configuration is no longer available",
                code="CALENDAR_PUBLICATION_PREVIEW_STALE",
                status_code=409,
            )
        if type(context) is not CalendarPublicationPreparationContext:
            raise CalendarPublicationOperationsError(
                "Preparation provider returned an invalid context type",
                code="CALENDAR_PUBLICATION_PREPARATION_INVALID",
            )
        context.validate()
        _ensure_context_known(context, confirmed_at)
        seal = _build_seal(context, intent.snapshot_reference)
        response_expires_at = _response_expiry(seal)
        if confirmed_at >= response_expires_at:
            raise CalendarPublicationOperationsError(
                "Calendar response-age TTL expired before confirmation",
                code="CALENDAR_PUBLICATION_RESPONSE_EXPIRED",
                status_code=409,
            )
        _validate_pointer_scope(context.current_pointer, seal)
        _validate_pointer_scope(intent.expected_pointer, seal)
        current_pointer = context.current_pointer
        exact_current_winner = (
            not current_pointer.is_absent
            and current_pointer.publication_hash == seal.publication_hash
            and current_pointer.activation_id == intent.activation_id
        )
        if current_pointer != intent.expected_pointer and not exact_current_winner:
            raise CalendarPublicationOperationsError(
                "Current publication pointer changed after preview",
                code="CALENDAR_PUBLICATION_POINTER_CHANGED",
                status_code=409,
            )
        identity = _identity_from_seal(seal)
        if identity != intent.expected_identity:
            raise CalendarPublicationOperationsError(
                "Catalog identity changed after preview",
                code="CALENDAR_PUBLICATION_PREVIEW_STALE",
                status_code=409,
            )
        if seal.publication_hash != intent.expected_publication_hash:
            raise CalendarPublicationOperationsError(
                "Expected publication hash no longer matches exact evidence",
                code="CALENDAR_PUBLICATION_PREVIEW_STALE",
                status_code=409,
            )
        preview_hash = _preview_hash(
            reference=intent.snapshot_reference,
            identity=identity,
            # The checksum records the original preview CAS. A post-write
            # pointer is never substituted into the client's original preview.
            pointer=intent.expected_pointer,
            activation_id=intent.activation_id,
            publication_hash=seal.publication_hash,
            first_seen_at=seal.snapshot_first_seen_at,
            snapshot_recorded_at=seal.snapshot_recorded_at,
            source_published_at=seal.snapshot.source_published_at,
            response_expires_at=response_expires_at,
        )
        if preview_hash != intent.preview_hash:
            raise CalendarPublicationOperationsError(
                "Confirmation did not echo the exact server preview",
                code="CALENDAR_PUBLICATION_PREVIEW_HASH_MISMATCH",
                status_code=409,
            )
        _assert_publisher_live(principal)
        request = CalendarFormalPublicationRequest(
            proposed_seal=seal,
            expected_pointer=(current_pointer if exact_current_winner else intent.expected_pointer),
            activation_id=intent.activation_id,
        )
        result = self._publisher.execute(request, principal=principal)
        _assert_publisher_live(principal)
        if type(result) is not CalendarFormalPublicationCommit:
            raise CalendarPublicationOperationsError(
                "Formal publisher returned no typed commit receipt",
                code="CALENDAR_PUBLICATION_COMMIT_INVALID",
            )
        result.__post_init__()
        if (
            not calendar_formal_seals_have_same_evidence(result.record.seal, seal)
            or result.record.activation_id != intent.activation_id
            or result.audit_pair.actor_user_id != principal.user_id
            or result.audit_pair.database_alias != principal.database_alias
        ):
            raise CalendarPublicationOperationsError(
                "Formal publisher receipt is not bound to this request and authority",
                code="CALENDAR_PUBLICATION_COMMIT_BINDING_INVALID",
            )
        return result


@dataclass(frozen=True, slots=True)
class ReadCurrentCalendarIntent:
    """Request an exact current calendar without exposing a client clock."""

    dataset_key: str
    exchange: str

    def __post_init__(self) -> None:
        """Require explicit dataset and exchange identities."""

        _require_bounded_text(self.dataset_key, "dataset_key")
        _require_bounded_text(self.exchange, "exchange")


class ReadCurrentCalendarUseCase:
    """Read exact current state using a server-owned knowledge cutoff."""

    def __init__(
        self,
        *,
        reader: CalendarCurrentPublicationReaderPort,
        clock: CalendarOperationsClock,
    ) -> None:
        """Bind the current reader and an explicit server clock."""

        self._reader = reader
        self._clock = clock

    def execute(
        self,
        intent: ReadCurrentCalendarIntent,
    ) -> CurrentPublishedExchangeCalendar | None:
        """Query the exact current pointer and keep its non-execution boundary."""

        if type(intent) is not ReadCurrentCalendarIntent:
            raise CalendarPublicationOperationsError(
                "Current read requires a typed intent",
                code="CALENDAR_CURRENT_READ_INTENT_INVALID",
            )
        intent.__post_init__()
        as_of = _read_server_clock(self._clock)
        result = self._reader.read_current(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=intent.dataset_key,
                exchange=intent.exchange,
                as_of=as_of,
            )
        )
        if result is None:
            return None
        if type(result) is not CurrentPublishedExchangeCalendar:
            raise CalendarPublicationOperationsError(
                "Current reader returned an invalid result type",
                code="CALENDAR_CURRENT_READ_RESULT_INVALID",
            )
        result.__post_init__()
        if (
            result.record.seal.dataset.value != intent.dataset_key
            or result.record.seal.exchange != intent.exchange
        ):
            raise CalendarPublicationOperationsError(
                "Current reader returned a publication for another dataset or exchange",
                code="CALENDAR_CURRENT_READ_SCOPE_MISMATCH",
            )
        if result.as_of != as_of or result.must_not_execute is not True:
            raise CalendarPublicationOperationsError(
                "Current read result lost its server clock or capability boundary",
                code="CALENDAR_CURRENT_READ_RESULT_INVALID",
            )
        return result


def _build_seal(
    context: CalendarPublicationPreparationContext,
    reference: ExchangeCalendarSnapshotReference,
) -> CalendarFormalPublicationSeal:
    """Reconstruct a content seal from exact repository and catalog evidence."""

    context.validate()
    snapshot = context.snapshot
    if snapshot.reference() != reference:
        raise CalendarPublicationOperationsError(
            "Preparation context returned another source snapshot",
            code="CALENDAR_PUBLICATION_SOURCE_REFERENCE_MISMATCH",
            status_code=409,
        )
    if context.contract.calendar_response_max_age_seconds is None:
        raise MissingConfigError(
            "Exact dataset contract has no calendar response-age TTL",
            code="CALENDAR_FORMAL_TTL_MISSING",
        )
    try:
        return create_calendar_formal_publication_seal(
            dataset=context.contract.key,
            exchange=snapshot.exchange,
            calendar_response_max_age_seconds=context.contract.calendar_response_max_age_seconds,
            contract_recorded_at=context.contract_recorded_at,
            policy=context.policy,
            policy_recorded_at=context.policy_recorded_at,
            snapshot=snapshot,
            member_reference=context.member_reference,
        )
    except CalendarFormalPublicationError as error:
        raise CalendarPublicationOperationsError(
            str(error), code=error.code, status_code=409
        ) from error


def _identity_from_seal(seal: CalendarFormalPublicationSeal) -> CalendarPublicationPreviewIdentity:
    """Project all publication-relevant catalog identity into the preview DTO."""

    seal.validate()
    return CalendarPublicationPreviewIdentity(
        dataset_key=seal.dataset.value,
        contract_version=seal.dataset.contract_version,
        schema_version=seal.dataset.schema_version,
        policy_identity=seal.policy_identity,
        policy_version=seal.policy_version,
        calendar_response_max_age_seconds=seal.calendar_response_max_age_seconds,
    )


def _response_expiry(seal: CalendarFormalPublicationSeal) -> datetime:
    """Compute the source-age expiry from original response completion only."""

    knowledge_anchor = max(
        seal.snapshot_recorded_at,
        seal.contract_recorded_at,
        seal.policy_recorded_at,
    )
    try:
        window = CalendarPublicationWindow(
            snapshot=seal.snapshot,
            calendar_response_max_age_seconds=seal.calendar_response_max_age_seconds,
            published_at=knowledge_anchor,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            superseded_at=None,
        )
    except CalendarPublicationWindowError as error:
        code = (
            "CALENDAR_PUBLICATION_RESPONSE_EXPIRED"
            if error.code == "CALENDAR_WINDOW_EXPIRED_AT_PUBLICATION"
            else error.code
        )
        raise CalendarPublicationOperationsError(str(error), code=code, status_code=409) from error
    return window.response_expires_at


def _preview_hash(
    *,
    reference: ExchangeCalendarSnapshotReference,
    identity: CalendarPublicationPreviewIdentity,
    pointer: CalendarPublicationPointerExpectation,
    activation_id: str,
    publication_hash: str,
    first_seen_at: datetime,
    snapshot_recorded_at: datetime,
    source_published_at: datetime | None,
    response_expires_at: datetime,
) -> str:
    """Hash all client-echoed source/catalog/CAS choices as an unkeyed checksum."""

    payload: dict[str, object] = {
        "schema": _PREVIEW_SCHEMA,
        "snapshot_reference": reference.to_payload(),
        "identity": {
            "dataset_key": identity.dataset_key,
            "contract_version": identity.contract_version,
            "schema_version": identity.schema_version,
            "policy_identity": identity.policy_identity,
            "policy_version": identity.policy_version,
            "calendar_response_max_age_seconds": identity.calendar_response_max_age_seconds,
        },
        "pointer": _pointer_payload(pointer),
        "activation_id": activation_id,
        "publication_hash": publication_hash,
        "first_seen_at": _utc_text(first_seen_at),
        "snapshot_recorded_at": _utc_text(snapshot_recorded_at),
        "source_published_at": (
            _utc_text(source_published_at) if source_published_at is not None else None
        ),
        "response_expires_at": _utc_text(response_expires_at),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _pointer_payload(pointer: CalendarPublicationPointerExpectation) -> dict[str, object]:
    """Serialize the complete pointer expectation for the preview checksum."""

    pointer.validate()
    return {
        "dataset_key": pointer.dataset_key,
        "publication_key": pointer.publication_key,
        "pointer_id": pointer.pointer_id,
        "publication_id": pointer.publication_id,
        "publication_hash": pointer.publication_hash,
        "activation_id": pointer.activation_id,
        "updated_at": _utc_text(pointer.updated_at) if pointer.updated_at is not None else None,
    }


def _validate_pointer_scope(
    pointer: CalendarPublicationPointerExpectation,
    seal: CalendarFormalPublicationSeal,
) -> None:
    """Require the exact pointer read by the preparation port to match the seal."""

    if pointer.dataset_key != seal.dataset.value or pointer.publication_key != seal.publication_key:
        raise CalendarPublicationOperationsError(
            "Current pointer scope differs from the exact calendar publication",
            code="CALENDAR_PUBLICATION_POINTER_SCOPE_MISMATCH",
        )


def _ensure_context_known(
    context: CalendarPublicationPreparationContext,
    known_at: datetime,
) -> None:
    """Prevent source or catalog evidence recorded after the requested cutoff."""

    if any(
        recorded_at > known_at
        for recorded_at in (
            context.snapshot.first_seen_at,
            context.snapshot.recorded_at,
            context.contract_recorded_at,
            context.policy_recorded_at,
        )
    ):
        raise CalendarPublicationOperationsError(
            "Source or catalog evidence was not known at the server cutoff",
            code="CALENDAR_PUBLICATION_EVIDENCE_NOT_KNOWN",
            status_code=409,
        )


def _validate_publisher(principal: LockedCalendarPublisherPrincipal) -> None:
    """Require the exact permission-bearing live principal, not a caller actor id."""

    try:
        actor_match = _ACTOR_RE.fullmatch(principal.actor_id)
        is_valid = (
            principal.actor_type == "django_user"
            and actor_match is not None
            and type(principal.user_id) is int
            and principal.user_id > 0
            and actor_match.group(1) == str(principal.user_id)
            and principal.permission_codename == CALENDAR_PUBLISH_PERMISSION_CODENAME
            and type(principal.permission_id) is int
            and principal.permission_id > 0
            and type(principal.database_alias) is str
            and bool(principal.database_alias)
            and principal.database_alias.strip() == principal.database_alias
            and bool(principal.database_alias.strip())
        )
        _require_utc(principal.verified_at, "principal.verified_at")
    except (AttributeError, TypeError, ValueError) as error:
        raise AuthorizationError(
            "Calendar publication requires a locked publisher permission",
            code="CALENDAR_PUBLISHER_AUTHORITY_INVALID",
        ) from error
    if not is_valid:
        raise AuthorizationError(
            "Calendar publication requires a locked publisher permission",
            code="CALENDAR_PUBLISHER_AUTHORITY_INVALID",
        )
    _assert_publisher_live(principal)


def _assert_publisher_live(principal: LockedCalendarPublisherPrincipal) -> None:
    """Recheck the authority lease immediately before a publish operation."""

    try:
        principal.assert_live()
    except AuthorizationError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise AuthorizationError(
            "Calendar publisher permission lease is not live",
            code="CALENDAR_PUBLISHER_AUTHORITY_INVALID",
        ) from error


def _ensure_clock_after_authorization(
    now: datetime,
    principal: LockedCalendarPublisherPrincipal,
) -> None:
    """Reject clock rollback before the active permission lease was verified."""

    if now < principal.verified_at:
        raise CalendarPublicationOperationsError(
            "Server clock precedes publisher authorization verification",
            code="CALENDAR_OPERATIONS_CLOCK_ROLLBACK",
            status_code=409,
        )


def _read_server_clock(clock: CalendarOperationsClock) -> datetime:
    """Read and strictly validate one injected server clock value."""

    value = clock.now()
    _require_utc(value, "server clock")
    return value


def _require_utc(value: object, field_name: str) -> None:
    """Require an exact timezone-aware UTC datetime without coercion."""

    if type(value) is not datetime or value.tzinfo is None or _utc_offset_seconds(value) != 0:
        raise CalendarPublicationOperationsError(
            f"{field_name} must be timezone-aware UTC",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )


def _utc_offset_seconds(value: datetime) -> float | None:
    """Return an offset only for an exact datetime value."""

    offset = value.utcoffset()
    return None if offset is None else offset.total_seconds()


def _require_bounded_text(value: object, field_name: str) -> None:
    """Require explicit trimmed nonempty text within the catalog identity bound."""

    if type(value) is not str or not value or len(value) > 300 or value.strip() != value:
        raise CalendarPublicationOperationsError(
            f"{field_name} must be explicit bounded text",
            code="CALENDAR_PUBLICATION_IDENTITY_INVALID",
        )


def _require_activation_id(value: object) -> None:
    """Require a canonical activation token accepted by the formal Domain."""

    if type(value) is not str or _ACTIVATION_RE.fullmatch(value) is None:
        raise CalendarPublicationOperationsError(
            "Activation id must be a canonical bounded token",
            code="CALENDAR_PUBLICATION_ACTIVATION_INVALID",
        )


def _require_sha256(value: object, field_name: str) -> None:
    """Require one lowercase, unprefixed SHA-256 digest."""

    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CalendarPublicationOperationsError(
            f"{field_name} must be lowercase SHA-256",
            code="CALENDAR_PUBLICATION_HASH_INVALID",
        )


def _utc_text(value: datetime) -> str:
    """Encode one validated instant in stable UTC text for checksum inputs."""

    _require_utc(value, "canonical datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CalendarActivationIdFactory",
    "CalendarFormalPublicationPort",
    "CalendarOperationsClock",
    "CalendarPublicationOperationsError",
    "CalendarPublicationPreparationContext",
    "CalendarPublicationPreparationPort",
    "CalendarPublicationPreview",
    "CalendarPublicationPreviewIdentity",
    "CalendarSnapshotCapturePort",
    "CaptureExchangeCalendarSnapshotIntent",
    "CaptureExchangeCalendarSnapshotUseCase",
    "CapturedExchangeCalendarSnapshot",
    "ConfirmCalendarPublicationIntent",
    "ConfirmCalendarPublicationUseCase",
    "PreviewCalendarPublicationIntent",
    "PreviewCalendarPublicationUseCase",
    "ReadCurrentCalendarIntent",
    "ReadCurrentCalendarUseCase",
]
