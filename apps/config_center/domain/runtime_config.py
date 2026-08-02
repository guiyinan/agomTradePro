"""Typed, versioned runtime configuration domain objects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
from typing import Any


class RuntimeValueType(str, Enum):
    """Supported scalar and structured configuration value types."""

    BOOL = "bool"
    INT = "int"
    DECIMAL = "decimal"
    STRING = "string"
    DURATION = "duration"
    BYTES = "bytes"
    PERCENTAGE = "percentage"
    ENUM = "enum"
    TYPED_JSON = "typed_json"


class RuntimeConfigCriticality(str, Enum):
    """Operational impact of a configuration definition."""

    BOOTSTRAP = "bootstrap"
    CRITICAL = "critical"
    NORMAL = "normal"
    EXPERIMENTAL = "experimental"


class RuntimeConfigReloadMode(str, Enum):
    """When a changed value becomes effective."""

    IMMEDIATE = "immediate"
    NEXT_TASK = "next_task"
    RESTART_REQUIRED = "restart_required"


class RuntimeProfileStatus(str, Enum):
    """Lifecycle of a versioned configuration profile."""

    DRAFT = "draft"
    VALIDATING = "validating"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(frozen=True)
class RuntimeConfigDefinition:
    """Registry metadata and validation rules for one stable key."""

    key: str
    namespace: str
    owner_app: str
    value_type: RuntimeValueType
    unit: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    criticality: RuntimeConfigCriticality = RuntimeConfigCriticality.NORMAL
    secret: bool = False
    reload_mode: RuntimeConfigReloadMode = RuntimeConfigReloadMode.NEXT_TASK
    description: str = ""
    user_impact: str = ""
    is_deprecated: bool = False
    replacement_key: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip() or "." not in self.key:
            raise ValueError("RuntimeConfigDefinition.key must be a namespaced key")
        if not self.namespace.strip() or not self.owner_app.strip():
            raise ValueError("RuntimeConfigDefinition namespace and owner_app are required")
        if self.secret and self.value_type is RuntimeValueType.TYPED_JSON:
            raise ValueError("Secret typed_json values must use secret_ref only")
        if self.is_deprecated and not self.replacement_key.strip():
            raise ValueError("Deprecated definitions require replacement_key")

    def validate(self, value: object, *, secret_ref: str = "") -> None:
        """Validate one value against its declared type and constraints."""

        if self.secret:
            if value not in (None, "", {}):
                raise ValueError(f"{self.key} is secret; store only secret_ref")
            if not secret_ref.strip():
                raise ValueError(f"{self.key} requires secret_ref")
            return
        if secret_ref:
            raise ValueError(f"{self.key} is not secret and cannot have secret_ref")
        if self.value_type is RuntimeValueType.BOOL and not isinstance(value, bool):
            raise ValueError(f"{self.key} requires bool")
        if self.value_type is RuntimeValueType.INT and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"{self.key} requires int")
        if self.value_type in {RuntimeValueType.DECIMAL, RuntimeValueType.PERCENTAGE}:
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f"{self.key} requires decimal") from exc
            if self.value_type is RuntimeValueType.PERCENTAGE and not Decimal(
                "0"
            ) <= decimal_value <= Decimal("1"):
                raise ValueError(f"{self.key} percentage must be in [0, 1]")
        elif self.value_type is RuntimeValueType.STRING and not isinstance(value, str):
            raise ValueError(f"{self.key} requires string")
        elif self.value_type in {RuntimeValueType.DURATION, RuntimeValueType.BYTES} and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"{self.key} requires a non-negative integer")
        elif self.value_type is RuntimeValueType.ENUM:
            choices = self.constraints.get("choices", ())
            if value not in choices:
                raise ValueError(f"{self.key} must be one of {choices}")
        elif self.value_type is RuntimeValueType.TYPED_JSON and not isinstance(value, (dict, list)):
            raise ValueError(f"{self.key} requires JSON object or array")
        minimum = self.constraints.get("minimum")
        maximum = self.constraints.get("maximum")
        if minimum is not None and Decimal(str(value)) < Decimal(str(minimum)):
            raise ValueError(f"{self.key} is below minimum")
        if maximum is not None and Decimal(str(value)) > Decimal(str(maximum)):
            raise ValueError(f"{self.key} is above maximum")


@dataclass(frozen=True)
class RuntimeConfigProfile:
    """Versioned desired-state profile."""

    profile_id: str
    profile_key: str
    environment: str
    version: int
    status: RuntimeProfileStatus = RuntimeProfileStatus.DRAFT
    based_on_profile: str = ""
    content_hash: str = ""
    created_by: str = "system"
    activated_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    change_reason: str = ""
    release_ref: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.profile_key.strip():
            raise ValueError("RuntimeConfigProfile identifiers are required")
        if self.version < 1:
            raise ValueError("RuntimeConfigProfile.version must be positive")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("RuntimeConfigProfile.created_at must be timezone-aware")
        if self.activated_at is not None and (
            self.activated_at.tzinfo is None or self.activated_at.utcoffset() is None
        ):
            raise ValueError("RuntimeConfigProfile.activated_at must be timezone-aware")
        if self.status is RuntimeProfileStatus.ACTIVE and not self.content_hash:
            raise ValueError("Active profile requires content_hash")


@dataclass(frozen=True)
class RuntimeConfigValue:
    """One validated definition value in a profile."""

    profile_id: str
    definition_key: str
    value_json: Any = None
    secret_ref: str = ""
    source: str = "admin"
    validation_status: str = "valid"
    validation_error: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.definition_key.strip():
            raise ValueError("RuntimeConfigValue profile_id and definition_key are required")
        if self.validation_status not in {"valid", "invalid", "pending"}:
            raise ValueError("RuntimeConfigValue.validation_status is unsupported")


@dataclass(frozen=True)
class RuntimeConfigRevision:
    """Immutable audit record for a profile change."""

    revision_id: str
    profile_id: str
    before_hash: str
    after_hash: str
    changed_keys: tuple[str, ...]
    before_projection: dict[str, Any]
    after_projection: dict[str, Any]
    actor: str
    reason: str
    changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    release_ref: str = ""
    validation_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.revision_id.strip() or not self.profile_id.strip():
            raise ValueError("RuntimeConfigRevision identifiers are required")
        if not self.actor.strip() or not self.reason.strip():
            raise ValueError("RuntimeConfigRevision actor and reason are required")
        if self.changed_at.tzinfo is None or self.changed_at.utcoffset() is None:
            raise ValueError("RuntimeConfigRevision.changed_at must be timezone-aware")


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    """Resolved immutable configuration used by tasks and decisions."""

    snapshot_id: str
    profile_id: str
    profile_key: str
    profile_version: int
    snapshot_hash: str
    resolved_values: dict[str, Any]
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    effective_from: datetime | None = None
    validation_report: dict[str, Any] = field(default_factory=dict)
    consumer_acknowledgement: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.profile_id.strip():
            raise ValueError("RuntimeConfigSnapshot identifiers are required")
        if self.profile_version < 1 or not self.snapshot_hash.strip():
            raise ValueError("RuntimeConfigSnapshot requires version and hash")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("RuntimeConfigSnapshot.generated_at must be timezone-aware")

    @staticmethod
    def hash_values(values: dict[str, Any]) -> str:
        """Return a deterministic hash for a resolved, JSON-safe projection."""

        serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StorageBudgetPolicy:
    """Configurable storage capacity and watermarks."""

    policy_key: str
    version: int
    configured_capacity_bytes: int
    raw_budget_ratio: float
    quarantine_budget_ratio: float
    database_budget_ratio: float
    logs_budget_ratio: float
    emergency_reserve_ratio: float
    warning_ratio: float
    critical_ratio: float
    active: bool = False

    def __post_init__(self) -> None:
        if not self.policy_key.strip() or self.version < 1:
            raise ValueError("StorageBudgetPolicy key/version are required")
        if self.configured_capacity_bytes <= 0:
            raise ValueError("StorageBudgetPolicy capacity must be positive")
        ratios = (
            self.raw_budget_ratio,
            self.quarantine_budget_ratio,
            self.database_budget_ratio,
            self.logs_budget_ratio,
            self.emergency_reserve_ratio,
            self.warning_ratio,
            self.critical_ratio,
        )
        if any(not 0.0 <= value <= 1.0 for value in ratios):
            raise ValueError("StorageBudgetPolicy ratios must be in [0, 1]")
        if self.warning_ratio >= self.critical_ratio:
            raise ValueError("warning_ratio must be below critical_ratio")
        if (
            self.raw_budget_ratio
            + self.quarantine_budget_ratio
            + self.database_budget_ratio
            + self.logs_budget_ratio
            + self.emergency_reserve_ratio
            > 1.0
        ):
            raise ValueError("StorageBudgetPolicy sub-budgets exceed capacity")


@dataclass(frozen=True)
class StorageCapacityObservation:
    """Immutable filesystem/database capacity evidence for one observation."""

    observation_id: str
    environment: str
    observed_at: datetime
    filesystem_total_bytes: int
    filesystem_used_bytes: int
    filesystem_free_bytes: int
    database_size_bytes: int
    relation_sizes: dict[str, int] = field(default_factory=dict)
    policy_key: str = ""
    configured_capacity_bytes: int | None = None
    effective_capacity_bytes: int | None = None
    usage_ratio: float | None = None
    pressure_state: str = ""
    source: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.environment.strip():
            raise ValueError("StorageCapacityObservation identifiers are required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("StorageCapacityObservation.observed_at must be timezone-aware")
        byte_values = (
            self.filesystem_total_bytes,
            self.filesystem_used_bytes,
            self.filesystem_free_bytes,
            self.database_size_bytes,
        )
        if any(isinstance(value, bool) or value < 0 for value in byte_values):
            raise ValueError("StorageCapacityObservation byte values must be non-negative")
        if self.filesystem_used_bytes + self.filesystem_free_bytes > self.filesystem_total_bytes:
            raise ValueError("filesystem used + free cannot exceed total capacity")
        if any(isinstance(value, bool) or value < 0 for value in self.relation_sizes.values()):
            raise ValueError("relation sizes must be non-negative")
        if self.configured_capacity_bytes is not None and self.configured_capacity_bytes <= 0:
            raise ValueError("configured capacity must be positive when provided")
        if self.effective_capacity_bytes is not None and self.effective_capacity_bytes <= 0:
            raise ValueError("effective capacity must be positive when provided")
        if self.usage_ratio is not None and (
            not isfinite(self.usage_ratio) or self.usage_ratio < 0.0
        ):
            raise ValueError("usage ratio must be finite and non-negative")


__all__ = [
    "RuntimeConfigCriticality",
    "RuntimeConfigDefinition",
    "RuntimeConfigProfile",
    "RuntimeConfigReloadMode",
    "RuntimeConfigRevision",
    "RuntimeConfigSnapshot",
    "RuntimeConfigValue",
    "RuntimeProfileStatus",
    "RuntimeValueType",
    "StorageBudgetPolicy",
    "StorageCapacityObservation",
]
