"""Application contracts for the short current-publication activation UOW."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    SystemAuditEventOutboxCommit,
)


class PublicationActivationError(DataValidationError):
    """Raised when a candidate cannot be atomically made current."""

    default_message = "Canonical publication activation failed"
    default_code = "PUBLICATION_ACTIVATION_ERROR"


def _require_token(value: object, field_name: str, *, max_length: int = 300) -> str:
    """Validate one bounded single-line activation identity token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(character in value for character in ("\r", "\n"))
    ):
        raise PublicationActivationError(f"{field_name} must be a bounded single-line token")
    return value


@dataclass(frozen=True, slots=True)
class PublicationActivationRequest:
    """Exact candidate and pointer compare-and-swap inputs."""

    dataset_key: str
    publication_key: str
    candidate_publication_id: str
    candidate_publication_hash: str
    activation_id: str
    audit_observation: DataPublicationAuditObservation
    expected_current_publication_id: str | None = None
    expected_current_publication_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_key",
            "candidate_publication_id",
            "candidate_publication_hash",
            "activation_id",
        ):
            _require_token(getattr(self, field_name), f"PublicationActivationRequest.{field_name}")
        for field_name in (
            "expected_current_publication_id",
            "expected_current_publication_hash",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_token(value, f"PublicationActivationRequest.{field_name}")
        if type(self.audit_observation) is not DataPublicationAuditObservation:
            raise PublicationActivationError(
                "audit_observation must be canonical publication evidence"
            )


@dataclass(frozen=True, slots=True)
class PublicationActivationAuthorityLease:
    """Account-neutral scope and expiry projection from a complete fence."""

    database_alias: str
    tenant_id: str
    owner_id: str
    generation: int
    graph_hash: str
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in ("database_alias", "tenant_id", "owner_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value.strip() != value:
                raise PublicationActivationError(f"authority lease {field_name} is invalid")
        if (
            type(self.graph_hash) is not str
            or len(self.graph_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.graph_hash)
        ):
            raise PublicationActivationError("authority lease graph digest is invalid")
        if type(self.generation) is not int or self.generation < 0:
            raise PublicationActivationError("authority lease generation is invalid")
        if (
            type(self.valid_until) is not datetime
            or self.valid_until.tzinfo is None
            or self.valid_until.utcoffset() is None
        ):
            raise PublicationActivationError("authority lease expiry must be timezone-aware")
        if (
            type(self.checked_at) is not datetime
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise PublicationActivationError("authority lease cutoff must be timezone-aware")
        if self.checked_at >= self.valid_until:
            raise PublicationActivationError("authority lease cutoff must precede expiry")


class PublicationActivationAuthorityFence(Protocol):
    """Minimal complete-fence capability required by activation."""

    def fence_complete(self, proof: object) -> AbstractContextManager[object]:
        """Yield one validated complete graph while its outer RC/RW transaction is open."""


def publication_activation_lease_from_complete_graph(
    result: object,
) -> PublicationActivationAuthorityLease:
    """Project the exact complete-fence result without rereading authority scope."""

    if getattr(result, "scope", None) != "account_authority_complete_graph":
        raise PublicationActivationError("complete authority result scope is invalid")
    fingerprint = getattr(result, "fingerprint", None)
    graph_hash = getattr(fingerprint, "complete_graph_hash", None)
    try:
        return PublicationActivationAuthorityLease(
            database_alias=cast(str, _required_attribute(result, "database_alias")),
            tenant_id=cast(str, _required_attribute(result, "tenant_id")),
            owner_id=cast(str, _required_attribute(result, "owner_id")),
            generation=cast(int, _required_attribute(result, "generation")),
            graph_hash=cast(str, graph_hash),
            checked_at=cast(datetime, _required_attribute(result, "checked_at")),
            valid_until=cast(datetime, _required_attribute(result, "valid_until")),
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise PublicationActivationError(
            "complete authority result cannot provide an activation lease"
        ) from error


def _required_attribute(value: object, name: str) -> object:
    """Read one required structural attribute across the Account boundary."""

    return getattr(value, name)


class PublicationActivationAuditWriter(Protocol):
    """Required audit plus outbox append inside the caller's transaction."""

    @property
    def database_alias(self) -> str:
        """Return the exact alias shared with activation."""

    def append_required(
        self,
        *,
        request: PublicationActivationRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append the required publication event and matching outbox row."""


class PublicationActivationRepository(Protocol):
    """Infrastructure port for one short candidate activation transaction."""

    def activate_candidate(
        self,
        request: PublicationActivationRequest,
        *,
        audit_writer: PublicationActivationAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> CanonicalPublication:
        """Revalidate and atomically switch the current pointer."""


class ActivateCanonicalPublicationUseCase:
    """Run candidate activation without composing any production writer."""

    def __init__(self, repository: PublicationActivationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        request: PublicationActivationRequest,
        *,
        audit_writer: PublicationActivationAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> CanonicalPublication:
        """Activate one exact candidate after all repository-side rechecks."""

        return self._repository.activate_candidate(
            request,
            audit_writer=audit_writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )


__all__ = [
    "ActivateCanonicalPublicationUseCase",
    "PublicationActivationAuditWriter",
    "PublicationActivationAuthorityFence",
    "PublicationActivationAuthorityLease",
    "PublicationActivationError",
    "publication_activation_lease_from_complete_graph",
    "PublicationActivationRepository",
    "PublicationActivationRequest",
]
