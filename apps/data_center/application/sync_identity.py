"""Server-issued identity contract for future Data Center sync writers.

The existing ``SyncRun``/``SyncBatch`` persistence is not currently wired to
the ordinary SyncMacro path.  This module therefore exposes only a typed,
fail-closed boundary: a composition root must inject an owner-side issuer
that returns identities already persisted in the same transaction as the
future fact/RawAudit/publication writer.  No caller-supplied UUID, request
clock, or random fallback is accepted here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SyncExecutionIdentity:
    """Immutable run/batch correlation issued by a Data Center owner."""

    run_id: str
    ingested_run_id: str
    batch_id: str
    dataset_key: str
    provider_name: str
    identity_hash: str

    def __post_init__(self) -> None:
        for field_name in ("run_id", "ingested_run_id", "batch_id"):
            value = getattr(self, field_name)
            _require_uuid(value, field_name)
        for field_name in ("dataset_key", "provider_name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > 192:
                raise ValueError(f"{field_name} must be a bounded non-empty string")
        if not isinstance(self.identity_hash, str) or len(self.identity_hash) != 64:
            raise ValueError("identity_hash must be a lowercase sha256 digest")
        if any(character not in "0123456789abcdef" for character in self.identity_hash):
            raise ValueError("identity_hash must be a lowercase sha256 digest")
        if self.identity_hash != sync_execution_identity_hash(self):
            raise ValueError("identity_hash does not match the canonical identity")

    @property
    def raw_audit_correlation(self) -> tuple[str, str]:
        """Return the exact run/ingested-run pair for a RawAudit row."""

        return self.run_id, self.ingested_run_id


class SyncExecutionIdentityIssuer(Protocol):
    """Owner-side port that issues an identity inside a caller UOW."""

    def issue(
        self,
        *,
        dataset_key: str,
        provider_name: str,
    ) -> SyncExecutionIdentity:
        """Return an already persisted identity or raise a bounded error."""


class SyncExecutionIdentityRepositoryPort(Protocol):
    """Persistence port for an owner-issued sync execution identity.

    The port deliberately accepts a complete identity rather than selectors
    from which a repository could invent UUIDs or clocks.  Implementations
    must perform an exact idempotent replay or fail closed on a collision.
    """

    def persist(self, identity: SyncExecutionIdentity) -> SyncExecutionIdentity:
        """Persist one complete identity without generating authoritative fields."""

        ...

    def get_by_identity_hash(self, identity_hash: str) -> SyncExecutionIdentity | None:
        """Return the exact identity for a canonical hash, when present."""

        ...


@dataclass(frozen=True, slots=True)
class IssueSyncExecutionIdentityCommand:
    """Request containing only non-authoritative routing selectors."""

    dataset_key: str
    provider_name: str

    def __post_init__(self) -> None:
        for field_name in ("dataset_key", "provider_name"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or len(value) > 192:
                raise ValueError(f"{field_name} must be a bounded non-empty string")


class IssueSyncExecutionIdentityUseCase:
    """Validate an owner-issued identity without creating one locally."""

    __slots__ = ("_issuer",)

    def __init__(self, issuer: SyncExecutionIdentityIssuer) -> None:
        self._issuer = issuer

    def execute(self, command: IssueSyncExecutionIdentityCommand) -> SyncExecutionIdentity:
        """Return an exact identity matching the requested dataset/provider."""

        identity = self._issuer.issue(
            dataset_key=command.dataset_key,
            provider_name=command.provider_name,
        )
        if not isinstance(identity, SyncExecutionIdentity):
            raise TypeError("identity issuer returned an invalid identity type")
        if identity.dataset_key != command.dataset_key:
            raise ValueError("identity dataset_key does not match the command")
        if identity.provider_name != command.provider_name:
            raise ValueError("identity provider_name does not match the command")
        return identity


class PersistSyncExecutionIdentityUseCase:
    """Persist a complete identity supplied by an owner-side issuer.

    This use case is intentionally separate from issuing.  It does not create
    UUIDs, derive a batch id, or sample a request clock; a future composition
    root must provide those values from its server-side transaction context.
    """

    __slots__ = ("_repository",)

    def __init__(self, repository: SyncExecutionIdentityRepositoryPort) -> None:
        self._repository = repository

    def execute(self, identity: SyncExecutionIdentity) -> SyncExecutionIdentity:
        """Persist and return the exact owner-issued identity."""

        if not isinstance(identity, SyncExecutionIdentity):
            raise TypeError("identity must be a SyncExecutionIdentity")
        persisted = self._repository.persist(identity)
        if persisted != identity:
            raise ValueError("identity repository returned a different identity")
        return persisted


def sync_execution_identity_hash(identity: SyncExecutionIdentity) -> str:
    """Compute the domain-separated hash of identity fields only."""

    return _sync_execution_identity_hash_values(
        run_id=identity.run_id,
        ingested_run_id=identity.ingested_run_id,
        batch_id=identity.batch_id,
        dataset_key=identity.dataset_key,
        provider_name=identity.provider_name,
    )


def build_sync_execution_identity(
    *,
    run_id: str,
    ingested_run_id: str,
    batch_id: str,
    dataset_key: str,
    provider_name: str,
) -> SyncExecutionIdentity:
    """Build one complete server-issued identity with its canonical hash."""

    identity_hash = _sync_execution_identity_hash_values(
        run_id=run_id,
        ingested_run_id=ingested_run_id,
        batch_id=batch_id,
        dataset_key=dataset_key,
        provider_name=provider_name,
    )
    return SyncExecutionIdentity(
        run_id=run_id,
        ingested_run_id=ingested_run_id,
        batch_id=batch_id,
        dataset_key=dataset_key,
        provider_name=provider_name,
        identity_hash=identity_hash,
    )


def _sync_execution_identity_hash_values(
    *,
    run_id: str,
    ingested_run_id: str,
    batch_id: str,
    dataset_key: str,
    provider_name: str,
) -> str:
    """Hash the exact five identity fields without a partially built object."""

    payload = {
        "batch_id": batch_id,
        "dataset_key": dataset_key,
        "ingested_run_id": ingested_run_id,
        "provider_name": provider_name,
        "run_id": run_id,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(
        b"agomtradepro:data-center:sync-execution-identity:v1\0" + encoded
    ).hexdigest()


def _require_uuid(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a canonical UUID") from error
    if str(parsed) != value.lower():
        raise ValueError(f"{field_name} must use canonical lowercase UUID text")


__all__ = [
    "build_sync_execution_identity",
    "IssueSyncExecutionIdentityCommand",
    "IssueSyncExecutionIdentityUseCase",
    "PersistSyncExecutionIdentityUseCase",
    "SyncExecutionIdentity",
    "SyncExecutionIdentityIssuer",
    "SyncExecutionIdentityRepositoryPort",
    "sync_execution_identity_hash",
]
