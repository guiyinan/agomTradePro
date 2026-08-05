"""Governed data contracts for strategy-research R1/R2 foundations.

The module defines semantic invariants only.  Investor actors, operating
metrics, units, frequencies and sources are supplied as versioned governance
data; no business taxonomy is embedded in Python defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

OPERATING_OBSERVATION_DATASET = "research.operating_observation.v1"
INVESTOR_FLOW_OBSERVATION_DATASET = "research.investor_flow_observation.v1"
ASSET_GROUP_MEMBERSHIP_DATASET = "research.asset_group_membership.v1"


class ObservationValueKind(str, Enum):
    """Mutually exclusive origin of an operating observation."""

    OBSERVED_FACT = "observed_fact"
    HUMAN_ASSUMPTION = "human_assumption"
    MODEL_INFERENCE = "model_inference"


class InvestorFlowMeasureKind(str, Enum):
    """Non-interchangeable measurement semantics for investor-flow data."""

    FUND_FLOW = "fund_flow"
    CAPITAL_BALANCE = "capital_balance"
    HOLDING_CHANGE = "holding_change"
    TRANSACTION_NET_FLOW = "transaction_net_flow"


def _require_text(value: str, field_name: str, *, maximum: int) -> None:
    """Require a bounded, non-blank string."""

    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_token(value: str, field_name: str, *, maximum: int) -> None:
    """Require a compact identifier without whitespace."""

    _require_text(value, field_name, maximum=maximum)
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware datetime."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_interval(
    effective_at: datetime,
    effective_to: datetime | None,
    *,
    prefix: str,
) -> None:
    """Validate an aware half-open effective interval."""

    _require_aware(effective_at, f"{prefix}.effective_at")
    if effective_to is not None:
        _require_aware(effective_to, f"{prefix}.effective_to")
        if effective_to <= effective_at:
            raise ValueError(f"{prefix}.effective_to must follow effective_at")


def _require_finite(value: Decimal, field_name: str) -> None:
    """Reject booleans, non-decimals and non-finite numeric values."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


@dataclass(frozen=True)
class OperatingMetricDefinition:
    """One governed version of an operating metric definition."""

    metric_code: str
    definition_version: int
    name: str
    canonical_unit: str
    frequency: str
    source: str
    effective_at: datetime
    effective_to: datetime | None = None
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "OperatingMetricDefinition.metric_code", maximum=64)
        if isinstance(self.definition_version, bool) or self.definition_version <= 0:
            raise ValueError("OperatingMetricDefinition.definition_version must be positive")
        _require_text(self.name, "OperatingMetricDefinition.name", maximum=160)
        _require_text(
            self.canonical_unit,
            "OperatingMetricDefinition.canonical_unit",
            maximum=40,
        )
        _require_token(self.frequency, "OperatingMetricDefinition.frequency", maximum=40)
        _require_token(self.source, "OperatingMetricDefinition.source", maximum=100)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="OperatingMetricDefinition",
        )
        if not isinstance(self.is_active, bool):
            raise ValueError("OperatingMetricDefinition.is_active must be a boolean")


@dataclass(frozen=True)
class OperatingObservation:
    """A PIT operating value whose fact/assumption/inference origin is explicit."""

    metric_code: str
    definition_version: int
    subject_type: str
    subject_code: str
    effective_at: datetime
    effective_to: datetime | None
    available_at: datetime
    revision_number: int
    value: Decimal
    unit: str
    frequency: str
    source: str
    value_kind: ObservationValueKind
    source_record_id: str = ""
    assumption_set_id: str = ""
    model_version: str = ""

    def __post_init__(self) -> None:
        _require_token(self.metric_code, "OperatingObservation.metric_code", maximum=64)
        if isinstance(self.definition_version, bool) or self.definition_version <= 0:
            raise ValueError("OperatingObservation.definition_version must be positive")
        _require_token(self.subject_type, "OperatingObservation.subject_type", maximum=40)
        _require_token(self.subject_code, "OperatingObservation.subject_code", maximum=80)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="OperatingObservation",
        )
        _require_aware(self.available_at, "OperatingObservation.available_at")
        if isinstance(self.revision_number, bool) or self.revision_number < 0:
            raise ValueError("OperatingObservation.revision_number cannot be negative")
        _require_finite(self.value, "OperatingObservation.value")
        _require_text(self.unit, "OperatingObservation.unit", maximum=40)
        _require_token(self.frequency, "OperatingObservation.frequency", maximum=40)
        _require_token(self.source, "OperatingObservation.source", maximum=100)
        if not isinstance(self.value_kind, ObservationValueKind):
            raise ValueError("OperatingObservation.value_kind is invalid")
        self._validate_lineage()

    def _validate_lineage(self) -> None:
        """Ensure the three value origins cannot share misleading lineage."""

        populated = {
            "source_record_id": bool(self.source_record_id.strip()),
            "assumption_set_id": bool(self.assumption_set_id.strip()),
            "model_version": bool(self.model_version.strip()),
        }
        expected = {
            ObservationValueKind.OBSERVED_FACT: "source_record_id",
            ObservationValueKind.HUMAN_ASSUMPTION: "assumption_set_id",
            ObservationValueKind.MODEL_INFERENCE: "model_version",
        }[self.value_kind]
        if not populated[expected] or sum(populated.values()) != 1:
            raise ValueError(
                "OperatingObservation lineage must match exactly one value_kind origin"
            )
        if self.value_kind is ObservationValueKind.OBSERVED_FACT:
            if self.available_at < self.effective_at:
                raise ValueError("observed fact cannot be available before it is effective")

    @property
    def lineage_ref(self) -> str:
        """Return the single validated lineage reference."""

        return self.source_record_id or self.assumption_set_id or self.model_version


@dataclass(frozen=True)
class InvestorFlowDefinition:
    """Versioned, governed actor/measure/source definition for one flow series."""

    flow_code: str
    definition_version: int
    actor_code: str
    actor_name: str
    measure_kind: InvestorFlowMeasureKind
    canonical_unit: str
    frequency: str
    source: str
    effective_at: datetime
    is_proxy: bool
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""
    effective_to: datetime | None = None
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_token(self.flow_code, "InvestorFlowDefinition.flow_code", maximum=64)
        if isinstance(self.definition_version, bool) or self.definition_version <= 0:
            raise ValueError("InvestorFlowDefinition.definition_version must be positive")
        _require_token(self.actor_code, "InvestorFlowDefinition.actor_code", maximum=64)
        _require_text(self.actor_name, "InvestorFlowDefinition.actor_name", maximum=160)
        if not isinstance(self.measure_kind, InvestorFlowMeasureKind):
            raise ValueError("InvestorFlowDefinition.measure_kind is invalid")
        _require_text(
            self.canonical_unit,
            "InvestorFlowDefinition.canonical_unit",
            maximum=40,
        )
        _require_token(self.frequency, "InvestorFlowDefinition.frequency", maximum=40)
        _require_token(self.source, "InvestorFlowDefinition.source", maximum=100)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="InvestorFlowDefinition",
        )
        if not isinstance(self.is_proxy, bool) or not isinstance(self.is_active, bool):
            raise ValueError("InvestorFlowDefinition boolean fields are invalid")
        if self.is_proxy:
            _require_token(
                self.proxy_target_actor_code,
                "InvestorFlowDefinition.proxy_target_actor_code",
                maximum=64,
            )
            _require_text(
                self.proxy_methodology_ref,
                "InvestorFlowDefinition.proxy_methodology_ref",
                maximum=300,
            )
        elif self.proxy_target_actor_code.strip() or self.proxy_methodology_ref.strip():
            raise ValueError("direct flow definition cannot carry proxy metadata")


@dataclass(frozen=True)
class InvestorFlowObservation:
    """A PIT flow value with explicit measure and proxy semantics."""

    flow_code: str
    definition_version: int
    scope_type: str
    scope_code: str
    effective_at: datetime
    effective_to: datetime | None
    available_at: datetime
    revision_number: int
    value: Decimal
    measure_kind: InvestorFlowMeasureKind
    unit: str
    frequency: str
    source: str
    source_record_id: str
    is_proxy: bool
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""

    def __post_init__(self) -> None:
        _require_token(self.flow_code, "InvestorFlowObservation.flow_code", maximum=64)
        if isinstance(self.definition_version, bool) or self.definition_version <= 0:
            raise ValueError("InvestorFlowObservation.definition_version must be positive")
        _require_token(self.scope_type, "InvestorFlowObservation.scope_type", maximum=40)
        _require_token(self.scope_code, "InvestorFlowObservation.scope_code", maximum=80)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="InvestorFlowObservation",
        )
        _require_aware(self.available_at, "InvestorFlowObservation.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("flow observation cannot be available before it is effective")
        if isinstance(self.revision_number, bool) or self.revision_number < 0:
            raise ValueError("InvestorFlowObservation.revision_number cannot be negative")
        _require_finite(self.value, "InvestorFlowObservation.value")
        if not isinstance(self.measure_kind, InvestorFlowMeasureKind):
            raise ValueError("InvestorFlowObservation.measure_kind is invalid")
        _require_text(self.unit, "InvestorFlowObservation.unit", maximum=40)
        _require_token(self.frequency, "InvestorFlowObservation.frequency", maximum=40)
        _require_token(self.source, "InvestorFlowObservation.source", maximum=100)
        _require_text(
            self.source_record_id,
            "InvestorFlowObservation.source_record_id",
            maximum=255,
        )
        if not isinstance(self.is_proxy, bool):
            raise ValueError("InvestorFlowObservation.is_proxy must be a boolean")
        if self.is_proxy:
            _require_token(
                self.proxy_target_actor_code,
                "InvestorFlowObservation.proxy_target_actor_code",
                maximum=64,
            )
            _require_text(
                self.proxy_methodology_ref,
                "InvestorFlowObservation.proxy_methodology_ref",
                maximum=300,
            )
        elif self.proxy_target_actor_code.strip() or self.proxy_methodology_ref.strip():
            raise ValueError("direct flow observation cannot carry proxy metadata")


@dataclass(frozen=True)
class AssetGroupRevision:
    """One governed revision of a custom asset-group definition."""

    group_code: str
    revision: int
    name: str
    source: str
    effective_at: datetime
    effective_to: datetime | None = None
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_token(self.group_code, "AssetGroupRevision.group_code", maximum=64)
        if isinstance(self.revision, bool) or self.revision <= 0:
            raise ValueError("AssetGroupRevision.revision must be positive")
        _require_text(self.name, "AssetGroupRevision.name", maximum=160)
        _require_token(self.source, "AssetGroupRevision.source", maximum=100)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="AssetGroupRevision",
        )
        if not isinstance(self.is_active, bool):
            raise ValueError("AssetGroupRevision.is_active must be a boolean")


@dataclass(frozen=True)
class PITAssetGroupMembership:
    """Append-only asset membership with effective and knowledge-time clocks."""

    group_code: str
    group_revision: int
    asset_code: str
    effective_at: datetime
    effective_to: datetime | None
    available_at: datetime
    revision_number: int
    source: str
    source_record_id: str

    def __post_init__(self) -> None:
        _require_token(self.group_code, "PITAssetGroupMembership.group_code", maximum=64)
        if isinstance(self.group_revision, bool) or self.group_revision <= 0:
            raise ValueError("PITAssetGroupMembership.group_revision must be positive")
        _require_token(self.asset_code, "PITAssetGroupMembership.asset_code", maximum=40)
        _require_interval(
            self.effective_at,
            self.effective_to,
            prefix="PITAssetGroupMembership",
        )
        _require_aware(self.available_at, "PITAssetGroupMembership.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("membership cannot be available before it is effective")
        if isinstance(self.revision_number, bool) or self.revision_number < 0:
            raise ValueError("PITAssetGroupMembership.revision_number cannot be negative")
        _require_token(self.source, "PITAssetGroupMembership.source", maximum=100)
        _require_text(
            self.source_record_id,
            "PITAssetGroupMembership.source_record_id",
            maximum=255,
        )


def validate_operating_observation(
    definition: OperatingMetricDefinition,
    observation: OperatingObservation,
) -> None:
    """Reject an observation that drifts from its governed metric version."""

    actual = (
        observation.metric_code,
        observation.definition_version,
        observation.unit,
        observation.frequency,
        observation.source,
    )
    expected = (
        definition.metric_code,
        definition.definition_version,
        definition.canonical_unit,
        definition.frequency,
        definition.source,
    )
    if actual != expected:
        raise ValueError("operating observation conflicts with its governed definition")
    if not definition.is_active:
        raise ValueError("operating metric definition is inactive")
    if observation.effective_at < definition.effective_at or (
        definition.effective_to is not None and observation.effective_at >= definition.effective_to
    ):
        raise ValueError("operating observation falls outside the definition interval")


def validate_investor_flow_observation(
    definition: InvestorFlowDefinition,
    observation: InvestorFlowObservation,
) -> None:
    """Reject measure, unit, source or proxy drift from a flow definition."""

    actual = (
        observation.flow_code,
        observation.definition_version,
        observation.measure_kind,
        observation.unit,
        observation.frequency,
        observation.source,
        observation.is_proxy,
        observation.proxy_target_actor_code,
        observation.proxy_methodology_ref,
    )
    expected = (
        definition.flow_code,
        definition.definition_version,
        definition.measure_kind,
        definition.canonical_unit,
        definition.frequency,
        definition.source,
        definition.is_proxy,
        definition.proxy_target_actor_code,
        definition.proxy_methodology_ref,
    )
    if actual != expected:
        raise ValueError("investor-flow observation conflicts with its governed definition")
    if not definition.is_active:
        raise ValueError("investor-flow definition is inactive")
    if observation.effective_at < definition.effective_at or (
        definition.effective_to is not None and observation.effective_at >= definition.effective_to
    ):
        raise ValueError("investor-flow observation falls outside the definition interval")


def validate_asset_group_membership(
    definition: AssetGroupRevision,
    membership: PITAssetGroupMembership,
) -> None:
    """Reject membership rows that drift from their governed group revision."""

    if (
        membership.group_code != definition.group_code
        or membership.group_revision != definition.revision
        or membership.source != definition.source
    ):
        raise ValueError("asset-group membership conflicts with its governed revision")
    if not definition.is_active:
        raise ValueError("asset-group revision is inactive")
    if membership.effective_at < definition.effective_at or (
        definition.effective_to is not None and membership.effective_at >= definition.effective_to
    ):
        raise ValueError("asset-group membership falls outside the revision interval")


__all__ = [
    "ASSET_GROUP_MEMBERSHIP_DATASET",
    "INVESTOR_FLOW_OBSERVATION_DATASET",
    "OPERATING_OBSERVATION_DATASET",
    "AssetGroupRevision",
    "InvestorFlowDefinition",
    "InvestorFlowMeasureKind",
    "InvestorFlowObservation",
    "ObservationValueKind",
    "OperatingMetricDefinition",
    "OperatingObservation",
    "PITAssetGroupMembership",
    "validate_asset_group_membership",
    "validate_investor_flow_observation",
    "validate_operating_observation",
]
