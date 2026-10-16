"""Typed, content-bound early retirement for immutable A-share rule versions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

_REASON_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_HASH_DOMAIN = b"risk-center.ashare-execution-rule-retirement.request.v1\0"


class AShareExecutionRuleRetirementValidationError(ValueError):
    """A retirement value or transition violates the typed domain contract."""


class AShareExecutionRuleRetirementConflict(ValueError):
    """A retirement intent does not match the exact rule or persisted winner."""


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementIntent:
    """One exact, idempotent retirement request for a canonical rule identity."""

    security_id: str
    rule_id: str
    rule_version: str
    expected_content_hash: str
    request_id: UUID
    effective_at: datetime
    reason_code: str

    def __post_init__(self) -> None:
        """Validate the exact rule identity, request UUID, effective time, and reason."""

        _require_token(self.security_id, "security_id", maximum=192)
        _require_token(self.rule_id, "rule_id", maximum=192)
        _require_token(self.rule_version, "rule_version", maximum=192)
        _require_digest(self.expected_content_hash, "expected_content_hash")
        if type(self.request_id) is not UUID:
            raise AShareExecutionRuleRetirementValidationError("request_id must be a UUID")
        _require_aware(self.effective_at, "effective_at")
        if (
            type(self.reason_code) is not str
            or len(self.reason_code) > 128
            or _REASON_RE.fullmatch(self.reason_code) is None
        ):
            raise AShareExecutionRuleRetirementValidationError(
                "reason_code must be a canonical lowercase code"
            )


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementAuthorization:
    """Server-issued actor and explicit Audit scope bound to this operation."""

    actor_type: str
    actor_id: str
    scope_tenant_id: str
    scope_owner_id: str

    def __post_init__(self) -> None:
        """Require the trusted actor and explicit tenant and owner scope."""

        _require_token(self.actor_type, "actor_type", maximum=64)
        _require_token(self.actor_id, "actor_id", maximum=256)
        _require_token(self.scope_tenant_id, "scope_tenant_id", maximum=192)
        _require_token(self.scope_owner_id, "scope_owner_id", maximum=192)


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementEvidence:
    """One-time retirement columns; all six values are present or all absent."""

    retirement_effective_at: datetime | None = None
    retirement_recorded_at: datetime | None = None
    retirement_request_id: UUID | None = None
    retirement_actor_type: str | None = None
    retirement_actor_id: str | None = None
    retirement_request_hash: str | None = None

    def __post_init__(self) -> None:
        """Require either six absent values or complete time-consistent retirement evidence."""

        values = (
            self.retirement_effective_at,
            self.retirement_recorded_at,
            self.retirement_request_id,
            self.retirement_actor_type,
            self.retirement_actor_id,
            self.retirement_request_hash,
        )
        if all(value is None for value in values):
            return
        if any(value is None for value in values):
            raise AShareExecutionRuleRetirementValidationError(
                "retirement evidence must be entirely empty or complete"
            )
        assert self.retirement_effective_at is not None
        assert self.retirement_recorded_at is not None
        assert self.retirement_request_id is not None
        assert self.retirement_actor_type is not None
        assert self.retirement_actor_id is not None
        assert self.retirement_request_hash is not None
        _require_aware(self.retirement_effective_at, "retirement_effective_at")
        _require_aware(self.retirement_recorded_at, "retirement_recorded_at")
        if self.retirement_effective_at < self.retirement_recorded_at:
            raise AShareExecutionRuleRetirementValidationError(
                "retirement_effective_at cannot precede retirement_recorded_at"
            )
        if type(self.retirement_request_id) is not UUID:
            raise AShareExecutionRuleRetirementValidationError(
                "retirement_request_id must be a UUID"
            )
        _require_token(self.retirement_actor_type, "retirement_actor_type", maximum=64)
        _require_token(self.retirement_actor_id, "retirement_actor_id", maximum=256)
        _require_digest(self.retirement_request_hash, "retirement_request_hash")

    @property
    def is_empty(self) -> bool:
        """Return whether this value represents an unretired rule."""

        return self.retirement_request_id is None


@dataclass(frozen=True, slots=True)
class AShareExecutionRuleRetirementTarget:
    """Exact immutable rule identity and validity window targeted for retirement."""

    security_id: str
    rule_id: str
    rule_version: str
    content_hash: str
    rule_recorded_at: datetime
    effective_from: datetime
    valid_until: datetime
    retirement: AShareExecutionRuleRetirementEvidence

    def __post_init__(self) -> None:
        """Bind retirement evidence to the immutable rule identity and validity window."""

        _require_token(self.security_id, "security_id", maximum=192)
        _require_token(self.rule_id, "rule_id", maximum=192)
        _require_token(self.rule_version, "rule_version", maximum=192)
        _require_digest(self.content_hash, "content_hash")
        _require_aware(self.rule_recorded_at, "rule_recorded_at")
        _require_aware(self.effective_from, "effective_from")
        _require_aware(self.valid_until, "valid_until")
        if self.effective_from >= self.valid_until:
            raise AShareExecutionRuleRetirementValidationError(
                "rule effective window must be nonempty"
            )
        if type(self.retirement) is not AShareExecutionRuleRetirementEvidence:
            raise AShareExecutionRuleRetirementValidationError(
                "retirement must be typed retirement evidence"
            )
        AShareExecutionRuleRetirementEvidence.__post_init__(self.retirement)
        if not self.retirement.is_empty:
            assert self.retirement.retirement_effective_at is not None
            assert self.retirement.retirement_recorded_at is not None
            if self.retirement.retirement_recorded_at < self.rule_recorded_at:
                raise AShareExecutionRuleRetirementValidationError(
                    "retirement recorded time cannot precede original rule knowledge time"
                )
            if not (
                self.effective_from <= self.retirement.retirement_effective_at < self.valid_until
            ):
                raise AShareExecutionRuleRetirementValidationError(
                    "stored retirement must fall inside the original rule window"
                )


def build_retirement_evidence(
    *,
    target: AShareExecutionRuleRetirementTarget,
    intent: AShareExecutionRuleRetirementIntent,
    authorization: AShareExecutionRuleRetirementAuthorization,
    recorded_at: datetime,
) -> AShareExecutionRuleRetirementEvidence:
    """Validate a first retirement and return its immutable evidence fields."""

    _validate_exact_types(target=target, intent=intent, authorization=authorization)
    _validate_target_intent(target=target, intent=intent)
    _require_aware(recorded_at, "recorded_at")
    if not target.retirement.is_empty:
        raise AShareExecutionRuleRetirementConflict("rule already has a retirement winner")
    if intent.effective_at < recorded_at:
        raise AShareExecutionRuleRetirementValidationError(
            "retirement cannot be effective before it is recorded"
        )
    if recorded_at < target.rule_recorded_at:
        raise AShareExecutionRuleRetirementValidationError(
            "retirement recorded time cannot precede original rule knowledge time"
        )
    if not target.effective_from <= intent.effective_at < target.valid_until:
        raise AShareExecutionRuleRetirementValidationError(
            "retirement effective time must fall inside the original rule window"
        )
    request_hash = retirement_request_hash(intent=intent, authorization=authorization)
    return AShareExecutionRuleRetirementEvidence(
        retirement_effective_at=intent.effective_at,
        retirement_recorded_at=recorded_at,
        retirement_request_id=intent.request_id,
        retirement_actor_type=authorization.actor_type,
        retirement_actor_id=authorization.actor_id,
        retirement_request_hash=request_hash,
    )


def verify_retirement_replay(
    *,
    target: AShareExecutionRuleRetirementTarget,
    intent: AShareExecutionRuleRetirementIntent,
    authorization: AShareExecutionRuleRetirementAuthorization,
) -> AShareExecutionRuleRetirementEvidence:
    """Require the supplied request and trusted identity to match the stored winner."""

    _validate_exact_types(target=target, intent=intent, authorization=authorization)
    _validate_target_intent(target=target, intent=intent)
    evidence = target.retirement
    if evidence.is_empty:
        raise AShareExecutionRuleRetirementConflict("rule has no retirement winner to replay")
    if (
        evidence.retirement_request_id != intent.request_id
        or evidence.retirement_effective_at != intent.effective_at
        or evidence.retirement_actor_type != authorization.actor_type
        or evidence.retirement_actor_id != authorization.actor_id
        or evidence.retirement_request_hash
        != retirement_request_hash(intent=intent, authorization=authorization)
    ):
        raise AShareExecutionRuleRetirementConflict(
            "retirement request or authorized identity differs from its first winner"
        )
    assert evidence.retirement_recorded_at is not None
    if not target.effective_from <= evidence.retirement_effective_at < target.valid_until:
        raise AShareExecutionRuleRetirementValidationError(
            "stored retirement is outside the original rule window"
        )
    if evidence.retirement_effective_at < evidence.retirement_recorded_at:
        raise AShareExecutionRuleRetirementValidationError(
            "stored retirement predates its recorded time"
        )
    if evidence.retirement_recorded_at < target.rule_recorded_at:
        raise AShareExecutionRuleRetirementValidationError(
            "stored retirement predates the original rule knowledge time"
        )
    return evidence


def retirement_request_hash(
    *,
    intent: AShareExecutionRuleRetirementIntent,
    authorization: AShareExecutionRuleRetirementAuthorization,
) -> str:
    """Return a deterministic request digest bound to actor and explicit scope."""

    if type(intent) is not AShareExecutionRuleRetirementIntent:
        raise AShareExecutionRuleRetirementValidationError("intent has an invalid type")
    if type(authorization) is not AShareExecutionRuleRetirementAuthorization:
        raise AShareExecutionRuleRetirementValidationError("authorization has an invalid type")
    AShareExecutionRuleRetirementIntent.__post_init__(intent)
    AShareExecutionRuleRetirementAuthorization.__post_init__(authorization)
    payload = {
        "security_id": intent.security_id,
        "rule_id": intent.rule_id,
        "rule_version": intent.rule_version,
        "expected_content_hash": intent.expected_content_hash,
        "request_id": str(intent.request_id),
        "effective_at": _utc_text(intent.effective_at),
        "reason_code": intent.reason_code,
        "actor_type": authorization.actor_type,
        "actor_id": authorization.actor_id,
        "scope_tenant_id": authorization.scope_tenant_id,
        "scope_owner_id": authorization.scope_owner_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(_REQUEST_HASH_DOMAIN + canonical).hexdigest()


def _validate_exact_types(
    *,
    target: AShareExecutionRuleRetirementTarget,
    intent: AShareExecutionRuleRetirementIntent,
    authorization: AShareExecutionRuleRetirementAuthorization,
) -> None:
    if type(target) is not AShareExecutionRuleRetirementTarget:
        raise AShareExecutionRuleRetirementValidationError("target has an invalid type")
    if type(intent) is not AShareExecutionRuleRetirementIntent:
        raise AShareExecutionRuleRetirementValidationError("intent has an invalid type")
    if type(authorization) is not AShareExecutionRuleRetirementAuthorization:
        raise AShareExecutionRuleRetirementValidationError("authorization has an invalid type")
    AShareExecutionRuleRetirementTarget.__post_init__(target)
    AShareExecutionRuleRetirementIntent.__post_init__(intent)
    AShareExecutionRuleRetirementAuthorization.__post_init__(authorization)


def _validate_target_intent(
    *,
    target: AShareExecutionRuleRetirementTarget,
    intent: AShareExecutionRuleRetirementIntent,
) -> None:
    if (
        target.security_id != intent.security_id
        or target.rule_id != intent.rule_id
        or target.rule_version != intent.rule_version
        or target.content_hash != intent.expected_content_hash
    ):
        raise AShareExecutionRuleRetirementConflict(
            "retirement request does not match the exact immutable rule winner"
        )


def _require_token(value: str, field: str, *, maximum: int) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise AShareExecutionRuleRetirementValidationError(
            f"{field} must be a bounded canonical token"
        )


def _require_digest(value: str, field: str) -> None:
    if type(value) is not str or _HASH_RE.fullmatch(value) is None:
        raise AShareExecutionRuleRetirementValidationError(
            f"{field} must be a lowercase SHA-256 digest"
        )


def _require_aware(value: datetime, field: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AShareExecutionRuleRetirementValidationError(f"{field} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "AShareExecutionRuleRetirementAuthorization",
    "AShareExecutionRuleRetirementConflict",
    "AShareExecutionRuleRetirementEvidence",
    "AShareExecutionRuleRetirementIntent",
    "AShareExecutionRuleRetirementTarget",
    "AShareExecutionRuleRetirementValidationError",
    "build_retirement_evidence",
    "retirement_request_hash",
    "verify_retirement_replay",
]
