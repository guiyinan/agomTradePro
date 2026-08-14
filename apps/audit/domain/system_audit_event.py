"""Pure canonical contract for the system audit event envelope.

This module deliberately contains no Django or runtime integration.  It is the
owner-neutral value object that a future audit repository/outbox must persist.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final, Mapping, Sequence, TypeAlias


class AuditCategory(StrEnum):
    """Registered top-level event categories."""

    SYSTEM_OPERATION = "system.operation"
    SYSTEM_SECURITY = "system.security"
    SYSTEM_CONFIGURATION = "system.configuration"
    SYSTEM_TASK = "system.task"
    DATA_RELIABILITY = "data.reliability"
    DECISION_GOVERNANCE = "decision.governance"
    EXECUTION_CONTROL = "execution.control"


class AuditOutcome(StrEnum):
    """Canonical event outcomes from the governance registry."""

    STARTED = "started"
    SUCCESS = "success"
    NOOP = "noop"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    DETECTED = "detected"
    RECOVERED = "recovered"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"


class AuditSeverity(StrEnum):
    """Canonical event severities."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditWritePolicy(StrEnum):
    """Persistence policy selected by the registered event contract."""

    REQUIRED = "required"
    TRANSACTIONAL_OUTBOX = "transactional_outbox"
    BEST_EFFORT = "best_effort"


JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | Mapping[str, "JSONValue"] | Sequence["JSONValue"]

_EVENT_TYPE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z0-9_-]+)+$")
_REASON_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:token|secret|password|passwd|credential|cookie|csrf|authorization|api[_-]?key|session[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


def _require_text(value: str, field: str, *, max_length: int = 256) -> None:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ValueError(f"{field} must be a non-empty bounded string")


def _require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase sha256 digest")


def _require_aware(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_json(value: JSONValue, path: str = "detail") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} keys must be non-empty strings")
            if _SENSITIVE_KEY_RE.search(key):
                raise ValueError(f"{path} contains a sensitive key")
            _validate_json(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_json(child, f"{path}[{index}]")
        return
    raise ValueError(f"{path} contains an unsupported JSON value")


def _json_value(value: JSONValue) -> JSONValue:
    if isinstance(value, Mapping):
        return {key: _json_value(child) for key, child in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(child) for child in value]
    return value


def _canonical_bytes(payload: Mapping[str, JSONValue]) -> bytes:
    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(domain: str, payload: Mapping[str, JSONValue]) -> str:
    return hashlib.sha256(domain.encode("ascii") + b"\0" + _canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditActorRef:
    """Stable, non-secret actor reference."""

    actor_type: str
    actor_id: str
    actor_display: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.actor_type, "actor_type", max_length=64)
        _require_text(self.actor_id, "actor_id", max_length=256)
        if self.actor_display is not None:
            _require_text(self.actor_display, "actor_display", max_length=256)

    def to_payload(self) -> Mapping[str, JSONValue]:
        return {
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor_display": self.actor_display,
        }


@dataclass(frozen=True, slots=True)
class AuditResourceRef:
    """Typed business resource reference."""

    resource_type: str
    resource_id: str
    resource_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.resource_type, "resource_type", max_length=128)
        _require_text(self.resource_id, "resource_id", max_length=256)
        if self.resource_version is not None:
            _require_text(self.resource_version, "resource_version", max_length=128)

    def to_payload(self) -> Mapping[str, JSONValue]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_version": self.resource_version,
        }


@dataclass(frozen=True, slots=True)
class AuditEvidenceRef:
    """Exact owner/type/version/hash pointer to professional evidence."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_text(self.owner, "evidence.owner", max_length=64)
        _require_text(self.artifact_type, "evidence.artifact_type", max_length=128)
        _require_text(self.artifact_id, "evidence.artifact_id", max_length=256)
        _require_text(self.artifact_version, "evidence.artifact_version", max_length=128)
        _require_digest(self.content_hash, "evidence.content_hash")

    def to_payload(self) -> Mapping[str, JSONValue]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class AuditCorrelations:
    """Bounded correlation keys; no free-form query or URL fields."""

    trace_id: str | None = None
    request_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    ingested_run_id: str | None = None
    dataset_key: str | None = None
    provider_key: str | None = None
    capability: str | None = None
    publication_id: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        for name, value in self.to_payload().items():
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"correlations.{name} must be a string")
                _require_text(value, f"correlations.{name}", max_length=256)

    def to_payload(self) -> Mapping[str, JSONValue]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "ingested_run_id": self.ingested_run_id,
            "dataset_key": self.dataset_key,
            "provider_key": self.provider_key,
            "capability": self.capability,
            "publication_id": self.publication_id,
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True, slots=True)
class SystemAuditEvent:
    """Canonical immutable event envelope.

    ``create`` is the only supported constructor for new events.  Persisted
    bytes are restored by the infrastructure codec, which revalidates this
    value object through its strict constructor.
    """

    event_id: str
    event_version: str
    schema_version: str
    category: AuditCategory
    event_type: str
    owner: str
    write_policy: AuditWritePolicy
    outcome: AuditOutcome
    severity: AuditSeverity
    reason_codes: tuple[str, ...]
    occurred_at: datetime
    recorded_at: datetime
    observed_at: datetime | None
    actor: AuditActorRef
    source_app: str
    source_component: str
    source_surface: str
    correlations: AuditCorrelations
    resource: AuditResourceRef | None
    dataset_key: str | None
    provider_key: str | None
    capability: str | None
    publication_id: str | None
    evidence_refs: tuple[AuditEvidenceRef, ...]
    detail_schema: str
    detail: Mapping[str, JSONValue]
    stream_id: str
    sequence_no: int
    predecessor_hash: str | None
    idempotency_key: str
    identity_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        event_version: str,
        schema_version: str,
        category: AuditCategory,
        event_type: str,
        owner: str,
        write_policy: AuditWritePolicy,
        outcome: AuditOutcome,
        severity: AuditSeverity,
        reason_codes: Sequence[str],
        occurred_at: datetime,
        recorded_at: datetime,
        observed_at: datetime | None,
        actor: AuditActorRef,
        source_app: str,
        source_component: str,
        source_surface: str,
        correlations: AuditCorrelations,
        resource: AuditResourceRef | None,
        dataset_key: str | None,
        provider_key: str | None,
        capability: str | None,
        publication_id: str | None,
        evidence_refs: Sequence[AuditEvidenceRef],
        detail_schema: str,
        detail: Mapping[str, JSONValue],
        stream_id: str,
        sequence_no: int,
        predecessor_hash: str | None,
        idempotency_key: str,
    ) -> "SystemAuditEvent":
        normalized_reasons = tuple(reason_codes)
        normalized_refs = tuple(evidence_refs)
        provisional = cls(
            event_id=event_id,
            event_version=event_version,
            schema_version=schema_version,
            category=category,
            event_type=event_type,
            owner=owner,
            write_policy=write_policy,
            outcome=outcome,
            severity=severity,
            reason_codes=normalized_reasons,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            observed_at=observed_at,
            actor=actor,
            source_app=source_app,
            source_component=source_component,
            source_surface=source_surface,
            correlations=correlations,
            resource=resource,
            dataset_key=dataset_key,
            provider_key=provider_key,
            capability=capability,
            publication_id=publication_id,
            evidence_refs=normalized_refs,
            detail_schema=detail_schema,
            detail=detail,
            stream_id=stream_id,
            sequence_no=sequence_no,
            predecessor_hash=predecessor_hash,
            idempotency_key=idempotency_key,
            identity_hash="0" * 64,
            content_hash="0" * 64,
        )
        payload = provisional._canonical_payload()
        identity_hash = _digest(
            "account.system-audit-event.identity.v1", provisional._identity_payload()
        )
        content_hash = _digest("account.system-audit-event.content.v1", payload)
        return replace(provisional, identity_hash=identity_hash, content_hash=content_hash)

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id", max_length=128)
        _require_text(self.event_version, "event_version", max_length=64)
        _require_text(self.schema_version, "schema_version", max_length=64)
        _require_text(self.owner, "owner", max_length=64)
        _require_text(self.event_type, "event_type", max_length=128)
        if _EVENT_TYPE_RE.fullmatch(self.event_type) is None:
            raise ValueError("event_type is not canonical")
        _require_text(self.source_app, "source_app", max_length=128)
        _require_text(self.source_component, "source_component", max_length=128)
        _require_text(self.source_surface, "source_surface", max_length=64)
        _require_text(self.detail_schema, "detail_schema", max_length=128)
        _require_text(self.stream_id, "stream_id", max_length=256)
        _require_text(self.idempotency_key, "idempotency_key", max_length=256)
        if not isinstance(self.category, AuditCategory) or not isinstance(
            self.outcome, AuditOutcome
        ):
            raise ValueError("category/outcome must use registered enums")
        if not isinstance(self.severity, AuditSeverity) or not isinstance(
            self.write_policy, AuditWritePolicy
        ):
            raise ValueError("severity/write_policy must use registered enums")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.observed_at is not None:
            _require_aware(self.observed_at, "observed_at")
            if self.observed_at > self.recorded_at:
                raise ValueError("observed_at cannot be after recorded_at")
        if not self.reason_codes or any(
            _REASON_RE.fullmatch(code) is None for code in self.reason_codes
        ):
            raise ValueError("reason_codes must be non-empty canonical codes")
        if (
            not isinstance(self.sequence_no, int)
            or isinstance(self.sequence_no, bool)
            or self.sequence_no < 1
        ):
            raise ValueError("sequence_no must be a positive integer")
        if self.sequence_no == 1 and self.predecessor_hash is not None:
            raise ValueError("root event cannot have predecessor_hash")
        if self.sequence_no > 1:
            if self.predecessor_hash is None:
                raise ValueError("successor event requires predecessor_hash")
            _require_digest(self.predecessor_hash, "predecessor_hash")
        for name, value in (
            ("dataset_key", self.dataset_key),
            ("provider_key", self.provider_key),
            ("capability", self.capability),
            ("publication_id", self.publication_id),
        ):
            if value is not None:
                _require_text(value, name, max_length=256)
        _validate_json(self.detail)
        _require_digest(self.identity_hash, "identity_hash")
        _require_digest(self.content_hash, "content_hash")

    def _identity_payload(self) -> Mapping[str, JSONValue]:
        return {
            "event_id": self.event_id,
            "event_version": self.event_version,
            "schema_version": self.schema_version,
            "category": self.category.value,
            "event_type": self.event_type,
            "owner": self.owner,
        }

    def _canonical_payload(self) -> Mapping[str, JSONValue]:
        return {
            **self._identity_payload(),
            "write_policy": self.write_policy.value,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "reason_codes": list(self.reason_codes),
            "occurred_at": _utc_text(self.occurred_at),
            "recorded_at": _utc_text(self.recorded_at),
            "observed_at": _utc_text(self.observed_at) if self.observed_at is not None else None,
            "actor": self.actor.to_payload(),
            "source_app": self.source_app,
            "source_component": self.source_component,
            "source_surface": self.source_surface,
            "correlations": self.correlations.to_payload(),
            "resource": self.resource.to_payload() if self.resource is not None else None,
            "dataset_key": self.dataset_key,
            "provider_key": self.provider_key,
            "capability": self.capability,
            "publication_id": self.publication_id,
            "evidence_refs": [ref.to_payload() for ref in self.evidence_refs],
            "detail_schema": self.detail_schema,
            "detail": self.detail,
            "stream_id": self.stream_id,
            "sequence_no": self.sequence_no,
            "predecessor_hash": self.predecessor_hash,
            "idempotency_key": self.idempotency_key,
        }

    def to_payload(self) -> Mapping[str, JSONValue]:
        """Return a complete canonical payload including both hashes."""

        return {
            **self._canonical_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }

    def validate_hashes(self) -> None:
        """Recompute and verify identity/content hashes."""

        identity = _digest("account.system-audit-event.identity.v1", self._identity_payload())
        content = _digest("account.system-audit-event.content.v1", self._canonical_payload())
        if identity != self.identity_hash or content != self.content_hash:
            raise ValueError("audit event hash mismatch")
