"""Pure contracts for preview-first stress-scenario write governance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum


class ScenarioGovernanceOperation(str, Enum):
    """Stable high-risk write operations governed by Risk Center."""

    PROPOSE = "propose"
    ACTIVATE = "activate"
    ROLLBACK = "rollback"
    RETIRE = "retire"


class ScenarioGovernanceActorKind(str, Enum):
    """Trusted server-side actor classifications."""

    HUMAN = "human"
    AI = "ai"
    SERVICE = "service"


class ScenarioGovernanceStatus(str, Enum):
    """Stable success states returned by every governance use case."""

    CONFIRMATION_REQUIRED = "confirmation_required"
    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    ROLLED_BACK = "rolled_back"
    RETIRED = "retired"


class ScenarioGovernanceErrorCode(str, Enum):
    """Stable machine-readable failure codes for API, SDK, and MCP transports."""

    INVALID_REQUEST = "scenario_governance_invalid_request"
    PERMISSION_DENIED = "scenario_governance_permission_denied"
    TARGET_NOT_FOUND = "scenario_governance_target_not_found"
    TARGET_IN_USE = "scenario_governance_target_in_use"
    PREVIEW_NOT_FOUND = "scenario_governance_preview_not_found"
    PREVIEW_EXPIRED = "scenario_governance_preview_expired"
    PREVIEW_ALREADY_USED = "scenario_governance_preview_already_used"
    PREVIEW_BINDING_MISMATCH = "scenario_governance_preview_binding_mismatch"
    IDEMPOTENCY_CONFLICT = "scenario_governance_idempotency_conflict"
    IDEMPOTENCY_IN_PROGRESS = "scenario_governance_idempotency_in_progress"
    OPTIMISTIC_LOCK_CONFLICT = "scenario_governance_optimistic_lock_conflict"
    PROPOSAL_NOT_FOUND = "scenario_governance_proposal_not_found"
    PROPOSAL_NOT_APPROVED = "scenario_governance_proposal_not_approved"
    SELF_APPROVAL_FORBIDDEN = "scenario_governance_self_approval_forbidden"
    AUDIT_WRITE_FAILED = "scenario_governance_audit_write_failed"
    INVALID_STATE = "scenario_governance_invalid_state"


@dataclass(frozen=True)
class ScenarioGovernanceActor:
    """Server-authenticated actor identity used for durable write binding."""

    actor_id: str
    kind: ScenarioGovernanceActorKind
    is_staff: bool
    user_id: int | None = None
    roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Normalize identity metadata and reject untrusted human shapes."""

        actor_id = self.actor_id.strip()
        if not actor_id or len(actor_id) > 150:
            raise ValueError("actor_id must contain at most 150 non-blank characters")
        if self.user_id is not None and (isinstance(self.user_id, bool) or self.user_id <= 0):
            raise ValueError("user_id must be a positive integer")
        if self.kind is ScenarioGovernanceActorKind.HUMAN and self.user_id is None:
            raise ValueError("human governance actors require a persisted user_id")
        roles = tuple(sorted({item.strip() for item in self.roles if item.strip()}))
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "roles", roles)

    @property
    def is_human_staff(self) -> bool:
        """Return whether this actor may approve or execute production writes."""

        return self.kind is ScenarioGovernanceActorKind.HUMAN and self.is_staff


@dataclass(frozen=True)
class ScenarioGovernancePreview:
    """Durable, actor-bound evidence for one exact write request."""

    preview_id: str
    actor_id: str
    actor_kind: ScenarioGovernanceActorKind
    capability_key: str
    operation: ScenarioGovernanceOperation
    scenario_key: str | None
    request_fingerprint: str
    base_version: int | None
    base_hash: str | None
    after_hash: str
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Enforce hash and timezone invariants at the pure-domain boundary."""

        for field_name, value in (
            ("preview_id", self.preview_id),
            ("actor_id", self.actor_id),
            ("capability_key", self.capability_key),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        for field_name, value in (
            ("request_fingerprint", self.request_fingerprint),
            ("after_hash", self.after_hash),
        ):
            _require_sha256(field_name, value)
        if self.base_hash is not None:
            _require_sha256("base_hash", self.base_hash)
        if self.base_version is not None and self.base_version < 1:
            raise ValueError("base_version must be positive")
        _require_aware("expires_at", self.expires_at)
        _require_aware("created_at", self.created_at)
        if self.consumed_at is not None:
            _require_aware("consumed_at", self.consumed_at)
        if self.expires_at <= self.created_at:
            raise ValueError("preview expiry must be after creation")


@dataclass(frozen=True)
class ScenarioGovernanceProposal:
    """Risk Center binding for a persistent AgentProposal lifecycle."""

    proposal_id: int
    operation: ScenarioGovernanceOperation
    creator_actor_id: str
    creator_actor_kind: ScenarioGovernanceActorKind
    capability_key: str
    request_fingerprint: str
    preview_id: str
    status: str
    revision_id: str | None = None
    approved_by_actor_id: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate persisted proposal references and lifecycle timestamps."""

        if isinstance(self.proposal_id, bool) or self.proposal_id <= 0:
            raise ValueError("proposal_id must be positive")
        for field_name, value in (
            ("creator_actor_id", self.creator_actor_id),
            ("capability_key", self.capability_key),
            ("preview_id", self.preview_id),
            ("status", self.status),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        _require_sha256("request_fingerprint", self.request_fingerprint)
        if self.approved_at is not None:
            _require_aware("approved_at", self.approved_at)
        if self.executed_at is not None:
            _require_aware("executed_at", self.executed_at)


@dataclass(frozen=True)
class ScenarioGovernanceAuditRecord:
    """Append-only canonical domain audit request written in the business transaction."""

    operation: str
    actor_id: str
    actor_kind: ScenarioGovernanceActorKind
    capability_key: str
    request_fingerprint: str
    correlation_id: str
    scenario_key: str | None = None
    proposal_id: int | None = None
    preview_id: str | None = None
    revision_id: str | None = None
    scenario_set_revision_id: str | None = None
    activation_id: str | None = None
    idempotency_key: str | None = None
    base_version: int | None = None
    before_hash: str | None = None
    after_hash: str | None = None
    approver_actor_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate stable identifiers before the audit adapter receives the record."""

        for field_name, value in (
            ("operation", self.operation),
            ("actor_id", self.actor_id),
            ("capability_key", self.capability_key),
            ("correlation_id", self.correlation_id),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} is required")
        _require_sha256("request_fingerprint", self.request_fingerprint)
        if self.before_hash is not None:
            _require_sha256("before_hash", self.before_hash)
        if self.after_hash is not None:
            _require_sha256("after_hash", self.after_hash)


@dataclass(frozen=True)
class ScenarioGovernanceOutcome:
    """Transport-neutral successful outcome with stable status semantics."""

    status: ScenarioGovernanceStatus
    operation: ScenarioGovernanceOperation
    correlation_id: str
    scenario_key: str | None = None
    revision_id: str | None = None
    proposal_id: int | None = None
    preview_id: str | None = None
    version: int | None = None
    content_hash: str | None = None
    activation_id: str | None = None
    audit_id: str | None = None
    request_fingerprint: str | None = None
    base_version: int | None = None
    base_hash: str | None = None
    after_hash: str | None = None
    expires_at: datetime | None = None
    warnings: tuple[str, ...] = ()
    blocked_reason: str | None = None
    must_not_use_for_decision: bool = False
    replayed: bool = False
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Keep status output identifiers and timestamps well formed."""

        if not self.correlation_id.strip():
            raise ValueError("correlation_id is required")
        if self.version is not None and self.version < 1:
            raise ValueError("version must be positive")
        for field_name, value in (
            ("content_hash", self.content_hash),
            ("request_fingerprint", self.request_fingerprint),
            ("base_hash", self.base_hash),
            ("after_hash", self.after_hash),
        ):
            if value is not None:
                _require_sha256(field_name, value)
        if self.expires_at is not None:
            _require_aware("expires_at", self.expires_at)

    def as_dict(self) -> dict[str, object]:
        """Return the stable JSON-ready success contract."""

        return {
            "status": self.status.value,
            "operation": self.operation.value,
            "correlation_id": self.correlation_id,
            "scenario_key": self.scenario_key,
            "revision_id": self.revision_id,
            "proposal_id": self.proposal_id,
            "preview_id": self.preview_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "activation_id": self.activation_id,
            "audit_id": self.audit_id,
            "request_fingerprint": self.request_fingerprint,
            "base_version": self.base_version,
            "base_hash": self.base_hash,
            "after_hash": self.after_hash,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "warnings": list(self.warnings),
            "blocked_reason": self.blocked_reason,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "replayed": self.replayed,
            "details": _json_value(self.details),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ScenarioGovernanceOutcome:
        """Rehydrate a stored idempotent result without recomputing business state."""

        expires_at = value.get("expires_at")
        details = value.get("details")
        warnings = value.get("warnings")
        return cls(
            status=ScenarioGovernanceStatus(str(value["status"])),
            operation=ScenarioGovernanceOperation(str(value["operation"])),
            correlation_id=str(value["correlation_id"]),
            scenario_key=_optional_text(value.get("scenario_key")),
            revision_id=_optional_text(value.get("revision_id")),
            proposal_id=_optional_positive_int(value.get("proposal_id")),
            preview_id=_optional_text(value.get("preview_id")),
            version=_optional_positive_int(value.get("version")),
            content_hash=_optional_text(value.get("content_hash")),
            activation_id=_optional_text(value.get("activation_id")),
            audit_id=_optional_text(value.get("audit_id")),
            request_fingerprint=_optional_text(value.get("request_fingerprint")),
            base_version=_optional_positive_int(value.get("base_version")),
            base_hash=_optional_text(value.get("base_hash")),
            after_hash=_optional_text(value.get("after_hash")),
            expires_at=(
                datetime.fromisoformat(str(expires_at)) if expires_at is not None else None
            ),
            warnings=(
                tuple(str(item) for item in warnings)
                if isinstance(warnings, Sequence) and not isinstance(warnings, (str, bytes))
                else ()
            ),
            blocked_reason=_optional_text(value.get("blocked_reason")),
            must_not_use_for_decision=bool(value.get("must_not_use_for_decision", False)),
            replayed=bool(value.get("replayed", False)),
            details=(details if isinstance(details, Mapping) else {}),
        )

    def as_replay(self) -> ScenarioGovernanceOutcome:
        """Return the original outcome marked as an idempotent replay."""

        return replace(self, replayed=True)


class ScenarioGovernanceError(RuntimeError):
    """Stable blocked/rejected error that transports can map without string parsing."""

    def __init__(
        self,
        code: ScenarioGovernanceErrorCode,
        message: str,
        *,
        conflict: bool = False,
    ) -> None:
        self.code = code
        self.conflict = conflict
        self.safe_message = " ".join(message.split())[:500]
        super().__init__(self.safe_message)

    def as_dict(self, *, correlation_id: str) -> dict[str, object]:
        """Return a stable fail-closed error envelope."""

        return {
            "status": "rejected",
            "error": {
                "code": self.code.value,
                "message": self.safe_message,
                "conflict": self.conflict,
            },
            "blocked_reason": self.code.value,
            "must_not_use_for_decision": True,
            "correlation_id": correlation_id,
        }


def require_human_staff(actor: ScenarioGovernanceActor, *, action: str) -> None:
    """Fail closed unless the actor is an authenticated human staff user."""

    if not actor.is_human_staff:
        raise ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.PERMISSION_DENIED,
            f"{action} requires a human staff actor",
        )


def scenario_governance_fingerprint(
    *,
    operation: ScenarioGovernanceOperation,
    capability_key: str,
    payload: Mapping[str, object],
    base_version: int | None,
    base_hash: str | None,
) -> str:
    """Hash the exact normalized payload and optimistic-lock evidence."""

    return stable_governance_hash(
        {
            "operation": operation.value,
            "capability_key": capability_key,
            "payload": payload,
            "base_version": base_version,
            "base_hash": base_hash,
        }
    )


def stable_governance_hash(payload: Mapping[str, object]) -> str:
    """Return a canonical SHA-256 digest for a JSON-safe governance value."""

    encoded = json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def governance_json_value(value: object) -> object:
    """Return a detached JSON-safe value for persistence adapters."""

    return json.loads(
        json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        _require_aware("datetime", value)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported governance JSON value: {type(value).__name__}")


def _require_sha256(field_name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lower-case SHA-256 digest")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized or None


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("stored positive integer cannot be boolean")
    if not isinstance(value, (str, int)):
        raise ValueError("stored positive integer has an invalid type")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("stored integer must be positive")
    return parsed


__all__ = [
    "ScenarioGovernanceActor",
    "ScenarioGovernanceActorKind",
    "ScenarioGovernanceAuditRecord",
    "ScenarioGovernanceError",
    "ScenarioGovernanceErrorCode",
    "ScenarioGovernanceOperation",
    "ScenarioGovernanceOutcome",
    "ScenarioGovernancePreview",
    "ScenarioGovernanceProposal",
    "ScenarioGovernanceStatus",
    "governance_json_value",
    "require_human_staff",
    "scenario_governance_fingerprint",
    "stable_governance_hash",
]
