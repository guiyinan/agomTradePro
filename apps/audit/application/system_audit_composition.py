"""Fail-closed contracts for future system-audit composition.

This module deliberately contains no Django, Celery, generic event-bus, or
external-sink implementation.  It gives the eventual runtime composition a
typed boundary: a publisher must return an exact receipt for the immutable
event it accepted, and a query authority must come from an injected
authoritative provider rather than caller-supplied actor flags.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, cast

from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.audit.domain.system_audit_event import JSONValue, SystemAuditEvent

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_token(value: object, field: str) -> None:
    """Require one bounded, whitespace-free authority identity token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} must be a bounded canonical token")


class SystemAuditCompositionUnavailable(Exception):
    """A required publisher or authority provider is not wired."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class SystemAuditPublisherContractViolation(Exception):
    """A publisher did not preserve the canonical audit envelope exactly."""


def _canonical_bytes(payload: Mapping[str, JSONValue]) -> bytes:
    """Serialize a JSON payload with strict, deterministic scalar semantics."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def system_audit_authority_content_hash(
    *,
    actor_id: str,
    user_id: int,
    tenant_id: str,
    owner_id: str,
    is_authenticated: bool,
    is_staff: bool,
    role: str,
) -> str:
    """Return the canonical digest for one provider-issued authority snapshot.

    The digest binds every non-secret fact that the composition boundary uses
    for staff/user and tenant/owner scope.  It is not an authentication
    provider and does not create authority; it only lets the boundary reject
    a snapshot whose scope fields were substituted after issuance.
    """

    for name, value in (
        ("actor_id", actor_id),
        ("tenant_id", tenant_id),
        ("owner_id", owner_id),
        ("role", role),
    ):
        _require_token(value, name)

    payload: Mapping[str, JSONValue] = {
        "actor_id": actor_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "is_authenticated": is_authenticated,
        "is_staff": is_staff,
        "role": role,
    }
    return hashlib.sha256(
        b"audit.system-audit-authority.v1\0" + _canonical_bytes(payload)
    ).hexdigest()


def _exact_payload_equal(left: object, right: object) -> bool:
    """Compare canonical payload trees without JSON coercion.

    ``json.dumps`` deliberately normalizes several Python representations (for
    example, tuples to arrays and boolean/integer keys in some contexts).  A
    publisher receipt must preserve the event's in-memory canonical tree, so
    container and scalar types are checked before values are compared.  Mapping
    key order remains canonicalized by ``sort_keys=True``; key types, sequence
    order, and nested container types do not.
    """

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if type(left) is not dict:
            return False
        left_dict = cast(dict[object, object], left)
        right_dict = cast(dict[object, object], right)
        if not all(type(key) is str for key in left_dict):
            return False
        if not all(type(key) is str for key in right_dict):
            return False
        if left_dict.keys() != right_dict.keys():
            return False
        return all(_exact_payload_equal(left_dict[key], right_dict[key]) for key in left_dict)
    if isinstance(left, list) or isinstance(left, tuple):
        if type(left) not in (list, tuple):
            return False
        left_sequence = cast(list[object] | tuple[object, ...], left)
        right_sequence = cast(list[object] | tuple[object, ...], right)
        return len(left_sequence) == len(right_sequence) and all(
            _exact_payload_equal(left_item, right_item)
            for left_item, right_item in zip(left_sequence, right_sequence)
        )
    if left is None or isinstance(left, (str, bool, int, float)):
        return left == right
    return False


def _require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")


@dataclass(frozen=True, slots=True)
class CanonicalSystemAuditPublishReceipt:
    """Durable-sink receipt that proves exact event preservation."""

    event_id: str
    event_version: str
    identity_hash: str
    content_hash: str
    stream_id: str
    sequence_no: int
    predecessor_hash: str | None
    idempotency_key: str
    canonical_payload: Mapping[str, JSONValue]

    @classmethod
    def from_event(cls, event: SystemAuditEvent) -> "CanonicalSystemAuditPublishReceipt":
        """Build the test/reference receipt for an unchanged event."""

        return cls(
            event_id=event.event_id,
            event_version=event.event_version,
            identity_hash=event.identity_hash,
            content_hash=event.content_hash,
            stream_id=event.stream_id,
            sequence_no=event.sequence_no,
            predecessor_hash=event.predecessor_hash,
            idempotency_key=event.idempotency_key,
            canonical_payload=event.to_payload(),
        )

    def __post_init__(self) -> None:
        for name, value in (
            ("event_id", self.event_id),
            ("event_version", self.event_version),
            ("stream_id", self.stream_id),
            ("idempotency_key", self.idempotency_key),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        _require_digest(self.identity_hash, "identity_hash")
        _require_digest(self.content_hash, "content_hash")
        if self.predecessor_hash is not None:
            _require_digest(self.predecessor_hash, "predecessor_hash")
        if (
            not isinstance(self.sequence_no, int)
            or isinstance(self.sequence_no, bool)
            or self.sequence_no < 1
        ):
            raise ValueError("sequence_no must be a positive integer")
        if not isinstance(self.canonical_payload, Mapping):
            raise TypeError("canonical_payload must be a mapping")

    def validate_for(self, event: SystemAuditEvent) -> None:
        """Reject any identity, chain, hash, or payload substitution."""

        if not isinstance(event, SystemAuditEvent):
            raise SystemAuditPublisherContractViolation("publisher event type was substituted")
        expected = self.from_event(event)
        try:
            receipt_bytes = _canonical_bytes(self.canonical_payload)
            expected_bytes = _canonical_bytes(expected.canonical_payload)
            payload_matches = (
                _exact_payload_equal(self.canonical_payload, expected.canonical_payload)
                and receipt_bytes == expected_bytes
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise SystemAuditPublisherContractViolation(
                "publisher receipt contained a non-canonical payload"
            ) from exc
        if (
            self.event_id != expected.event_id
            or self.event_version != expected.event_version
            or self.identity_hash != expected.identity_hash
            or self.content_hash != expected.content_hash
            or self.stream_id != expected.stream_id
            or self.sequence_no != expected.sequence_no
            or self.predecessor_hash != expected.predecessor_hash
            or self.idempotency_key != expected.idempotency_key
            or not payload_matches
        ):
            raise SystemAuditPublisherContractViolation(
                "publisher receipt did not preserve the canonical event"
            )
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as exc:
            raise SystemAuditPublisherContractViolation(
                "publisher received an invalid canonical event"
            ) from exc


class CanonicalSystemAuditPublisher(Protocol):
    """Future durable publisher port; generic or memory sinks do not qualify."""

    def publish(self, event: SystemAuditEvent) -> CanonicalSystemAuditPublishReceipt:
        """Persist exactly one event and return an exact preservation receipt."""


@dataclass(frozen=True, slots=True)
class SystemAuditAuthoritySnapshot:
    """Authoritative, request-independent facts used for a scoped read."""

    actor_id: str
    user_id: int
    tenant_id: str
    owner_id: str
    authority_content_hash: str
    is_authenticated: bool
    is_staff: bool
    role: str

    def __post_init__(self) -> None:
        for name, value in (
            ("actor_id", self.actor_id),
            ("tenant_id", self.tenant_id),
            ("owner_id", self.owner_id),
            ("role", self.role),
        ):
            _require_token(value, name)
        if not isinstance(self.user_id, int) or isinstance(self.user_id, bool) or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if not isinstance(self.is_authenticated, bool) or not isinstance(self.is_staff, bool):
            raise TypeError("authority flags must be bools")
        _require_digest(self.authority_content_hash, "authority_content_hash")

    def validate_integrity(self) -> None:
        """Reject a provider snapshot whose scope facts do not match its hash."""

        expected = system_audit_authority_content_hash(
            actor_id=self.actor_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            owner_id=self.owner_id,
            is_authenticated=self.is_authenticated,
            is_staff=self.is_staff,
            role=self.role,
        )
        if expected != self.authority_content_hash:
            raise ValueError("authority snapshot content hash mismatch")

    @property
    def can_read(self) -> bool:
        """Return the minimum staff/user binding required by the query contract."""

        return (
            self.is_authenticated
            and self.is_staff
            and self.actor_id == f"django-user:{self.user_id}"
        )


class SystemAuditAuthorityProvider(Protocol):
    """Injected source of current, immutable authority facts."""

    def get_current(self, *, as_of: datetime) -> SystemAuditAuthoritySnapshot | None:
        """Return authoritative facts at ``as_of`` or ``None`` when unavailable."""


def get_system_audit_reader_context(
    provider: SystemAuditAuthorityProvider | None,
    *,
    as_of: datetime,
) -> SystemAuditReaderContext:
    """Project provider-backed authority into the existing query context.

    This is intentionally not wired to a request or route.  A missing provider,
    stale/unscoped snapshot, or non-staff snapshot blocks before repository
    access; callers cannot manufacture authority through this function.
    """

    if provider is None:
        raise SystemAuditCompositionUnavailable(
            "system audit authority provider is not wired",
            reason_code="authority_not_wired",
        )
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise SystemAuditCompositionUnavailable(
            "system audit authority cutoff must be timezone-aware",
            reason_code="authority_cutoff_invalid",
        )
    try:
        snapshot = provider.get_current(as_of=as_of)
        if isinstance(snapshot, SystemAuditAuthoritySnapshot):
            snapshot.validate_integrity()
        is_eligible = isinstance(snapshot, SystemAuditAuthoritySnapshot) and snapshot.can_read
    except Exception:
        # Do not leak provider/database/RBAC details through this boundary.
        # A failed authority lookup is indistinguishable from unavailable or
        # unscoped authority until a real composition root supplies policy.
        is_eligible = False
        snapshot = None
    if not is_eligible or snapshot is None:
        raise SystemAuditCompositionUnavailable(
            "system audit authority is unavailable or not scoped",
            reason_code="authority_unavailable",
        )
    return SystemAuditReaderContext(
        actor_id=snapshot.actor_id,
        user_id=snapshot.user_id,
        is_authenticated=snapshot.is_authenticated,
        is_staff=snapshot.is_staff,
        role=snapshot.role,
    )


__all__ = [
    "CanonicalSystemAuditPublishReceipt",
    "CanonicalSystemAuditPublisher",
    "SystemAuditAuthorityProvider",
    "SystemAuditAuthoritySnapshot",
    "SystemAuditCompositionUnavailable",
    "SystemAuditPublisherContractViolation",
    "system_audit_authority_content_hash",
    "get_system_audit_reader_context",
]
