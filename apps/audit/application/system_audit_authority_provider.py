"""Provider-backed scoped authority composition for system-audit reads.

The audit application must not derive authority from a Django request, a
mutable ``User``/``Profile`` row, or a caller-provided role.  This module
defines the small application port that a composition root can implement with
the immutable Account actor-authority and Research scope ledgers.

The selector is intentionally an input to the composition root, not to a
request handler.  It represents an externally issued exact bundle of source
identities and content hashes.  Until an issuer and the two concrete readers
are wired, the provider simply returns ``None`` and the existing composition
boundary remains fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.audit.application.system_audit_composition import (
    SystemAuditAuthorityProvider,
    SystemAuditAuthoritySnapshot,
    system_audit_authority_content_hash,
)


def _token(value: object, field: str) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} must be a bounded canonical token")


def _digest(value: object, field: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _aware(value: object, field: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityBundleSelector:
    """Exact source bundle selected by a trusted authority issuer.

    The selector carries no mutable request state.  Its child content hashes
    become part of the derived bundle identity, so a reader cannot substitute
    another immutable version with the same source ID and version.
    """

    actor_source_id: str
    actor_source_version: str
    actor_content_hash: str
    scope_source_id: str
    scope_source_version: str
    scope_content_hash: str

    def __post_init__(self) -> None:
        for name, value in (
            ("actor_source_id", self.actor_source_id),
            ("actor_source_version", self.actor_source_version),
            ("scope_source_id", self.scope_source_id),
            ("scope_source_version", self.scope_source_version),
        ):
            _token(value, name)
        _digest(self.actor_content_hash, "actor_content_hash")
        _digest(self.scope_content_hash, "scope_content_hash")

    def canonical_key(self) -> str:
        """Return a stable digest for this exact two-ledger selection."""

        payload = {
            "actor_content_hash": self.actor_content_hash,
            "actor_source_id": self.actor_source_id,
            "actor_source_version": self.actor_source_version,
            "scope_content_hash": self.scope_content_hash,
            "scope_source_id": self.scope_source_id,
            "scope_source_version": self.scope_source_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(b"audit.system-authority-bundle.v1\0" + encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SystemAuditActorAuthorityFacts:
    """Immutable Account actor facts projected by an injected reader."""

    source_id: str
    source_version: str
    content_hash: str
    actor_id: str
    user_id: int
    is_authenticated: bool
    is_staff: bool
    role: str
    authority_state: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("actor_id", self.actor_id),
            ("role", self.role),
            ("authority_state", self.authority_state),
        ):
            _token(value, name)
        _digest(self.content_hash, "content_hash")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if type(self.is_authenticated) is not bool or type(self.is_staff) is not bool:
            raise TypeError("authority flags must be bool")
        if self.authority_state not in {"active", "revoked"}:
            raise ValueError("authority_state must be active or revoked")
        _aware(self.recorded_at, "recorded_at")
        _aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("recorded_at must precede valid_until")


@dataclass(frozen=True, slots=True)
class SystemAuditScopeAuthorityFacts:
    """Immutable tenant/owner scope facts projected by an injected reader."""

    source_id: str
    source_version: str
    content_hash: str
    actor_id: str
    user_id: int
    tenant_id: str
    owner_id: str
    authority_state: str
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("actor_id", self.actor_id),
            ("tenant_id", self.tenant_id),
            ("owner_id", self.owner_id),
            ("authority_state", self.authority_state),
        ):
            _token(value, name)
        _digest(self.content_hash, "content_hash")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if self.authority_state not in {"active", "revoked"}:
            raise ValueError("authority_state must be active or revoked")
        _aware(self.recorded_at, "recorded_at")
        _aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("recorded_at must precede valid_until")


class SystemAuditActorAuthorityReader(Protocol):
    """Read one exact/current Account actor-authority source."""

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditActorAuthorityFacts | None:
        """Return the final exact head, or ``None`` without fallback."""


class SystemAuditScopeAuthorityReader(Protocol):
    """Read one exact/current immutable tenant/owner scope source."""

    def get_current(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> SystemAuditScopeAuthorityFacts | None:
        """Return the final exact head, or ``None`` without fallback."""


class ExactScopedSystemAuditAuthorityProvider(SystemAuditAuthorityProvider):
    """Compose Account actor and Research scope ledgers into audit authority.

    This provider is deliberately inert without a server-issued selector.  A
    selector mismatch, stale/terminal source, actor/user mismatch, or reader
    exception returns ``None``.  The caller then maps that result to the
    stable ``authority_unavailable`` reason and never touches the event
    repository.
    """

    __slots__ = ("_actor_reader", "_scope_reader", "_selector")

    def __init__(
        self,
        *,
        actor_reader: SystemAuditActorAuthorityReader,
        scope_reader: SystemAuditScopeAuthorityReader,
        selector: SystemAuditAuthorityBundleSelector | None,
    ) -> None:
        self._actor_reader = actor_reader
        self._scope_reader = scope_reader
        self._selector = selector

    def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
        """Return one exact scoped snapshot, or ``None`` on any uncertainty."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            return None
        selector = self._selector
        if selector is None:
            return None
        try:
            actor = self._actor_reader.get_current(
                source_id=selector.actor_source_id,
                source_version=selector.actor_source_version,
                expected_content_hash=selector.actor_content_hash,
                as_of=as_of,
            )
            scope = self._scope_reader.get_current(
                source_id=selector.scope_source_id,
                source_version=selector.scope_source_version,
                expected_content_hash=selector.scope_content_hash,
                as_of=as_of,
            )
            if not isinstance(actor, SystemAuditActorAuthorityFacts):
                return None
            if not isinstance(scope, SystemAuditScopeAuthorityFacts):
                return None
            if not _matches_actor(actor, selector) or not _matches_scope(scope, selector):
                return None
            if (
                actor.actor_id != scope.actor_id
                or actor.user_id != scope.user_id
                or actor.authority_state != "active"
                or scope.authority_state != "active"
                or not actor.is_authenticated
                or not actor.is_staff
                or actor.actor_id != f"django-user:{actor.user_id}"
                or actor.recorded_at > as_of
                or scope.recorded_at > as_of
                or actor.valid_until <= as_of
                or scope.valid_until <= as_of
            ):
                return None
            recorded_at = max(actor.recorded_at, scope.recorded_at)
            valid_until = min(actor.valid_until, scope.valid_until)
            if recorded_at >= valid_until:
                return None
            bundle_key = selector.canonical_key()
            return SystemAuditAuthoritySnapshot(
                source_id=f"audit-authority-bundle:{bundle_key}",
                source_version=f"v1-{bundle_key[:32]}",
                actor_id=actor.actor_id,
                user_id=actor.user_id,
                tenant_id=scope.tenant_id,
                owner_id=scope.owner_id,
                authority_content_hash=system_audit_authority_content_hash(
                    source_id=f"audit-authority-bundle:{bundle_key}",
                    source_version=f"v1-{bundle_key[:32]}",
                    actor_id=actor.actor_id,
                    user_id=actor.user_id,
                    tenant_id=scope.tenant_id,
                    owner_id=scope.owner_id,
                    is_authenticated=actor.is_authenticated,
                    is_staff=actor.is_staff,
                    role=actor.role,
                    authority_state="active",
                    recorded_at=recorded_at,
                    valid_until=valid_until,
                ),
                is_authenticated=actor.is_authenticated,
                is_staff=actor.is_staff,
                role=actor.role,
                authority_state="active",
                recorded_at=recorded_at,
                valid_until=valid_until,
            )
        except Exception:
            # Database/RBAC/provider errors are intentionally opaque here.
            return None


def _matches_actor(
    value: SystemAuditActorAuthorityFacts, selector: SystemAuditAuthorityBundleSelector
) -> bool:
    return (
        value.source_id,
        value.source_version,
        value.content_hash,
    ) == (
        selector.actor_source_id,
        selector.actor_source_version,
        selector.actor_content_hash,
    )


def _matches_scope(
    value: SystemAuditScopeAuthorityFacts, selector: SystemAuditAuthorityBundleSelector
) -> bool:
    return (
        value.source_id,
        value.source_version,
        value.content_hash,
    ) == (
        selector.scope_source_id,
        selector.scope_source_version,
        selector.scope_content_hash,
    )


__all__ = [
    "ExactScopedSystemAuditAuthorityProvider",
    "SystemAuditActorAuthorityFacts",
    "SystemAuditActorAuthorityReader",
    "SystemAuditAuthorityBundleSelector",
    "SystemAuditScopeAuthorityFacts",
    "SystemAuditScopeAuthorityReader",
]
