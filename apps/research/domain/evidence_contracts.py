"""Canonical evidence-envelope contracts for decision-facing research outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from shared.domain.reliability import ReliabilityContract, ReliabilityStatus


class ClaimKind(str, Enum):
    """What kind of assertion an output makes."""

    OBSERVATION = "observation"
    DERIVED = "derived"
    ESTIMATE = "estimate"
    FORECAST = "forecast"
    RECOMMENDATION = "recommendation"


class MethodKind(str, Enum):
    """How an output is produced."""

    IDENTITY = "identity"
    DETERMINISTIC = "deterministic"
    STATISTICAL = "statistical"
    SIMULATION = "simulation"
    HUMAN_JUDGMENT = "human_judgment"


class GovernanceState(str, Enum):
    """Lifecycle state assigned by the output owner's governance stream."""

    RESEARCH_ONLY = "research_only"
    PROMOTED = "promoted"
    DEGRADED = "degraded"
    RETIRED = "retired"
    BLOCKED = "blocked"


class DecisionPermission(str, Enum):
    """Ordered permission axis for evidence-governed outputs."""

    DISPLAY_ONLY = "display_only"
    ADVISORY = "advisory"
    DECISION_ELIGIBLE = "decision_eligible"
    EXECUTION_ELIGIBLE = "execution_eligible"


class DependencyFlag(str, Enum):
    """Uncertainty-producing dependency categories propagated downstream."""

    ESTIMATED_INPUT = "estimated_input"
    FORECAST_INPUT = "forecast_input"
    SIMULATED_INPUT = "simulated_input"
    HUMAN_JUDGMENT_INPUT = "human_judgment_input"


class MetricDirection(str, Enum):
    """Direction used to interpret one track-record metric."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class EvidenceBlockerCode(str, Enum):
    """Stable fail-closed blocker codes published by envelope resolution."""

    REQUIRED_INPUT_MISSING = "evidence.required_input_missing"
    INPUT_UNRELIABLE = "evidence.input_unreliable"
    INPUT_PIT_UNVERIFIED = "evidence.input_pit_unverified"
    INPUT_HASH_CONFLICT = "evidence.input_hash_conflict"
    OPERATOR_EXPIRED = "evidence.operator_expired"
    OUTPUT_NOT_PROMOTED = "evidence.output_not_promoted"
    PROMOTION_MISSING = "evidence.promotion_missing"
    PROMOTION_EXPIRED = "evidence.promotion_expired"
    MONITORING_MISSING = "evidence.monitoring_missing"
    MONITORING_EXPIRED = "evidence.monitoring_expired"
    TRACK_RECORD_MISSING = "evidence.track_record_missing"
    TRACK_RECORD_MISMATCH = "evidence.track_record_mismatch"
    TRACK_RECORD_EXPIRED = "evidence.track_record_expired"
    TRACK_RECORD_EMPTY = "evidence.track_record_empty"
    LEGACY_UNVERIFIED = "evidence.legacy_unverified"


_PERMISSION_RANK = {
    DecisionPermission.DISPLAY_ONLY: 0,
    DecisionPermission.ADVISORY: 1,
    DecisionPermission.DECISION_ELIGIBLE: 2,
    DecisionPermission.EXECUTION_ELIGIBLE: 3,
}


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    try:
        if value != value.lower():
            raise ValueError
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a sha256 hex digest") from error


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_finite_decimal(value: object, field_name: str) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _minimum_permission(
    permissions: tuple[DecisionPermission, ...],
) -> DecisionPermission:
    if not permissions:
        raise ValueError("permissions must not be empty")
    return min(permissions, key=_PERMISSION_RANK.__getitem__)


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, order=True)
class ArtifactRef:
    """Content-addressed reference to one exact owner artifact version."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical JSON-compatible artifact identity."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class EvidenceOperatorSpec:
    """Activated owner specification that fixes output semantics and permission cap."""

    operator_id: str
    operator_version: str
    research_family: str
    output_artifact_type: str
    claim_kind: ClaimKind
    method_kind: MethodKind
    required_input_roles: tuple[str, ...]
    dependency_flags: frozenset[DependencyFlag]
    maximum_permission: DecisionPermission
    requires_track_record: bool
    activated_at: datetime
    valid_until: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        operator_id: str,
        operator_version: str,
        research_family: str,
        output_artifact_type: str,
        claim_kind: ClaimKind,
        method_kind: MethodKind,
        required_input_roles: tuple[str, ...],
        dependency_flags: frozenset[DependencyFlag],
        maximum_permission: DecisionPermission,
        requires_track_record: bool,
        activated_at: datetime,
        valid_until: datetime,
    ) -> EvidenceOperatorSpec:
        """Build a canonical operator specification and compute its content hash."""

        _require_aware(activated_at, "activated_at")
        _require_aware(valid_until, "valid_until")
        values: dict[str, object] = {
            "operator_id": operator_id,
            "operator_version": operator_version,
            "research_family": research_family,
            "output_artifact_type": output_artifact_type,
            "claim_kind": claim_kind.value,
            "method_kind": method_kind.value,
            "required_input_roles": list(required_input_roles),
            "dependency_flags": sorted(item.value for item in dependency_flags),
            "maximum_permission": maximum_permission.value,
            "requires_track_record": requires_track_record,
            "activated_at": _utc_text(activated_at),
            "valid_until": _utc_text(valid_until),
        }
        return cls(
            operator_id=operator_id,
            operator_version=operator_version,
            research_family=research_family,
            output_artifact_type=output_artifact_type,
            claim_kind=claim_kind,
            method_kind=method_kind,
            required_input_roles=required_input_roles,
            dependency_flags=dependency_flags,
            maximum_permission=maximum_permission,
            requires_track_record=requires_track_record,
            activated_at=activated_at,
            valid_until=valid_until,
            content_hash=_canonical_hash(values),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "operator_id",
            "operator_version",
            "research_family",
            "output_artifact_type",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.required_input_roles) is not tuple:
            raise TypeError("required_input_roles must be a tuple")
        for role in self.required_input_roles:
            _require_token(role, "required_input_role")
        if self.required_input_roles != tuple(sorted(set(self.required_input_roles))):
            raise ValueError("required_input_roles must be ordered and unique")
        if type(self.dependency_flags) is not frozenset:
            raise TypeError("dependency_flags must be a frozenset")
        _require_aware(self.activated_at, "activated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.activated_at >= self.valid_until:
            raise ValueError("operator validity window is invalid")
        expected_hash = _canonical_hash(_operator_payload(self))
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("operator specification content_hash is invalid")

    @property
    def artifact_ref(self) -> ArtifactRef:
        """Expose the specification as a content-addressed lineage reference."""

        return ArtifactRef(
            owner="research",
            artifact_type="evidence_operator_spec",
            artifact_id=self.operator_id,
            artifact_version=self.operator_version,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True)
class EvidenceInputBinding:
    """Exact input evidence consumed by one operator execution."""

    role: str
    artifact: ArtifactRef
    reliability: ReliabilityContract
    permission: DecisionPermission
    valid_until: datetime
    dependency_flags: frozenset[DependencyFlag] = frozenset()
    pit_verified: bool = True

    def __post_init__(self) -> None:
        _require_token(self.role, "role")
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be exact ArtifactRef")
        ArtifactRef.__post_init__(self.artifact)
        if type(self.reliability) is not ReliabilityContract:
            raise TypeError("reliability must be exact ReliabilityContract")
        ReliabilityContract.__post_init__(self.reliability)
        _require_aware(self.valid_until, "valid_until")
        if type(self.dependency_flags) is not frozenset:
            raise TypeError("dependency_flags must be a frozenset")
        if type(self.pit_verified) is not bool:
            raise TypeError("pit_verified must be a bool")


@dataclass(frozen=True)
class TrackRecordSnapshot:
    """Immutable, version-specific out-of-sample performance evidence."""

    snapshot_id: str
    snapshot_version: str
    artifact: ArtifactRef
    target: str
    horizon: str
    sample_policy_id: str
    sample_policy_version: str
    evaluated_at: datetime
    valid_until: datetime
    eligible: int
    resolved: int
    unresolved: int
    censored: int
    invalidated: int
    n_eff: Decimal
    coverage: Decimal
    market_regimes: tuple[str, ...]
    primary_metric_code: str | None
    primary_metric_unit: str | None
    metric_direction: MetricDirection | None
    primary_metric_value: Decimal | None
    benchmark_metric_value: Decimal | None
    skill_delta: Decimal | None
    confidence_interval_low: Decimal | None
    confidence_interval_high: Decimal | None
    drift_detected: bool
    promotion_ref: ArtifactRef
    outcome_refs: tuple[ArtifactRef, ...]
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "snapshot_version",
            "target",
            "horizon",
            "sample_policy_id",
            "sample_policy_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_aware(self.evaluated_at, "evaluated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.evaluated_at >= self.valid_until:
            raise ValueError("track-record validity window is invalid")
        counts = (
            self.eligible,
            self.resolved,
            self.unresolved,
            self.censored,
            self.invalidated,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("track-record denominator counts must be non-negative integers")
        for field_name in ("n_eff", "coverage"):
            _require_finite_decimal(getattr(self, field_name), field_name)
        if self.eligible != self.resolved + self.unresolved + self.censored + self.invalidated:
            raise ValueError("track-record denominator states must conserve eligible samples")
        if self.n_eff < 0 or self.n_eff > Decimal(self.resolved):
            raise ValueError("n_eff cannot exceed resolved samples")
        expected_coverage = (
            Decimal(0) if self.eligible == 0 else Decimal(self.resolved) / Decimal(self.eligible)
        )
        if self.coverage != expected_coverage:
            raise ValueError("coverage must equal resolved divided by eligible")
        if self.market_regimes != tuple(sorted(set(self.market_regimes))):
            raise ValueError("market_regimes must be ordered and unique")
        metric_values = (
            self.primary_metric_value,
            self.benchmark_metric_value,
            self.skill_delta,
            self.confidence_interval_low,
            self.confidence_interval_high,
        )
        for field_name in (
            "primary_metric_value",
            "benchmark_metric_value",
            "skill_delta",
            "confidence_interval_low",
            "confidence_interval_high",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_finite_decimal(value, field_name)
        if self.eligible == 0 and any(value is not None for value in metric_values):
            raise ValueError("eligible=0 cannot publish performance or confidence metrics")
        if self.eligible == 0 and any(
            value is not None
            for value in (
                self.primary_metric_code,
                self.primary_metric_unit,
                self.metric_direction,
            )
        ):
            raise ValueError("eligible=0 cannot publish metric metadata")
        if self.eligible > 0 and any(
            value is None
            for value in (
                self.primary_metric_code,
                self.primary_metric_unit,
                self.metric_direction,
                self.primary_metric_value,
                self.benchmark_metric_value,
                self.skill_delta,
                self.confidence_interval_low,
                self.confidence_interval_high,
            )
        ):
            raise ValueError("non-empty track record requires complete metric evidence")
        if (
            self.confidence_interval_low is not None
            and self.confidence_interval_high is not None
            and self.confidence_interval_low > self.confidence_interval_high
        ):
            raise ValueError("track-record confidence interval is inverted")
        if self.outcome_refs != tuple(sorted(set(self.outcome_refs))):
            raise ValueError("outcome_refs must be ordered and unique")
        expected_hash = _canonical_hash(_track_record_payload(self))
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("track-record content_hash is invalid")

    @property
    def artifact_ref(self) -> ArtifactRef:
        """Expose this snapshot as a content-addressed Research artifact."""

        return ArtifactRef(
            owner="research",
            artifact_type="track_record_snapshot",
            artifact_id=self.snapshot_id,
            artifact_version=self.snapshot_version,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True)
class GovernanceGrant:
    """Exact promotion and monitoring authority for one output artifact."""

    output_artifact: ArtifactRef
    promotion_ref: ArtifactRef
    governance_state: GovernanceState
    permission_cap: DecisionPermission
    promotion_valid_until: datetime
    monitoring_ref: ArtifactRef
    monitoring_permission_cap: DecisionPermission
    monitoring_valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in ("promotion_valid_until", "monitoring_valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if self.governance_state is not GovernanceState.PROMOTED:
            raise ValueError("governance grant must represent an active promotion")


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Resolved decision-safety envelope for one exact output artifact."""

    output_artifact: ArtifactRef
    operator_spec_ref: ArtifactRef
    claim_kind: ClaimKind
    method_kind: MethodKind
    research_family: str
    governance_state: GovernanceState
    permission: DecisionPermission
    lineage: tuple[ArtifactRef, ...]
    dependency_flags: frozenset[DependencyFlag]
    track_record_ref: ArtifactRef | None
    blockers: tuple[EvidenceBlockerCode, ...]
    evaluated_at: datetime
    valid_until: datetime
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in ("output_artifact", "operator_spec_ref"):
            value = getattr(self, field_name)
            if type(value) is not ArtifactRef:
                raise TypeError(f"{field_name} must be exact ArtifactRef")
            ArtifactRef.__post_init__(value)
        _require_token(self.research_family, "research_family")
        if type(self.lineage) is not tuple or not self.lineage:
            raise ValueError("lineage must be a non-empty tuple")
        if self.lineage != tuple(sorted(set(self.lineage))):
            raise ValueError("lineage must be ordered and unique")
        if type(self.dependency_flags) is not frozenset:
            raise TypeError("dependency_flags must be a frozenset")
        if self.track_record_ref is not None:
            if type(self.track_record_ref) is not ArtifactRef:
                raise TypeError("track_record_ref must be exact ArtifactRef")
            ArtifactRef.__post_init__(self.track_record_ref)
        if self.blockers != tuple(sorted(set(self.blockers), key=lambda item: item.value)):
            raise ValueError("blockers must be ordered and unique")
        _require_aware(self.evaluated_at, "evaluated_at")
        _require_aware(self.valid_until, "valid_until")
        if self.evaluated_at >= self.valid_until:
            raise ValueError("evidence-envelope validity window is invalid")
        expected_hash = _canonical_hash(_envelope_payload(self))
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("evidence-envelope content_hash is invalid")

    @property
    def must_not_use_for_decision(self) -> bool:
        """Derive the compatibility decision blocker from the permission axis."""

        return (
            _PERMISSION_RANK[self.permission]
            < _PERMISSION_RANK[DecisionPermission.DECISION_ELIGIBLE]
        )

    @property
    def must_not_execute(self) -> bool:
        """Derive the compatibility execution blocker from the permission axis."""

        return self.permission is not DecisionPermission.EXECUTION_ELIGIBLE


def _operator_payload(spec: EvidenceOperatorSpec) -> dict[str, object]:
    return {
        "operator_id": spec.operator_id,
        "operator_version": spec.operator_version,
        "research_family": spec.research_family,
        "output_artifact_type": spec.output_artifact_type,
        "claim_kind": spec.claim_kind.value,
        "method_kind": spec.method_kind.value,
        "required_input_roles": list(spec.required_input_roles),
        "dependency_flags": sorted(item.value for item in spec.dependency_flags),
        "maximum_permission": spec.maximum_permission.value,
        "requires_track_record": spec.requires_track_record,
        "activated_at": _utc_text(spec.activated_at),
        "valid_until": _utc_text(spec.valid_until),
    }


def _track_record_payload(snapshot: TrackRecordSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "artifact": snapshot.artifact.to_payload(),
        "target": snapshot.target,
        "horizon": snapshot.horizon,
        "sample_policy_id": snapshot.sample_policy_id,
        "sample_policy_version": snapshot.sample_policy_version,
        "evaluated_at": _utc_text(snapshot.evaluated_at),
        "valid_until": _utc_text(snapshot.valid_until),
        "eligible": snapshot.eligible,
        "resolved": snapshot.resolved,
        "unresolved": snapshot.unresolved,
        "censored": snapshot.censored,
        "invalidated": snapshot.invalidated,
        "n_eff": str(snapshot.n_eff),
        "coverage": str(snapshot.coverage),
        "market_regimes": list(snapshot.market_regimes),
        "primary_metric_code": snapshot.primary_metric_code,
        "primary_metric_unit": snapshot.primary_metric_unit,
        "metric_direction": (
            snapshot.metric_direction.value if snapshot.metric_direction is not None else None
        ),
        "primary_metric_value": _optional_decimal_text(snapshot.primary_metric_value),
        "benchmark_metric_value": _optional_decimal_text(snapshot.benchmark_metric_value),
        "skill_delta": _optional_decimal_text(snapshot.skill_delta),
        "confidence_interval_low": _optional_decimal_text(snapshot.confidence_interval_low),
        "confidence_interval_high": _optional_decimal_text(snapshot.confidence_interval_high),
        "drift_detected": snapshot.drift_detected,
        "promotion_ref": snapshot.promotion_ref.to_payload(),
        "outcome_refs": [item.to_payload() for item in snapshot.outcome_refs],
    }


def _envelope_payload(envelope: EvidenceEnvelope) -> dict[str, object]:
    return {
        "output_artifact": envelope.output_artifact.to_payload(),
        "operator_spec_ref": envelope.operator_spec_ref.to_payload(),
        "claim_kind": envelope.claim_kind.value,
        "method_kind": envelope.method_kind.value,
        "research_family": envelope.research_family,
        "governance_state": envelope.governance_state.value,
        "permission": envelope.permission.value,
        "lineage": [item.to_payload() for item in envelope.lineage],
        "dependency_flags": sorted(item.value for item in envelope.dependency_flags),
        "track_record_ref": (
            envelope.track_record_ref.to_payload()
            if envelope.track_record_ref is not None
            else None
        ),
        "blockers": [item.value for item in envelope.blockers],
        "evaluated_at": _utc_text(envelope.evaluated_at),
        "valid_until": _utc_text(envelope.valid_until),
    }


def resolve_evidence_envelope(
    *,
    output_artifact: ArtifactRef,
    operator_spec: EvidenceOperatorSpec,
    inputs: tuple[EvidenceInputBinding, ...],
    governance_state: GovernanceState,
    governance_grant: GovernanceGrant | None,
    track_record: TrackRecordSnapshot | None,
    evaluated_at: datetime,
) -> EvidenceEnvelope:
    """Resolve lineage, uncertainty, validity, blockers, and effective permission."""

    _require_aware(evaluated_at, "evaluated_at")
    if output_artifact.artifact_type != operator_spec.output_artifact_type:
        raise ValueError("output artifact type differs from operator specification")
    if type(inputs) is not tuple:
        raise TypeError("inputs must be a tuple")

    roles = tuple(item.role for item in inputs)
    if len(roles) != len(set(roles)):
        raise ValueError("input roles must be unique")
    artifacts = tuple(item.artifact for item in inputs)
    if len(artifacts) != len(set(artifacts)):
        raise ValueError("input artifact identities must be unique")

    blockers: set[EvidenceBlockerCode] = set()
    required_roles = set(operator_spec.required_input_roles)
    if not required_roles.issubset(roles):
        blockers.add(EvidenceBlockerCode.REQUIRED_INPUT_MISSING)

    permissions = [operator_spec.maximum_permission]
    valid_until_candidates = [operator_spec.valid_until]
    dependency_flags = set(operator_spec.dependency_flags)
    lineage = set(artifacts)
    lineage.add(operator_spec.artifact_ref)

    for item in inputs:
        permissions.append(item.permission)
        valid_until_candidates.append(item.valid_until)
        dependency_flags.update(item.dependency_flags)
        if (
            item.reliability.status is not ReliabilityStatus.FRESH
            or item.reliability.must_not_use_for_decision
        ):
            blockers.add(EvidenceBlockerCode.INPUT_UNRELIABLE)
        if not item.pit_verified:
            blockers.add(EvidenceBlockerCode.INPUT_PIT_UNVERIFIED)

    if governance_state is GovernanceState.PROMOTED:
        if governance_grant is None:
            blockers.add(EvidenceBlockerCode.PROMOTION_MISSING)
        else:
            if governance_grant.output_artifact != output_artifact:
                blockers.add(EvidenceBlockerCode.INPUT_HASH_CONFLICT)
            permissions.extend(
                (governance_grant.permission_cap, governance_grant.monitoring_permission_cap)
            )
            valid_until_candidates.extend(
                (
                    governance_grant.promotion_valid_until,
                    governance_grant.monitoring_valid_until,
                )
            )
            lineage.update((governance_grant.promotion_ref, governance_grant.monitoring_ref))
            if governance_grant.promotion_valid_until <= evaluated_at:
                blockers.add(EvidenceBlockerCode.PROMOTION_EXPIRED)
            if governance_grant.monitoring_valid_until <= evaluated_at:
                blockers.add(EvidenceBlockerCode.MONITORING_EXPIRED)
    else:
        blockers.add(EvidenceBlockerCode.OUTPUT_NOT_PROMOTED)

    track_record_ref: ArtifactRef | None = None
    if track_record is None:
        if operator_spec.requires_track_record:
            blockers.add(EvidenceBlockerCode.TRACK_RECORD_MISSING)
    else:
        track_record_ref = track_record.artifact_ref
        lineage.update((track_record.artifact_ref, track_record.promotion_ref))
        lineage.update(track_record.outcome_refs)
        valid_until_candidates.append(track_record.valid_until)
        if track_record.artifact != output_artifact:
            blockers.add(EvidenceBlockerCode.TRACK_RECORD_MISMATCH)
        if track_record.valid_until <= evaluated_at:
            blockers.add(EvidenceBlockerCode.TRACK_RECORD_EXPIRED)
        if track_record.eligible == 0:
            blockers.add(EvidenceBlockerCode.TRACK_RECORD_EMPTY)

    valid_until = min(valid_until_candidates)
    if operator_spec.valid_until <= evaluated_at:
        blockers.add(EvidenceBlockerCode.OPERATOR_EXPIRED)

    permission = _minimum_permission(tuple(permissions))
    if governance_state in (
        GovernanceState.RESEARCH_ONLY,
        GovernanceState.RETIRED,
        GovernanceState.BLOCKED,
    ):
        permission = DecisionPermission.DISPLAY_ONLY
    elif governance_state is GovernanceState.DEGRADED:
        permission = _minimum_permission((permission, DecisionPermission.ADVISORY))
    if blockers:
        permission = DecisionPermission.DISPLAY_ONLY

    ordered_lineage = tuple(sorted(lineage))
    ordered_blockers = tuple(sorted(blockers, key=lambda item: item.value))
    return EvidenceEnvelope(
        output_artifact=output_artifact,
        operator_spec_ref=operator_spec.artifact_ref,
        claim_kind=operator_spec.claim_kind,
        method_kind=operator_spec.method_kind,
        research_family=operator_spec.research_family,
        governance_state=governance_state,
        permission=permission,
        lineage=ordered_lineage,
        dependency_flags=frozenset(dependency_flags),
        track_record_ref=track_record_ref,
        blockers=ordered_blockers,
        evaluated_at=evaluated_at,
        valid_until=valid_until,
        content_hash="",
    )


def build_legacy_unverified_envelope(
    *,
    output_artifact: ArtifactRef,
    claim_kind: ClaimKind,
    method_kind: MethodKind,
    evaluated_at: datetime,
    valid_until: datetime,
) -> EvidenceEnvelope:
    """Wrap an old output without persisting or granting decision authority."""

    _require_aware(evaluated_at, "evaluated_at")
    _require_aware(valid_until, "valid_until")
    if valid_until <= evaluated_at:
        raise ValueError("legacy envelope validity window is invalid")
    spec_payload: dict[str, object] = {
        "output_artifact": output_artifact.to_payload(),
        "mode": "legacy_unverified",
        "evaluated_at": _utc_text(evaluated_at),
        "valid_until": _utc_text(valid_until),
    }
    spec_ref = ArtifactRef(
        owner="research",
        artifact_type="legacy_evidence_adapter",
        artifact_id=output_artifact.artifact_id,
        artifact_version=output_artifact.artifact_version,
        content_hash=_canonical_hash(spec_payload),
    )
    lineage = tuple(sorted((output_artifact, spec_ref)))
    return EvidenceEnvelope(
        output_artifact=output_artifact,
        operator_spec_ref=spec_ref,
        claim_kind=claim_kind,
        method_kind=method_kind,
        research_family="legacy",
        governance_state=GovernanceState.RESEARCH_ONLY,
        permission=DecisionPermission.DISPLAY_ONLY,
        lineage=lineage,
        dependency_flags=frozenset(),
        track_record_ref=None,
        blockers=(EvidenceBlockerCode.LEGACY_UNVERIFIED,),
        evaluated_at=evaluated_at,
        valid_until=valid_until,
        content_hash="",
    )


__all__ = [
    "ArtifactRef",
    "ClaimKind",
    "DecisionPermission",
    "DependencyFlag",
    "EvidenceBlockerCode",
    "EvidenceEnvelope",
    "EvidenceInputBinding",
    "EvidenceOperatorSpec",
    "GovernanceGrant",
    "GovernanceState",
    "MethodKind",
    "MetricDirection",
    "TrackRecordSnapshot",
    "build_legacy_unverified_envelope",
    "resolve_evidence_envelope",
]
