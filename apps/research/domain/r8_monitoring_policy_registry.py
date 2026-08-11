"""Independent Research owner contracts for the R8 monitoring policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from apps.fixed_income.domain.evidence import canonical_hash
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringPolicy,
    GovernedOptimizationMonitoringTarget,
    GovernedOptimizationMonitoringThreshold,
    OptimizationPromotionSelector,
)

POLICY_DEFINITION_VERSION = "research-r8-monitoring-policy-definition.v1"
POLICY_SOURCE_RECEIPT_VERSION = "research-r8-monitoring-policy-source.v1"


def _require_token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _require_hash(value: object, label: str) -> str:
    text = _require_token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _require_aware(value: datetime, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _copy_policy(value: object) -> GovernedOptimizationMonitoringPolicy:
    if type(value) is not GovernedOptimizationMonitoringPolicy:
        raise TypeError("R8 monitoring policy must use the exact Phase A Domain type")
    GovernedOptimizationMonitoringPolicy.__post_init__(value)
    selectors = tuple(
        OptimizationPromotionSelector(
            capability_key=item.capability_key,
            decision_id=item.decision_id,
            decision_content_hash=item.decision_content_hash,
            attestation_hash=item.attestation_hash,
        )
        for item in value.target.upstream_promotions
    )
    target = GovernedOptimizationMonitoringTarget(
        optimization_scope_id=value.target.optimization_scope_id,
        optimization_scope_hash=value.target.optimization_scope_hash,
        result_id=value.target.result_id,
        result_version=value.target.result_version,
        result_hash=value.target.result_hash,
        receipt_id=value.target.receipt_id,
        receipt_version=value.target.receipt_version,
        receipt_hash=value.target.receipt_hash,
        r8_promotion_event_id=value.target.r8_promotion_event_id,
        r8_promotion_event_hash=value.target.r8_promotion_event_hash,
        upstream_promotions=selectors,
        content_hash=value.target.content_hash,
    )
    thresholds = tuple(
        GovernedOptimizationMonitoringThreshold(
            metric_key=item.metric_key,
            unit=item.unit,
            direction=item.direction,
            source_owner=item.source_owner,
            threshold=item.threshold,
            evidence_namespace=item.evidence_namespace,
            content_hash=item.content_hash,
        )
        for item in value.thresholds
    )
    copied = GovernedOptimizationMonitoringPolicy(
        policy_id=value.policy_id,
        policy_scope_id=value.policy_scope_id,
        policy_version=value.policy_version,
        owner=value.owner,
        target=target,
        thresholds=thresholds,
        required_consecutive_breaches=value.required_consecutive_breaches,
        minimum_complete_periods=value.minimum_complete_periods,
        max_period_lag_seconds=value.max_period_lag_seconds,
        max_evidence_delay_seconds=value.max_evidence_delay_seconds,
        calendar_id=value.calendar_id,
        calendar_version=value.calendar_version,
        calendar_hash=value.calendar_hash,
        calendar_recorded_at=value.calendar_recorded_at,
        calendar_first_period_start_at=value.calendar_first_period_start_at,
        recorded_at=value.recorded_at,
        valid_until=value.valid_until,
        content_hash=value.content_hash,
    )
    GovernedOptimizationMonitoringPolicy.__post_init__(copied)
    if copied != value:
        raise ValueError("R8 monitoring policy differs after recursive replay")
    return copied


@dataclass(frozen=True)
class R8MonitoringPolicyDefinition:
    """One complete policy from a dedicated Research definition source."""

    definition_version: str
    policy: GovernedOptimizationMonitoringPolicy
    content_hash: str = field(init=False)

    @classmethod
    def from_policy(
        cls,
        policy: GovernedOptimizationMonitoringPolicy,
    ) -> R8MonitoringPolicyDefinition:
        """Seal an exact policy without consulting any assessment snapshot."""

        return cls(definition_version=POLICY_DEFINITION_VERSION, policy=_copy_policy(policy))

    def __post_init__(self) -> None:
        if self.definition_version != POLICY_DEFINITION_VERSION:
            raise ValueError("R8 monitoring policy definition version is unsupported")
        policy = _copy_policy(self.policy)
        object.__setattr__(
            self,
            "content_hash",
            canonical_hash(
                {
                    "schema": POLICY_DEFINITION_VERSION,
                    "policy_id": policy.policy_id,
                    "policy_version": policy.policy_version,
                    "policy_hash": policy.content_hash,
                }
            ),
        )

    def validated_copy(self) -> R8MonitoringPolicyDefinition:
        """Return a recursively rebuilt exact definition."""

        if type(self) is not R8MonitoringPolicyDefinition:
            raise TypeError("R8 monitoring policy definition type differs")
        copied = R8MonitoringPolicyDefinition.from_policy(_copy_policy(self.policy))
        if copied != self:
            raise ValueError("R8 monitoring policy definition differs after replay")
        return copied


@dataclass(frozen=True)
class R8MonitoringPolicySourceReceipt:
    """Independent Research receipt binding one exact policy definition."""

    source_receipt_id: str
    source_receipt_version: str
    source_owner: str
    policy_id: str
    policy_version: str
    definition_hash: str
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_receipt_id: str,
        source_receipt_version: str,
        policy_id: str,
        policy_version: str,
        definition_hash: str,
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
    ) -> R8MonitoringPolicySourceReceipt:
        """Create a content-addressed source receipt with no policy defaults."""

        values = (
            source_receipt_id,
            source_receipt_version,
            "research",
            policy_id,
            policy_version,
            definition_hash,
            available_at,
            valid_until,
            evidence_ref,
        )
        return cls(*values, _source_hash(*values))

    def __post_init__(self) -> None:
        for label, value in (
            ("source_receipt_id", self.source_receipt_id),
            ("source_receipt_version", self.source_receipt_version),
            ("source_owner", self.source_owner),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("evidence_ref", self.evidence_ref),
        ):
            _require_token(value, f"Research R8 policy source {label}")
        if self.source_receipt_version != POLICY_SOURCE_RECEIPT_VERSION:
            raise ValueError("Research R8 policy source version is unsupported")
        if self.source_owner != "research":
            raise ValueError("R8 monitoring policy source must be Research-owned")
        _require_hash(self.definition_hash, "Research R8 policy source definition_hash")
        _require_hash(self.content_hash, "Research R8 policy source content_hash")
        _require_aware(self.available_at, "Research R8 policy source available_at")
        _require_aware(self.valid_until, "Research R8 policy source valid_until")
        if self.available_at >= self.valid_until:
            raise ValueError("Research R8 policy source validity is empty")
        if self.content_hash != _source_hash(
            self.source_receipt_id,
            self.source_receipt_version,
            self.source_owner,
            self.policy_id,
            self.policy_version,
            self.definition_hash,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
        ):
            raise ValueError("Research R8 policy source hash differs")

    def validated_copy(self) -> R8MonitoringPolicySourceReceipt:
        """Return an exact class-bound reconstruction."""

        if type(self) is not R8MonitoringPolicySourceReceipt:
            raise TypeError("Research R8 policy source type differs")
        copied = R8MonitoringPolicySourceReceipt.create(
            source_receipt_id=self.source_receipt_id,
            source_receipt_version=self.source_receipt_version,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            definition_hash=self.definition_hash,
            available_at=self.available_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
        )
        if copied != self:
            raise ValueError("Research R8 policy source differs after replay")
        return copied


def _source_hash(
    source_receipt_id: str,
    source_receipt_version: str,
    source_owner: str,
    policy_id: str,
    policy_version: str,
    definition_hash: str,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
) -> str:
    return canonical_hash(
        {
            "schema": POLICY_SOURCE_RECEIPT_VERSION,
            "source": (source_receipt_id, source_receipt_version, source_owner),
            "policy": (policy_id, policy_version, definition_hash),
            "window": (available_at, valid_until),
            "evidence_ref": evidence_ref,
        }
    )


__all__ = [
    "POLICY_DEFINITION_VERSION",
    "POLICY_SOURCE_RECEIPT_VERSION",
    "R8MonitoringPolicyDefinition",
    "R8MonitoringPolicySourceReceipt",
]
