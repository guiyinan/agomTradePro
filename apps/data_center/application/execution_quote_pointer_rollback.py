"""Application contracts for restoring the execution quote pointer safely."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.application.publication_activation import PublicationActivationAuthorityFence
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from core.exceptions import DataValidationError
from core.integration.data_center_audit import SystemAuditReaderContext

_DATASET_KEY = "equity.quote.snapshot"
_PUBLICATION_KEY = "execution"
_DEFAULT_DATABASE_ALIAS = "default"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,299}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ExecutionQuotePointerRollbackError(DataValidationError):
    """Raised when an execution-pointer rollback cannot be proven complete."""

    default_message = "Execution quote pointer rollback failed closed"
    default_code = "EXECUTION_QUOTE_POINTER_ROLLBACK_FAILED"


def _require_token(value: object, field_name: str, *, max_length: int = 300) -> str:
    """Require one bounded, canonical, single-line token."""

    if (
        type(value) is not str
        or not value
        or len(value) > max_length
        or value.strip() != value
        or any(character in value for character in ("\r", "\n"))
        or _TOKEN_PATTERN.fullmatch(value) is None
    ):
        raise ExecutionQuotePointerRollbackError(f"{field_name} is invalid")
    return value


def _require_uuid(value: object, field_name: str) -> str:
    """Require lowercase canonical UUID text."""

    if type(value) is not str:
        raise ExecutionQuotePointerRollbackError(f"{field_name} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ExecutionQuotePointerRollbackError(f"{field_name} must be a UUID") from error
    if str(parsed) != value:
        raise ExecutionQuotePointerRollbackError(f"{field_name} must use canonical UUID form")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Require one lowercase SHA-256 digest."""

    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ExecutionQuotePointerRollbackError(f"{field_name} must be a SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Require and normalize one timezone-aware UTC instant."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionQuotePointerRollbackError(f"{field_name} must be timezone-aware")
    try:
        if value.utcoffset() is None:
            raise ExecutionQuotePointerRollbackError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise ExecutionQuotePointerRollbackError(f"{field_name} is invalid") from error


def _require_reason(value: object) -> str:
    """Require a bounded, non-empty, single-line human rollback explanation."""

    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 1000
        or value != value.strip()
        or any(character in value for character in ("\r", "\n", "\x00"))
    ):
        raise ExecutionQuotePointerRollbackError(
            "reason must be bounded, non-empty, and single-line text"
        )
    return value


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerRollbackCommand:
    """Bind one rollback operation to both exact publications and pointer epoch."""

    rollback_id: str
    target_publication_id: str
    target_publication_hash: str
    expected_current_publication_id: str
    expected_current_publication_hash: str
    expected_current_activation_id: str
    reason: str
    operator: str
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate identities, human reason, and normalized operation time."""

        for field_name in (
            "rollback_id",
            "target_publication_id",
            "expected_current_publication_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        for field_name in ("target_publication_hash", "expected_current_publication_hash"):
            _require_digest(getattr(self, field_name), field_name)
        _require_uuid(self.expected_current_activation_id, "expected_current_activation_id")
        _require_reason(self.reason)
        _require_token(self.operator, "operator", max_length=150)
        object.__setattr__(self, "observed_at", _require_aware(self.observed_at, "observed_at"))
        if self.target_publication_id == self.expected_current_publication_id:
            raise ExecutionQuotePointerRollbackError("rollback target is already current")


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerRollbackAuditObservation:
    """Data Center-owned immutable facts passed to the Audit integration bridge."""

    target_publication_id: str
    target_publication_version: str
    target_publication_hash: str
    rollback_id: str
    rollback_version: str
    rollback_content_hash: str
    previous_publication_id: str
    previous_publication_version: str
    previous_publication_hash: str
    previous_pointer_activation_id: str
    run_id: str
    occurred_at: datetime
    recorded_at: datetime
    tenant_id: str
    owner_id: str

    def __post_init__(self) -> None:
        """Reject incomplete or inconsistent rollback evidence before Audit."""

        for field_name in (
            "target_publication_id",
            "rollback_id",
            "previous_publication_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        for field_name in (
            "target_publication_hash",
            "rollback_content_hash",
            "previous_publication_hash",
        ):
            _require_digest(getattr(self, field_name), field_name)
        for field_name in (
            "target_publication_version",
            "rollback_version",
            "previous_publication_version",
            "previous_pointer_activation_id",
            "run_id",
            "tenant_id",
            "owner_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "recorded_at", recorded_at)
        if occurred_at > recorded_at:
            raise ExecutionQuotePointerRollbackError("rollback audit time order is invalid")
        if self.target_publication_id == self.previous_publication_id:
            raise ExecutionQuotePointerRollbackError("rollback publications must differ")


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerRollbackAuditReceipt:
    """Immutable, identity-bound receipt for the exact Audit event/outbox pair."""

    target_publication_id: str
    target_publication_version: str
    target_publication_hash: str
    rollback_id: str
    rollback_version: str
    rollback_content_hash: str
    previous_publication_id: str
    previous_publication_version: str
    previous_publication_hash: str
    previous_pointer_activation_id: str
    run_id: str
    occurred_at: datetime
    recorded_at: datetime
    tenant_id: str
    owner_id: str
    event_id: str
    event_content_hash: str
    outbox_id: UUID
    idempotency_key: str

    def __post_init__(self) -> None:
        """Require the receipt to retain every rollback and delivery identity."""

        observation = ExecutionQuotePointerRollbackAuditObservation(
            target_publication_id=self.target_publication_id,
            target_publication_version=self.target_publication_version,
            target_publication_hash=self.target_publication_hash,
            rollback_id=self.rollback_id,
            rollback_version=self.rollback_version,
            rollback_content_hash=self.rollback_content_hash,
            previous_publication_id=self.previous_publication_id,
            previous_publication_version=self.previous_publication_version,
            previous_publication_hash=self.previous_publication_hash,
            previous_pointer_activation_id=self.previous_pointer_activation_id,
            run_id=self.run_id,
            occurred_at=self.occurred_at,
            recorded_at=self.recorded_at,
            tenant_id=self.tenant_id,
            owner_id=self.owner_id,
        )
        if type(self.event_id) is not str or not self.event_id:
            raise ExecutionQuotePointerRollbackError("Audit receipt event id is missing")
        _require_digest(self.event_content_hash, "event_content_hash")
        if type(self.outbox_id) is not UUID:
            raise ExecutionQuotePointerRollbackError("Audit receipt outbox id is invalid")
        if self.idempotency_key != f"data-publication-rollback:{observation.rollback_id}":
            raise ExecutionQuotePointerRollbackError("Audit receipt idempotency key differs")


class ExecutionQuotePointerRollbackAuditWriter(Protocol):
    """Same-alias caller-owned Audit/outbox capability for quote rollback."""

    @property
    def database_alias(self) -> str:
        """Return the database alias shared with the Account transaction."""

    def execute_in_caller_transaction(
        self,
        observation: ExecutionQuotePointerRollbackAuditObservation,
        *,
        exact_replay: bool,
    ) -> ExecutionQuotePointerRollbackAuditReceipt:
        """Append or verify the exact rollback event and outbox within the outer UOW."""


class ExecutionQuotePointerRollbackAuthorityCapture(Protocol):
    """Opaque complete Account graph and one-use fence proof."""

    @property
    def database_alias(self) -> str:
        """Return the alias on which the Account graph was captured."""

    @property
    def authority_fence(self) -> PublicationActivationAuthorityFence:
        """Return the live complete-graph fence capability."""

    @property
    def authority_proof(self) -> object:
        """Return the opaque proof consumed by the complete authority fence."""


class ExecutionQuotePointerRollbackAuthorityCaptureFactory(Protocol):
    """Capture current production Account authority after rollback preflight."""

    def __call__(
        self,
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ExecutionQuotePointerRollbackAuthorityCapture:
        """Return the complete graph proof bound to this preflight and database."""


class ExecutionQuotePointerRollbackRepository(Protocol):
    """Infrastructure capability that owns the locked rollback transaction."""

    @property
    def database_alias(self) -> str:
        """Return the pointer, publication, and fact storage alias."""

    def rollback_execution_quote_pointer(
        self,
        command: ExecutionQuotePointerRollbackCommand,
        *,
        audit_writer: ExecutionQuotePointerRollbackAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> ExecutionQuotePointerRollbackResult:
        """Restore one exact execution pointer under Account and evidence locks."""


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerRollbackResult:
    """One restored publication bound to its required Audit/outbox receipt."""

    publication: CanonicalPublication
    rollback_id: str
    audit_receipt: ExecutionQuotePointerRollbackAuditReceipt

    def __post_init__(self) -> None:
        """Require the result publication to match the audited rollback target."""

        if type(self.publication) is not CanonicalPublication:
            raise ExecutionQuotePointerRollbackError("rollback result publication is invalid")
        if (
            self.publication.dataset_key != _DATASET_KEY
            or self.publication.publication_key != _PUBLICATION_KEY
            or self.publication.state is not PublicationState.PUBLISHED
            or self.publication.publication_id != self.audit_receipt.target_publication_id
            or self.publication.publication_hash != self.audit_receipt.target_publication_hash
            or self.rollback_id != self.audit_receipt.rollback_id
        ):
            raise ExecutionQuotePointerRollbackError(
                "rollback result differs from its Audit receipt"
            )


ExecutionQuotePointerRollbackAuditWriterFactory = Callable[
    [], ExecutionQuotePointerRollbackAuditWriter
]


@dataclass(frozen=True, slots=True)
class ExecutionQuotePointerRollbackBundle:
    """One explicit repository, authority, and Audit composition for execution rollback."""

    database_alias: str
    repository: ExecutionQuotePointerRollbackRepository
    audit_writer_factory: ExecutionQuotePointerRollbackAuditWriterFactory
    authority_capture: ExecutionQuotePointerRollbackAuthorityCaptureFactory

    def __post_init__(self) -> None:
        """Reject missing or cross-alias dependencies at composition time."""

        if self.database_alias != _DEFAULT_DATABASE_ALIAS:
            raise ExecutionQuotePointerRollbackError("rollback requires the default database")
        if self.repository.database_alias != self.database_alias:
            raise ExecutionQuotePointerRollbackError("rollback repository database alias differs")


def rollback_execution_quote_pointer(
    *,
    command: ExecutionQuotePointerRollbackCommand,
    bundle: ExecutionQuotePointerRollbackBundle,
    preflight_context: SystemAuditReaderContext,
) -> ExecutionQuotePointerRollbackResult:
    """Restore the exact execution quote pointer through a complete fenced UOW."""

    if type(command) is not ExecutionQuotePointerRollbackCommand:
        raise ExecutionQuotePointerRollbackError("rollback command is invalid")
    command.__post_init__()
    if type(bundle) is not ExecutionQuotePointerRollbackBundle:
        raise ExecutionQuotePointerRollbackError("rollback bundle is invalid")
    bundle.__post_init__()
    if type(preflight_context) is not SystemAuditReaderContext:
        raise ExecutionQuotePointerRollbackError("rollback Audit preflight context is invalid")
    preflight_context.__post_init__()

    as_of = datetime.now(UTC)
    if not preflight_context.can_read_at(as_of):
        raise ExecutionQuotePointerRollbackError("rollback Audit preflight context expired")
    try:
        audit_writer = bundle.audit_writer_factory()
        if audit_writer.database_alias != bundle.database_alias:
            raise ExecutionQuotePointerRollbackError("rollback Audit database alias differs")
        capture = bundle.authority_capture(as_of=as_of, preflight_context=preflight_context)
        if capture.database_alias != bundle.database_alias:
            raise ExecutionQuotePointerRollbackError("rollback Account authority alias differs")
        result = bundle.repository.rollback_execution_quote_pointer(
            command,
            audit_writer=audit_writer,
            authority_fence=capture.authority_fence,
            authority_proof=capture.authority_proof,
        )
    except ExecutionQuotePointerRollbackError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise ExecutionQuotePointerRollbackError(
            "execution pointer rollback failed closed"
        ) from error

    if type(result) is not ExecutionQuotePointerRollbackResult:
        raise ExecutionQuotePointerRollbackError("rollback repository returned an invalid result")
    if (
        result.rollback_id != command.rollback_id
        or result.publication.publication_id != command.target_publication_id
        or result.publication.publication_hash != command.target_publication_hash
        or result.audit_receipt.previous_publication_id != command.expected_current_publication_id
        or result.audit_receipt.previous_publication_hash
        != command.expected_current_publication_hash
        or result.audit_receipt.previous_pointer_activation_id
        != command.expected_current_activation_id
        or result.audit_receipt.occurred_at != command.observed_at
    ):
        raise ExecutionQuotePointerRollbackError("rollback result is not bound to its command")
    return result


__all__ = [
    "ExecutionQuotePointerRollbackAuditObservation",
    "ExecutionQuotePointerRollbackAuditReceipt",
    "ExecutionQuotePointerRollbackAuditWriter",
    "ExecutionQuotePointerRollbackAuthorityCapture",
    "ExecutionQuotePointerRollbackAuthorityCaptureFactory",
    "ExecutionQuotePointerRollbackBundle",
    "ExecutionQuotePointerRollbackCommand",
    "ExecutionQuotePointerRollbackError",
    "ExecutionQuotePointerRollbackRepository",
    "ExecutionQuotePointerRollbackResult",
    "ExecutionQuotePointerRollbackAuditWriterFactory",
    "rollback_execution_quote_pointer",
]
