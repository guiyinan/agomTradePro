"""Fail-closed owner/tenant scope contract for exact Research evidence reads.

This module is deliberately dormant until a trusted owner-scope provider is
available.  It does not inspect Django users, tenant tables, sessions, or
request payloads; a composition root must inject the provider and the normal
exact-read facade.  The wrapper prevents an evidence repository call unless
the provider returns an exact, current read grant for the requested artifact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from apps.research.domain.evidence_contracts import (
    ArtifactRef,
)


class EvidenceScopeUnavailable(RuntimeError):
    """Raised when no current trusted scope grant can be proven."""


class EvidenceScopeCorruption(RuntimeError):
    """Raised when a provider returns a substituted or malformed scope grant."""


@dataclass(frozen=True, slots=True)
class EvidenceScopeGrant:
    """Immutable provider-issued read scope for one exact evidence artifact."""

    scope_id: str
    scope_version: str
    actor_id: str
    owner_id: str
    tenant_id: str
    account_id: str
    artifact: ArtifactRef
    status: str
    permission: str
    recorded_at: datetime
    valid_until: datetime
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "scope_id",
            "scope_version",
            "actor_id",
            "owner_id",
            "tenant_id",
            "account_id",
            "status",
            "permission",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        # Re-run the nested value-object invariant as part of this boundary.
        # A provider must not be able to mutate an ArtifactRef in place and
        # then make the altered identity look valid by recomputing the grant
        # hash.
        ArtifactRef.__post_init__(self.artifact)
        for field_name in ("recorded_at", "valid_until"):
            value = getattr(self, field_name)
            if type(value) is not datetime or value.tzinfo is None:
                raise TypeError(f"{field_name} must be timezone-aware")
        if self.recorded_at >= self.valid_until:
            raise ValueError("scope validity window is invalid")
        if self.status not in {"active", "revoked"}:
            raise ValueError("scope status is not canonical")
        if self.permission != "read_only":
            raise ValueError("scope permission must be read_only")
        expected_hash = evidence_scope_grant_hash(self)
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("scope grant content_hash is invalid")


class EvidenceScopeProvider(Protocol):
    """Trusted server-side port for one exact current scope grant."""

    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant | None:
        """Return a scope grant derived from trusted owner/tenant state."""


class EvidenceScopeAuthorizer:
    """Require exact current scope before an evidence repository is touched."""

    __slots__ = ("_provider",)

    def __init__(self, provider: EvidenceScopeProvider) -> None:
        self._provider = provider

    def require(self, *, artifact: ArtifactRef, as_of: datetime) -> EvidenceScopeGrant:
        """Return an exact active grant or raise a stable fail-closed error."""

        if type(artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        ArtifactRef.__post_init__(artifact)
        if type(as_of) is not datetime or as_of.tzinfo is None:
            raise TypeError("as_of must be timezone-aware")
        try:
            grant = self._provider.get_current_scope(artifact=artifact, as_of=as_of)
        except (EvidenceScopeUnavailable, EvidenceScopeCorruption):
            raise
        except Exception:
            # Provider implementations may reach a database or RBAC service.
            # Do not let implementation details escape the owner-scoped read
            # boundary; an unavailable authority is safer than a broad read.
            raise EvidenceScopeUnavailable("current evidence scope is unavailable") from None
        if grant is None:
            raise EvidenceScopeUnavailable("current evidence scope is unavailable")
        if type(grant) is not EvidenceScopeGrant:
            raise EvidenceScopeCorruption("scope provider returned an invalid grant type")
        try:
            # Re-run the complete immutable value-object contract at the
            # authority boundary.  A provider must not be able to substitute
            # a permission or identity field and make that substitution look
            # valid merely by recomputing the content hash.
            grant.__post_init__()
            if grant.content_hash != evidence_scope_grant_hash(grant):
                raise EvidenceScopeCorruption("scope grant content hash substitution")
        except (TypeError, ValueError) as error:
            raise EvidenceScopeCorruption("scope grant canonical payload is invalid") from error
        if grant.artifact != artifact:
            raise EvidenceScopeCorruption("scope grant artifact substitution")
        if grant.status != "active" or grant.recorded_at > as_of or grant.valid_until <= as_of:
            raise EvidenceScopeUnavailable("evidence scope is inactive or expired")
        return grant


def evidence_scope_grant_hash(grant: EvidenceScopeGrant) -> str:
    """Return the domain-separated canonical grant content hash."""

    payload = {
        "account_id": grant.account_id,
        "actor_id": grant.actor_id,
        "owner_id": grant.owner_id,
        "artifact": grant.artifact.to_payload(),
        "permission": grant.permission,
        "scope_id": grant.scope_id,
        "scope_version": grant.scope_version,
        "status": grant.status,
        "tenant_id": grant.tenant_id,
        "recorded_at": _utc_text(grant.recorded_at),
        "valid_until": _utc_text(grant.valid_until),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(b"agomtradepro:research:evidence-scope:v1\0" + encoded).hexdigest()


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
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "EvidenceScopeAuthorizer",
    "EvidenceScopeCorruption",
    "EvidenceScopeGrant",
    "EvidenceScopeProvider",
    "EvidenceScopeUnavailable",
    "evidence_scope_grant_hash",
]
