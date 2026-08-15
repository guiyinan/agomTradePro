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
_AUTHORITY_STATES = frozenset({"active", "revoked"})


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
    source_id: str,
    source_version: str,
    actor_id: str,
    user_id: int,
    tenant_id: str,
    owner_id: str,
    is_authenticated: bool,
    is_staff: bool,
    role: str,
    authority_state: str,
    recorded_at: datetime,
    valid_until: datetime,
) -> str:
    """Return the canonical digest for one provider-issued authority snapshot.

    The digest binds every non-secret fact that the composition boundary uses
    for staff/user and tenant/owner scope.  It is not an authentication
    provider and does not create authority; it only lets the boundary reject
    a snapshot whose scope fields were substituted after issuance.
    """

    for name, value in (
        ("source_id", source_id),
        ("source_version", source_version),
        ("actor_id", actor_id),
        ("tenant_id", tenant_id),
        ("owner_id", owner_id),
        ("role", role),
        ("authority_state", authority_state),
    ):
        _require_token(value, name)
    if authority_state not in _AUTHORITY_STATES:
        raise ValueError("authority_state must be active or revoked")
    _require_aware_datetime(recorded_at, "recorded_at")
    _require_aware_datetime(valid_until, "valid_until")
    if recorded_at >= valid_until:
        raise ValueError("recorded_at must be before valid_until")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    if not isinstance(is_authenticated, bool) or not isinstance(is_staff, bool):
        raise TypeError("authority flags must be bools")

    payload: Mapping[str, JSONValue] = {
        "source_id": source_id,
        "source_version": source_version,
        "actor_id": actor_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "is_authenticated": is_authenticated,
        "is_staff": is_staff,
        "role": role,
        "authority_state": authority_state,
        "recorded_at": recorded_at.isoformat(),
        "valid_until": valid_until.isoformat(),
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


def _require_aware_datetime(value: object, field: str) -> None:
    """Require a timezone-aware authority clock value."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CanonicalSystemAuditPublishReceipt:
    """Durable-sink receipt that proves exact event and delivery preservation.

    The delivery fields are deliberately optional at construction time so a
    malformed or legacy-shaped publisher result can cross the typed boundary
    and be rejected deterministically by :meth:`validate_for`.  A receipt is
    not deliverable evidence until all three fields are present and valid.
    """

    event_id: str
    event_version: str
    identity_hash: str
    content_hash: str
    stream_id: str
    sequence_no: int
    predecessor_hash: str | None
    idempotency_key: str
    canonical_payload: Mapping[str, JSONValue]
    sink_id: str | None = None
    delivery_id: str | None = None
    published_at: datetime | None = None

    @classmethod
    def from_event(
        cls,
        event: SystemAuditEvent,
        *,
        sink_id: str | None = None,
        delivery_id: str | None = None,
        published_at: datetime | None = None,
    ) -> "CanonicalSystemAuditPublishReceipt":
        """Build an exact receipt, optionally without delivery proof.

        Omitting the delivery arguments is useful for constructing a negative
        contract fixture.  Such a receipt must fail ``validate_for`` and can
        never be accepted by the outbox dispatcher.
        """

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
            sink_id=sink_id,
            delivery_id=delivery_id,
            published_at=published_at,
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
        if self.sink_id is not None and not isinstance(self.sink_id, str):
            raise TypeError("sink_id must be a string when provided")
        if self.delivery_id is not None and not isinstance(self.delivery_id, str):
            raise TypeError("delivery_id must be a string when provided")
        if self.published_at is not None:
            _require_aware_datetime(self.published_at, "published_at")

    def _validate_delivery_proof(self, event: SystemAuditEvent) -> None:
        """Require bounded sink/delivery identities and a post-event clock."""

        if self.sink_id is None or self.delivery_id is None or self.published_at is None:
            raise SystemAuditPublisherContractViolation(
                "publisher receipt did not include durable delivery proof"
            )
        try:
            _require_token(self.sink_id, "sink_id")
            _require_token(self.delivery_id, "delivery_id")
            _require_aware_datetime(self.published_at, "published_at")
        except (TypeError, ValueError) as exc:
            raise SystemAuditPublisherContractViolation(
                "publisher receipt contained invalid durable delivery proof"
            ) from exc
        if self.published_at < event.recorded_at:
            raise SystemAuditPublisherContractViolation(
                "publisher publication clock precedes the event clock"
            )

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
        self._validate_delivery_proof(event)
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

    source_id: str
    source_version: str
    actor_id: str
    user_id: int
    tenant_id: str
    owner_id: str
    authority_content_hash: str
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
            ("tenant_id", self.tenant_id),
            ("owner_id", self.owner_id),
            ("role", self.role),
            ("authority_state", self.authority_state),
        ):
            _require_token(value, name)
        if not isinstance(self.user_id, int) or isinstance(self.user_id, bool) or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        if not isinstance(self.is_authenticated, bool) or not isinstance(self.is_staff, bool):
            raise TypeError("authority flags must be bools")
        if self.authority_state not in _AUTHORITY_STATES:
            raise ValueError("authority_state must be active or revoked")
        _require_aware_datetime(self.recorded_at, "recorded_at")
        _require_aware_datetime(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("recorded_at must be before valid_until")
        _require_digest(self.authority_content_hash, "authority_content_hash")

    def validate_integrity(self) -> None:
        """Reject a provider snapshot whose scope facts do not match its hash."""

        expected = system_audit_authority_content_hash(
            source_id=self.source_id,
            source_version=self.source_version,
            actor_id=self.actor_id,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            owner_id=self.owner_id,
            is_authenticated=self.is_authenticated,
            is_staff=self.is_staff,
            role=self.role,
            authority_state=self.authority_state,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
        )
        if expected != self.authority_content_hash:
            raise ValueError("authority snapshot content hash mismatch")

    def validate_at(self, as_of: datetime) -> None:
        """Require this snapshot to be active and knowable at ``as_of``."""

        _require_aware_datetime(as_of, "authority cutoff")
        if self.authority_state != "active":
            raise ValueError("authority snapshot is not active")
        if not self.recorded_at <= as_of < self.valid_until:
            raise ValueError("authority snapshot is outside its validity window")

    @property
    def can_read(self) -> bool:
        """Return the minimum staff/user binding required by the query contract."""

        return (
            self.authority_state == "active"
            and self.is_authenticated
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
            snapshot.validate_at(as_of)
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
    return SystemAuditReaderContext._from_authority(
        authority_source_id=snapshot.source_id,
        authority_source_version=snapshot.source_version,
        actor_id=snapshot.actor_id,
        user_id=snapshot.user_id,
        tenant_id=snapshot.tenant_id,
        owner_id=snapshot.owner_id,
        authority_content_hash=snapshot.authority_content_hash,
        is_authenticated=snapshot.is_authenticated,
        is_staff=snapshot.is_staff,
        role=snapshot.role,
        authority_state=snapshot.authority_state,
        authority_recorded_at=snapshot.recorded_at,
        authority_valid_until=snapshot.valid_until,
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
