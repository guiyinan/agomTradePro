"""Application contracts for the short current-publication activation UOW."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from apps.data_center.domain.raw_audit_manifest import (
    CURRENT_MARKET_PUBLICATION_DATASETS,
    CandidateRawAuditManifest,
    requires_group_publication_activation,
)
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    DataPublicationManifestAuditObservation,
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
class PublicationActivationGroupCandidate:
    """One exact candidate and current-pointer CAS within a group activation."""

    dataset_key: str
    publication_key: str
    candidate_publication_id: str
    candidate_publication_hash: str
    expected_current_publication_id: str | None = None
    expected_current_publication_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate candidate identity and require a complete optional CAS pair."""

        for field_name in (
            "dataset_key",
            "publication_key",
            "candidate_publication_id",
            "candidate_publication_hash",
        ):
            _require_token(
                getattr(self, field_name),
                f"PublicationActivationGroupCandidate.{field_name}",
            )
        if len(self.candidate_publication_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.candidate_publication_hash
        ):
            raise PublicationActivationError("candidate publication hash is invalid")
        _require_canonical_uuid(self.candidate_publication_id, "candidate_publication_id")
        expected_id = self.expected_current_publication_id
        expected_hash = self.expected_current_publication_hash
        if (expected_id is None) != (expected_hash is None):
            raise PublicationActivationError("expected current pointer CAS pair is incomplete")
        if expected_id is not None:
            _require_canonical_uuid(expected_id, "expected_current_publication_id")
            if len(expected_hash or "") != 64 or any(
                character not in "0123456789abcdef" for character in expected_hash or ""
            ):
                raise PublicationActivationError("expected current publication hash is invalid")


_GROUP_ACTIVATION_DATASETS = CURRENT_MARKET_PUBLICATION_DATASETS


@dataclass(frozen=True, slots=True)
class PublicationActivationGroupRequest:
    """One indivisible fixed market current set: price, quote, and valuation."""

    activation_id: str
    candidates: tuple[PublicationActivationGroupCandidate, ...]

    def __post_init__(self) -> None:
        """Require exactly one candidate for each supported market publication."""

        _require_token(self.activation_id, "PublicationActivationGroupRequest.activation_id")
        if not isinstance(self.candidates, tuple) or len(self.candidates) != 3:
            raise PublicationActivationError(
                "market group activation contract requires exactly three candidates"
            )
        if any(type(item) is not PublicationActivationGroupCandidate for item in self.candidates):
            raise PublicationActivationError("group activation contains an invalid candidate")
        datasets = tuple(item.dataset_key for item in self.candidates)
        if set(datasets) != _GROUP_ACTIVATION_DATASETS or len(set(datasets)) != 3:
            raise PublicationActivationError(
                "market group activation contract requires current price, quote, and valuation"
            )
        if any(item.publication_key != "current" for item in self.candidates):
            raise PublicationActivationError(
                "market group activation contract only accepts current publications"
            )
        scopes = tuple((item.dataset_key, item.publication_key) for item in self.candidates)
        identities = tuple(item.candidate_publication_id for item in self.candidates)
        if len(set(scopes)) != len(scopes) or len(set(identities)) != len(identities):
            raise PublicationActivationError("group activation identities must be unique")
        ordered = tuple(
            sorted(
                self.candidates,
                key=lambda item: (
                    item.dataset_key,
                    item.publication_key,
                    item.candidate_publication_id,
                ),
            )
        )
        object.__setattr__(self, "candidates", ordered)


@dataclass(frozen=True, slots=True)
class CurrentPublicationPointerSnapshot:
    """Exact current-pointer CAS state read before candidate staging."""

    publication_id: str | None
    publication_hash: str | None

    def __post_init__(self) -> None:
        """Require either a fully empty pointer or one complete publication identity."""

        if (self.publication_id is None) != (self.publication_hash is None):
            raise PublicationActivationError("current pointer snapshot is incomplete")
        if self.publication_id is None:
            return
        _require_canonical_uuid(self.publication_id, "current_pointer.publication_id")
        digest = self.publication_hash or ""
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise PublicationActivationError("current pointer snapshot hash is invalid")


def _require_canonical_uuid(value: str, field_name: str) -> None:
    """Require one lowercase canonical UUID at the activation request boundary."""

    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise PublicationActivationError(f"{field_name} must be a UUID") from error
    if str(parsed) != value:
        raise PublicationActivationError(f"{field_name} must use canonical UUID form")


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


class PublicationActivationGroupAuditWriter(Protocol):
    """Required manifest-bound audit append used only by group activation."""

    @property
    def database_alias(self) -> str:
        """Return the exact alias shared with activation."""

    def append_manifest_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        manifest: CandidateRawAuditManifest,
        observation: DataPublicationManifestAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append one required event/outbox pair bound to a full manifest."""

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append the complete activation group's event/outbox pairs in one batch."""


@dataclass(frozen=True, slots=True)
class PublicationActivationManifestAuditWrite:
    """One validated manifest audit write within an atomic activation group."""

    publication: CanonicalPublication
    members: tuple[PublicationMember, ...]
    manifest: CandidateRawAuditManifest
    observation: DataPublicationManifestAuditObservation

    def __post_init__(self) -> None:
        """Require every audit input to name the same exact candidate."""

        publication_id = self.publication.publication_id
        if (
            self.manifest.publication_id != publication_id
            or self.observation.publication_id != publication_id
            or len(self.members) != self.publication.member_count
        ):
            raise PublicationActivationError("manifest audit write identity differs")


class PublicationActivationGroupRepository(Protocol):
    """Infrastructure port for fixed quote, price, and valuation activation."""

    def activate_candidate_group(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        """Validate and switch price, quote, and valuation as one fenced unit."""


class PublicationActivationRepository(PublicationActivationGroupRepository, Protocol):
    """Infrastructure port for both single-publication and group activation."""

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

        if requires_group_publication_activation(request.dataset_key):
            raise PublicationActivationError(
                "current market publication requires atomic group activation"
            )
        return self._repository.activate_candidate(
            request,
            audit_writer=audit_writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )


class ActivateCanonicalPublicationGroupUseCase:
    """Activate the three current market publications in one complete-fence UOW."""

    def __init__(self, repository: PublicationActivationGroupRepository) -> None:
        """Bind the use case to a group-capable publication repository."""

        self._repository = repository

    def execute(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: PublicationActivationAuthorityFence,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        """Activate all request members or raise before exposing a partial group."""

        return self._repository.activate_candidate_group(
            request,
            audit_writer=audit_writer,
            authority_fence=authority_fence,
            authority_proof=authority_proof,
        )


__all__ = [
    "ActivateCanonicalPublicationGroupUseCase",
    "ActivateCanonicalPublicationUseCase",
    "CurrentPublicationPointerSnapshot",
    "PublicationActivationAuditWriter",
    "PublicationActivationGroupAuditWriter",
    "PublicationActivationGroupCandidate",
    "PublicationActivationGroupRequest",
    "PublicationActivationGroupRepository",
    "PublicationActivationManifestAuditWrite",
    "PublicationActivationAuthorityFence",
    "PublicationActivationAuthorityLease",
    "PublicationActivationError",
    "publication_activation_lease_from_complete_graph",
    "PublicationActivationRepository",
    "PublicationActivationRequest",
]
