"""Dormant Application contract for issuing immutable Evidence scope sources.

This module is intentionally not wired into HTTP, CLI, Agent, Evidence
composition, or a production writer.  It accepts only an injected immutable
observation provider and a repository-owned unit of work.  Owner, tenant,
account, actor, validity facts, and the authoritative clock therefore come
from server-side ports rather than a caller, request, Django model, or session.

The contract is useful for a future owner/tenant lifecycle composition, but it
does not itself establish that such a lifecycle exists.  The B/S CLI boundary
is unchanged: users submit requests to the server and never run local AI,
provider, or Agent software.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from apps.research.application.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1Corruption,
    EvidenceScopeSourceV1Repository,
    EvidenceScopeSourceV1Unavailable,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
    validate_evidence_scope_source_v1_successor,
)


class EvidenceScopeSourceV1LifecycleUnavailable(EvidenceScopeSourceV1Unavailable):
    """The immutable lifecycle observation or repository is unavailable."""


class EvidenceScopeSourceV1LifecycleCorruption(EvidenceScopeSourceV1Corruption):
    """An observation, winner, head, or append result was substituted."""


class EvidenceScopeSourceV1LifecycleConflict(RuntimeError):
    """The immutable winner or predecessor CAS differs from this issuance."""


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class EvidenceScopeSourceV1Observation:
    """One immutable current owner/tenant observation supplied by the server.

    The observation contains the authority facts needed to construct a scope
    source, but the lifecycle command never accepts those facts directly.  A
    provider must return this exact value object for the requested observation
    identity and cutoff.
    """

    observation_id: str
    observation_version: str
    owner_id: str
    tenant_id: str
    account_id: str
    actor_id: str
    artifact: ArtifactRef
    status: str
    recorded_at: datetime
    valid_until: datetime
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate and seal the immutable observation payload."""

        for field_name in (
            "observation_id",
            "observation_version",
            "owner_id",
            "tenant_id",
            "account_id",
            "actor_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        ArtifactRef.__post_init__(self.artifact)
        if self.artifact.owner != "research":
            raise ValueError("observation artifact owner must be research")
        if type(self.status) is not str or self.status not in {"active", "revoked"}:
            raise ValueError("observation status must be active or revoked")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("observation recorded_at must precede valid_until")
        expected = evidence_scope_source_v1_observation_hash(self)
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected:
                raise ValueError("observation content_hash is invalid")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this provider observation is active at the cutoff."""

        _require_aware(as_of, "as_of")
        return self.status == "active" and self.recorded_at <= as_of < self.valid_until


def evidence_scope_source_v1_observation_hash(
    observation: EvidenceScopeSourceV1Observation,
) -> str:
    """Return the canonical content hash for one immutable observation."""

    if type(observation) is not EvidenceScopeSourceV1Observation:
        raise TypeError("observation must be an exact EvidenceScopeSourceV1Observation")
    payload = {
        "account_id": observation.account_id,
        "actor_id": observation.actor_id,
        "artifact": observation.artifact.to_payload(),
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "owner_id": observation.owner_id,
        "recorded_at": _utc_text(observation.recorded_at),
        "status": observation.status,
        "tenant_id": observation.tenant_id,
        "valid_until": _utc_text(observation.valid_until),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(
        b"agomtradepro:research:evidence-scope-source-observation:v1\0" + encoded
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class IssueEvidenceScopeSourceV1Command:
    """ID-only selector for one server-side scope-source issuance."""

    source_id: str
    source_version: str
    observation_id: str
    observation_version: str
    expected_observation_content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_version",
            "observation_id",
            "observation_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(
            self.expected_observation_content_hash,
            "expected_observation_content_hash",
        )


class ExactCurrentEvidenceScopeSourceV1ObservationProvider(Protocol):
    """Load one exact immutable owner/tenant observation at a server cutoff."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1Observation | None:
        """Return the exact current observation, or ``None`` when unavailable."""


class EvidenceScopeSourceV1LifecycleRepository(EvidenceScopeSourceV1Repository, Protocol):
    """Repository-owned atomic writer layered on the existing read port."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned issuance unit of work."""

    def now(self) -> datetime:
        """Return the authoritative server clock inside the unit of work."""

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        """Return the immutable first winner for one source identity."""

    def append(
        self,
        source: EvidenceScopeSourceV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> EvidenceScopeSourceV1:
        """Append a root/successor under exact predecessor compare-and-swap."""


class IssueEvidenceScopeSourceV1:
    """Issue or replay one immutable scope source using only server-side ports.

    This use case is dormant.  It is not a production lifecycle issuer until
    a trusted owner/tenant source and a repository composition root explicitly
    inject both ports.
    """

    __slots__ = ("_observation_provider", "_repository", "_validity_period")

    def __init__(
        self,
        *,
        observation_provider: ExactCurrentEvidenceScopeSourceV1ObservationProvider,
        repository: EvidenceScopeSourceV1LifecycleRepository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._observation_provider = observation_provider
        self._repository = repository
        self._validity_period = validity_period

    def execute(self, command: IssueEvidenceScopeSourceV1Command) -> EvidenceScopeSourceV1:
        """Issue/replay one source with winner-first, double-read, and CAS rules."""

        if type(command) is not IssueEvidenceScopeSourceV1Command:
            raise TypeError("command must be exact IssueEvidenceScopeSourceV1Command")
        IssueEvidenceScopeSourceV1Command.__post_init__(command)
        try:
            with self._repository.atomic():
                cutoff = self._read_cutoff()
                winner = self._read_winner(command, cutoff)
                if winner is not None:
                    # A committed immutable winner is the idempotency source.
                    # Do not require the mutable/current observation or logical
                    # head to remain live for a historical retry.
                    self._validate_winner(winner, command, cutoff)
                    return winner
                first = self._read_observation(command, cutoff)
                head = self._read_head(command, cutoff)
                final = self._read_observation(command, cutoff)
                if final != first:
                    raise EvidenceScopeSourceV1LifecycleConflict(
                        "owner/tenant observation changed during issuance"
                    )
                predecessor = self._validate_predecessor(head, command, final, cutoff)
                source = self._build_source(
                    command,
                    final,
                    cutoff,
                    predecessor=predecessor,
                )
                persisted = self._append(
                    source,
                    expected_predecessor_hash=(
                        predecessor.content_hash if predecessor is not None else None
                    ),
                    recorded_at=cutoff,
                )
                if persisted != source:
                    raise EvidenceScopeSourceV1LifecycleConflict(
                        "concurrent scope-source first winner differs"
                    )
                return persisted
        except (
            EvidenceScopeSourceV1LifecycleUnavailable,
            EvidenceScopeSourceV1LifecycleCorruption,
            EvidenceScopeSourceV1LifecycleConflict,
        ):
            raise
        except EvidenceScopeSourceV1Unavailable as error:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source lifecycle is unavailable"
            ) from error
        except EvidenceScopeSourceV1Corruption as error:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "scope-source lifecycle is corrupt"
            ) from error
        except (TypeError, ValueError) as error:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "scope-source lifecycle returned invalid data"
            ) from error
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source lifecycle is unavailable"
            ) from None

    def _read_cutoff(self) -> datetime:
        try:
            cutoff = self._repository.now()
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source server clock is unavailable"
            ) from None
        try:
            _require_aware(cutoff, "repository cutoff")
        except ValueError as error:
            raise EvidenceScopeSourceV1LifecycleCorruption(str(error)) from error
        return cutoff

    def _read_observation(
        self,
        command: IssueEvidenceScopeSourceV1Command,
        cutoff: datetime,
    ) -> EvidenceScopeSourceV1Observation:
        try:
            value = self._observation_provider.get_exact_current(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                expected_content_hash=command.expected_observation_content_hash,
                as_of=cutoff,
            )
        except (
            EvidenceScopeSourceV1LifecycleUnavailable,
            EvidenceScopeSourceV1LifecycleCorruption,
            EvidenceScopeSourceV1LifecycleConflict,
        ):
            raise
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "owner/tenant observation is unavailable"
            ) from None
        if value is None:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "exact owner/tenant observation is unavailable"
            )
        if type(value) is not EvidenceScopeSourceV1Observation:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "owner/tenant observation type substitution"
            )
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "owner/tenant observation is corrupt"
            ) from error
        if (
            value.observation_id != command.observation_id
            or value.observation_version != command.observation_version
            or value.content_hash != command.expected_observation_content_hash
        ):
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "owner/tenant observation identity substitution"
            )
        if value.recorded_at > cutoff:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "owner/tenant observation is from the future"
            )
        if not value.is_current_at(cutoff):
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "owner/tenant observation is terminal or expired"
            )
        return value

    def _read_winner(
        self,
        command: IssueEvidenceScopeSourceV1Command,
        cutoff: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        try:
            value = self._repository.get_winner(
                source_id=command.source_id,
                source_version=command.source_version,
                as_of=cutoff,
            )
        except (
            EvidenceScopeSourceV1LifecycleUnavailable,
            EvidenceScopeSourceV1LifecycleCorruption,
            EvidenceScopeSourceV1LifecycleConflict,
        ):
            raise
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source winner is unavailable"
            ) from None
        return _restore_source(value) if value is not None else None

    def _read_head(
        self,
        command: IssueEvidenceScopeSourceV1Command,
        cutoff: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        try:
            value = self._repository.get_current_head(
                source_id=command.source_id,
                as_of=cutoff,
            )
        except (
            EvidenceScopeSourceV1LifecycleUnavailable,
            EvidenceScopeSourceV1LifecycleCorruption,
            EvidenceScopeSourceV1LifecycleConflict,
        ):
            raise
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source current head is unavailable"
            ) from None
        return _restore_source(value) if value is not None else None

    def _append(
        self,
        source: EvidenceScopeSourceV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> EvidenceScopeSourceV1:
        try:
            value = self._repository.append(
                source,
                expected_predecessor_hash=expected_predecessor_hash,
                recorded_at=recorded_at,
            )
        except (
            EvidenceScopeSourceV1LifecycleUnavailable,
            EvidenceScopeSourceV1LifecycleCorruption,
            EvidenceScopeSourceV1LifecycleConflict,
        ):
            raise
        except Exception:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source append is unavailable"
            ) from None
        return _restore_source(value)

    def _build_source(
        self,
        command: IssueEvidenceScopeSourceV1Command,
        observation: EvidenceScopeSourceV1Observation,
        cutoff: datetime,
        *,
        predecessor: EvidenceScopeSourceV1 | None,
    ) -> EvidenceScopeSourceV1:
        valid_until = min(observation.valid_until, cutoff + self._validity_period)
        if cutoff >= valid_until:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "owner/tenant observation expires before source issuance"
            )
        if predecessor is not None:
            root_claim_hash = None
            supersedes_content_hash = predecessor.content_hash
        else:
            root_claim_hash = root_claim_hash_for_evidence_scope_source_v1(
                source_id=command.source_id,
                owner_id=observation.owner_id,
                tenant_id=observation.tenant_id,
                account_id=observation.account_id,
                actor_id=observation.actor_id,
                artifact=observation.artifact,
            )
            supersedes_content_hash = None
        try:
            source = EvidenceScopeSourceV1(
                source_id=command.source_id,
                source_version=command.source_version,
                owner_id=observation.owner_id,
                tenant_id=observation.tenant_id,
                account_id=observation.account_id,
                actor_id=observation.actor_id,
                artifact=observation.artifact,
                status="active",
                recorded_at=cutoff,
                valid_until=valid_until,
                root_claim_hash=root_claim_hash,
                supersedes_content_hash=supersedes_content_hash,
            )
        except (TypeError, ValueError) as error:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "issued scope-source payload is invalid"
            ) from error
        if predecessor is not None:
            try:
                validate_evidence_scope_source_v1_successor(predecessor, source)
            except (TypeError, ValueError) as error:
                raise EvidenceScopeSourceV1LifecycleConflict(
                    "issued scope-source successor is not a valid CAS successor"
                ) from error
        return source

    @staticmethod
    def _validate_winner(
        winner: EvidenceScopeSourceV1,
        command: IssueEvidenceScopeSourceV1Command,
        cutoff: datetime,
    ) -> None:
        if winner.source_id != command.source_id or winner.source_version != command.source_version:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "scope-source winner identity substitution"
            )
        if winner.status != "active":
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "scope-source winner status substitution"
            )
        if winner.recorded_at > cutoff:
            raise EvidenceScopeSourceV1LifecycleCorruption("scope-source winner is from the future")
        if winner.is_knowable_at(cutoff) is not True:
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source winner is not knowable at the cutoff"
            )

    @staticmethod
    def _validate_predecessor(
        head: EvidenceScopeSourceV1 | None,
        command: IssueEvidenceScopeSourceV1Command,
        observation: EvidenceScopeSourceV1Observation,
        cutoff: datetime,
    ) -> EvidenceScopeSourceV1 | None:
        if head is None:
            return None
        if head.source_id != command.source_id:
            raise EvidenceScopeSourceV1LifecycleCorruption(
                "scope-source current-head identity substitution"
            )
        _validate_source_observation_binding(head, observation)
        if not head.is_temporally_current_at(cutoff):
            raise EvidenceScopeSourceV1LifecycleUnavailable(
                "scope-source current head is terminal or expired"
            )
        return head


def _restore_source(value: object) -> EvidenceScopeSourceV1:
    if type(value) is not EvidenceScopeSourceV1:
        raise EvidenceScopeSourceV1LifecycleCorruption(
            "scope-source repository record type substitution"
        )
    source = value
    try:
        source.__post_init__()
    except (TypeError, ValueError, AttributeError) as error:
        raise EvidenceScopeSourceV1LifecycleCorruption(
            "scope-source repository record is corrupt"
        ) from error
    return source


def _validate_source_observation_binding(
    source: EvidenceScopeSourceV1,
    observation: EvidenceScopeSourceV1Observation,
) -> None:
    if (
        source.owner_id,
        source.tenant_id,
        source.account_id,
        source.actor_id,
        source.artifact,
    ) != (
        observation.owner_id,
        observation.tenant_id,
        observation.account_id,
        observation.actor_id,
        observation.artifact,
    ):
        raise EvidenceScopeSourceV1LifecycleCorruption(
            "scope-source authority observation substitution"
        )


__all__ = [
    "EvidenceScopeSourceV1LifecycleConflict",
    "EvidenceScopeSourceV1LifecycleCorruption",
    "EvidenceScopeSourceV1LifecycleRepository",
    "EvidenceScopeSourceV1LifecycleUnavailable",
    "EvidenceScopeSourceV1Observation",
    "ExactCurrentEvidenceScopeSourceV1ObservationProvider",
    "IssueEvidenceScopeSourceV1",
    "IssueEvidenceScopeSourceV1Command",
    "evidence_scope_source_v1_observation_hash",
]
