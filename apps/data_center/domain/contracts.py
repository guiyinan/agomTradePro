"""Typed, provider-neutral contracts for the canonical data plane.

The contracts in this module intentionally contain no Django or provider
dependencies.  They are the boundary between ingestion, publication and
consumer-facing query ports.  Legacy flat dictionaries may be adapted at an
application edge, but new data-center code should carry these values together.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, TypeVar

from shared.domain.reliability import ReliabilityContract, ReliabilityStatus

T = TypeVar("T")


class FetchOutcome(str, Enum):
    """Outcome of a provider fetch before persistence or publication."""

    SUCCESS = "success"
    PARTIAL = "partial"
    NOOP = "noop"
    BLOCKED = "blocked"
    FAILED = "failed"


class PublicationState(str, Enum):
    """Lifecycle state of a canonical dataset publication."""

    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


@dataclass(frozen=True)
class DatasetKey:
    """Stable identity and version for one canonical dataset contract."""

    value: str
    contract_version: str
    schema_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("value", self.value),
            ("contract_version", self.contract_version),
            ("schema_version", self.schema_version),
        ):
            if not value.strip():
                raise ValueError(f"DatasetKey.{name} cannot be empty")
        if any(char.isspace() for char in self.value):
            raise ValueError("DatasetKey.value cannot contain whitespace")


@dataclass(frozen=True)
class NaturalKey:
    """Canonical natural key with deterministic serialization."""

    values: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("NaturalKey.values cannot be empty")
        keys = [key for key, _ in self.values]
        if len(keys) != len(set(keys)):
            raise ValueError("NaturalKey keys must be unique")
        if any(not key.strip() for key in keys):
            raise ValueError("NaturalKey keys cannot be empty")

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation for persistence and audit."""

        return dict(self.values)


@dataclass(frozen=True)
class ObservationTime:
    """Preserve source time semantics across the full data lifecycle."""

    observed_at: datetime | None
    published_at: datetime | None
    available_at: datetime | None
    fetched_at: datetime

    def __post_init__(self) -> None:
        if self.fetched_at.utcoffset() is None:
            raise ValueError("ObservationTime.fetched_at must be timezone-aware")
        for field_name, value in (
            ("observed_at", self.observed_at),
            ("published_at", self.published_at),
            ("available_at", self.available_at),
        ):
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"ObservationTime.{field_name} must be timezone-aware")
        if self.observed_at is not None and self.fetched_at < self.observed_at:
            raise ValueError("fetched_at cannot precede observed_at")
        if self.published_at is not None and self.available_at is not None:
            if self.available_at < self.published_at:
                raise ValueError("available_at cannot precede published_at")


@dataclass(frozen=True)
class SourceEvidence:
    """Evidence needed to trace a fact back to a provider response."""

    source: str
    source_capability: str
    payload_hash: str
    raw_audit_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.source_capability.strip():
            raise ValueError("SourceEvidence source and capability are required")
        if len(self.payload_hash) < 16 or any(char.isspace() for char in self.payload_hash):
            raise ValueError("SourceEvidence.payload_hash must be a compact digest")
        if self.raw_audit_id is not None and not self.raw_audit_id.strip():
            raise ValueError("SourceEvidence.raw_audit_id cannot be blank")

    @classmethod
    def from_payload(
        cls,
        *,
        source: str,
        source_capability: str,
        payload: object,
        raw_audit_id: str | None = None,
    ) -> SourceEvidence:
        """Build deterministic evidence from a JSON-compatible provider payload."""

        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
        return cls(
            source=source,
            source_capability=source_capability,
            payload_hash=hashlib.sha256(encoded).hexdigest(),
            raw_audit_id=raw_audit_id,
        )


@dataclass(frozen=True)
class QualityAssessment:
    """Static quality assessment kept separate from dynamic freshness."""

    schema_valid: bool
    completeness_ratio: float
    unit_valid: bool
    natural_key_valid: bool
    conflict: bool = False
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.completeness_ratio <= 1.0:
            raise ValueError("QualityAssessment.completeness_ratio must be in [0, 1]")
        if any(not issue.strip() for issue in self.issues):
            raise ValueError("QualityAssessment issues cannot be blank")

    @property
    def is_acceptable(self) -> bool:
        """Return whether the value can enter canonical publication."""

        return (
            self.schema_valid
            and self.unit_valid
            and self.natural_key_valid
            and not self.conflict
            and self.completeness_ratio > 0.0
        )


@dataclass(frozen=True)
class DataEnvelope(Generic[T]):
    """One business-visible value plus its immutable provenance contract."""

    dataset: DatasetKey
    natural_key: NaturalKey
    value: T | None
    observation: ObservationTime
    evidence: SourceEvidence
    quality: QualityAssessment
    reliability: ReliabilityContract
    unit: str | None = None
    original_unit: str | None = None
    publication_id: str | None = None
    is_current: bool = False

    def __post_init__(self) -> None:
        if self.unit is not None and not self.unit.strip():
            raise ValueError("DataEnvelope.unit cannot be blank")
        if self.original_unit is not None and not self.original_unit.strip():
            raise ValueError("DataEnvelope.original_unit cannot be blank")
        if self.is_current and not self.publication_id:
            raise ValueError("current DataEnvelope requires publication_id")
        if self.reliability.status is ReliabilityStatus.FRESH and not self.quality.is_acceptable:
            raise ValueError("fresh DataEnvelope requires acceptable quality")
        if self.value is None and not self.reliability.must_not_use_for_decision:
            raise ValueError("missing DataEnvelope value must fail closed")

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe envelope without rewriting source times."""

        return {
            "dataset_key": self.dataset.value,
            "contract_version": self.dataset.contract_version,
            "schema_version": self.dataset.schema_version,
            "natural_key": self.natural_key.as_dict(),
            "value": self.value,
            "observed_at": self.observation.observed_at.isoformat()
            if self.observation.observed_at
            else None,
            "published_at": self.observation.published_at.isoformat()
            if self.observation.published_at
            else None,
            "available_at": self.observation.available_at.isoformat()
            if self.observation.available_at
            else None,
            "fetched_at": self.observation.fetched_at.isoformat(),
            "source": self.evidence.source,
            "source_capability": self.evidence.source_capability,
            "payload_hash": self.evidence.payload_hash,
            "raw_audit_id": self.evidence.raw_audit_id,
            "unit": self.unit,
            "original_unit": self.original_unit,
            "quality": {
                "schema_valid": self.quality.schema_valid,
                "completeness_ratio": self.quality.completeness_ratio,
                "unit_valid": self.quality.unit_valid,
                "natural_key_valid": self.quality.natural_key_valid,
                "conflict": self.quality.conflict,
                "issues": list(self.quality.issues),
            },
            "reliability": self.reliability.to_dict(),
            "publication_id": self.publication_id,
            "is_current": self.is_current,
        }


@dataclass(frozen=True)
class FetchResult(Generic[T]):
    """Provider result with acceptance evidence and explicit business outcome."""

    outcome: FetchOutcome
    values: tuple[T, ...]
    provider: str
    dataset: DatasetKey
    evidence: SourceEvidence | None
    reliability: ReliabilityContract
    quality: QualityAssessment
    error_code: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("FetchResult.provider cannot be empty")
        if self.outcome is FetchOutcome.SUCCESS and not self.values:
            raise ValueError("success FetchResult requires at least one value")
        if self.outcome in {FetchOutcome.FAILED, FetchOutcome.BLOCKED} and not self.error_code:
            raise ValueError("failed or blocked FetchResult requires error_code")
        if self.outcome is FetchOutcome.SUCCESS and self.evidence is None:
            raise ValueError("success FetchResult requires source evidence")

    @property
    def acceptable(self) -> bool:
        """Return whether failover may accept and publish this result."""

        return (
            self.outcome is FetchOutcome.SUCCESS
            and bool(self.values)
            and self.evidence is not None
            and self.quality.is_acceptable
            and not self.reliability.must_not_use_for_decision
        )


@dataclass(frozen=True)
class PublicationDecision:
    """Auditable result of selecting one canonical version for publication."""

    publication_id: str
    dataset: DatasetKey
    state: PublicationState
    selected_source: str | None
    selected_member_hash: str | None
    coverage_ratio: float
    conflict_count: int
    runtime_snapshot_id: str | None = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        if not self.publication_id.strip():
            raise ValueError("PublicationDecision.publication_id cannot be empty")
        if not 0.0 <= self.coverage_ratio <= 1.0:
            raise ValueError("PublicationDecision.coverage_ratio must be in [0, 1]")
        if self.conflict_count < 0:
            raise ValueError("PublicationDecision.conflict_count cannot be negative")
        if self.state is PublicationState.PUBLISHED and not self.selected_source:
            raise ValueError("published PublicationDecision requires selected_source")


@dataclass(frozen=True)
class SyncOutcome:
    """Normalized result for every data-writing task or command."""

    outcome: FetchOutcome
    requested: int
    succeeded: int
    failed: int
    stored: int
    run_id: str
    checkpoint: str | None = None
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("SyncOutcome.run_id cannot be empty")
        if min(self.requested, self.succeeded, self.failed, self.stored) < 0:
            raise ValueError("SyncOutcome counts cannot be negative")
        if self.succeeded + self.failed > self.requested:
            raise ValueError("SyncOutcome succeeded + failed exceeds requested")
        if self.stored > self.succeeded:
            raise ValueError("SyncOutcome.stored cannot exceed succeeded")
        if self.stored == 0 and self.outcome is FetchOutcome.SUCCESS:
            raise ValueError("zero stored rows cannot be reported as success")


@dataclass(frozen=True)
class DatasetFieldContract:
    """Schema and semantic rule for one field in a dataset."""

    name: str
    value_type: str
    unit: str | None
    nullable: bool
    zero_allowed: bool
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.value_type.strip():
            raise ValueError("DatasetFieldContract name and value_type are required")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("DatasetFieldContract minimum cannot exceed maximum")


@dataclass(frozen=True)
class DatasetContract:
    """Versioned dataset contract owned by the Data Center catalog."""

    key: DatasetKey
    owner: str
    frequency: str
    decision_critical: bool
    fields: tuple[DatasetFieldContract, ...]
    freshness_seconds: int | None = None
    comparable_group: str | None = None

    def __post_init__(self) -> None:
        if not self.owner.strip() or not self.frequency.strip():
            raise ValueError("DatasetContract owner and frequency are required")
        if not self.fields:
            raise ValueError("DatasetContract.fields cannot be empty")
        if self.freshness_seconds is not None and self.freshness_seconds <= 0:
            raise ValueError("DatasetContract.freshness_seconds must be positive")


@dataclass(frozen=True)
class ProviderBinding:
    """Versioned provider binding for one dataset capability."""

    dataset: DatasetKey
    provider: str
    capability: str
    priority: int
    freshness_seconds: int | None
    validator_key: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.capability.strip():
            raise ValueError("ProviderBinding provider and capability are required")
        if self.priority < 0:
            raise ValueError("ProviderBinding.priority cannot be negative")
        if self.freshness_seconds is not None and self.freshness_seconds <= 0:
            raise ValueError("ProviderBinding.freshness_seconds must be positive")
        if not self.validator_key.strip():
            raise ValueError("ProviderBinding.validator_key is required")


@dataclass(frozen=True)
class PublicationPolicy:
    """Fail-closed policy for publishing one canonical dataset revision."""

    dataset: DatasetKey
    minimum_coverage_ratio: float
    allow_partial: bool
    conflict_action: str
    required_evidence: tuple[str, ...]
    retention_days: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_coverage_ratio <= 1.0:
            raise ValueError("PublicationPolicy.minimum_coverage_ratio must be in [0, 1]")
        if self.conflict_action not in {"block", "quarantine", "prefer_governed_source"}:
            raise ValueError("PublicationPolicy.conflict_action is not supported")
        if not self.required_evidence:
            raise ValueError("PublicationPolicy.required_evidence cannot be empty")
        if self.retention_days <= 0:
            raise ValueError("PublicationPolicy.retention_days must be positive")


__all__ = [
    "DataEnvelope",
    "DatasetContract",
    "DatasetFieldContract",
    "DatasetKey",
    "FetchOutcome",
    "FetchResult",
    "NaturalKey",
    "ObservationTime",
    "PublicationDecision",
    "PublicationPolicy",
    "PublicationState",
    "ProviderBinding",
    "QualityAssessment",
    "SourceEvidence",
    "SyncOutcome",
]
