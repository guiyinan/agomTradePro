"""Pure contracts and aggregation rules for R2 market-structure research.

The module intentionally contains no investor catalog, asset list, data source,
or empirical threshold.  Those inputs are versioned governance data supplied
by callers.  Outputs remain descriptive, research-only evidence and can never
be promoted to an execution or decision instruction by this bounded context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations

from apps.data_center.domain.market_structure_governance import (
    MARKET_STRUCTURE_CALENDAR_DATASET,
    MARKET_STRUCTURE_TAXONOMY_DATASET,
    MEASURE_KIND_BY_CONCEPT,
    EmpiricalPercentileMethod,
    InvestorActorDefinition,
    MarketStructureGovernanceArtifactKind,
    MarketStructureMeasureConcept,
    MarketStructurePublicationAttestation,
    MarketStructureResearchStatus,
    VersionedEvidenceReference,
    _canonical_hash,
    _require_aware,
    _require_finite,
    _require_interval,
    _require_text,
    _require_token,
    _utc_iso,
    market_structure_publication_attestation_hash,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.domain.research_data_foundation import (
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
)


@dataclass(frozen=True)
class MarketStructureSeriesDefinition:
    """Research-eligible semantic overlay for one canonical PIT flow series."""

    series_code: str
    series_version: int
    flow_code: str
    flow_definition_version: int
    taxonomy_code: str
    taxonomy_version: int
    actor_code: str
    measure_concept: MarketStructureMeasureConcept
    measure_kind: InvestorFlowMeasureKind
    canonical_unit: str
    frequency: str
    source: str
    revision_policy_ref: str
    effective_at: datetime
    is_proxy: bool
    available_at: datetime
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""
    effective_to: datetime | None = None
    expires_at: datetime | None = None
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.series_code, "series_code"),
            (self.flow_code, "flow_code"),
            (self.taxonomy_code, "taxonomy_code"),
            (self.actor_code, "actor_code"),
        ):
            _require_token(
                value,
                f"MarketStructureSeriesDefinition.{field_name}",
                maximum=64,
            )
        for version_value, field_name in (
            (self.series_version, "series_version"),
            (self.flow_definition_version, "flow_definition_version"),
            (self.taxonomy_version, "taxonomy_version"),
        ):
            if isinstance(version_value, bool) or version_value <= 0:
                raise ValueError(f"MarketStructureSeriesDefinition.{field_name} must be positive")
        if not isinstance(self.measure_concept, MarketStructureMeasureConcept):
            raise ValueError("MarketStructureSeriesDefinition.measure_concept is invalid")
        if not isinstance(self.measure_kind, InvestorFlowMeasureKind):
            raise ValueError("MarketStructureSeriesDefinition.measure_kind is invalid")
        if MEASURE_KIND_BY_CONCEPT[self.measure_concept] is not self.measure_kind:
            raise ValueError("measure concept and measure kind are not interchangeable")
        _require_text(
            self.canonical_unit,
            "MarketStructureSeriesDefinition.canonical_unit",
            maximum=40,
        )
        _require_token(
            self.frequency,
            "MarketStructureSeriesDefinition.frequency",
            maximum=40,
        )
        _require_token(
            self.source,
            "MarketStructureSeriesDefinition.source",
            maximum=100,
        )
        _require_text(
            self.revision_policy_ref,
            "MarketStructureSeriesDefinition.revision_policy_ref",
            maximum=300,
        )
        _require_interval(
            self.effective_at,
            self.effective_to,
            field_name="MarketStructureSeriesDefinition",
        )
        _require_aware(self.available_at, "MarketStructureSeriesDefinition.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("market-structure series cannot be available before effective_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "MarketStructureSeriesDefinition.expires_at")
            if self.expires_at <= self.available_at:
                raise ValueError("market-structure series expires_at must follow available_at")
        if not isinstance(self.is_proxy, bool) or not isinstance(self.is_active, bool):
            raise ValueError("MarketStructureSeriesDefinition boolean fields are invalid")
        if self.is_proxy:
            _require_token(
                self.proxy_target_actor_code,
                "MarketStructureSeriesDefinition.proxy_target_actor_code",
                maximum=64,
            )
            _require_text(
                self.proxy_methodology_ref,
                "MarketStructureSeriesDefinition.proxy_methodology_ref",
                maximum=300,
            )
        elif self.proxy_target_actor_code or self.proxy_methodology_ref:
            raise ValueError("direct market-structure series cannot carry proxy metadata")

    def to_payload(self) -> dict[str, object]:
        """Return all version-bound series semantics for evidence hashing."""

        return {
            "actor_code": self.actor_code,
            "available_at": _utc_iso(self.available_at),
            "canonical_unit": self.canonical_unit,
            "description": self.description,
            "effective_at": _utc_iso(self.effective_at),
            "effective_to": _utc_iso(self.effective_to),
            "expires_at": _utc_iso(self.expires_at),
            "flow_code": self.flow_code,
            "flow_definition_version": self.flow_definition_version,
            "frequency": self.frequency,
            "is_active": self.is_active,
            "is_proxy": self.is_proxy,
            "measure_concept": self.measure_concept.value,
            "measure_kind": self.measure_kind.value,
            "proxy_methodology_ref": self.proxy_methodology_ref,
            "proxy_target_actor_code": self.proxy_target_actor_code,
            "revision_policy_ref": self.revision_policy_ref,
            "series_code": self.series_code,
            "series_version": self.series_version,
            "source": self.source,
            "taxonomy_code": self.taxonomy_code,
            "taxonomy_version": self.taxonomy_version,
        }

    @property
    def definition_hash(self) -> str:
        """Return the stable content hash of this research series version."""

        return _canonical_hash(self.to_payload())


def validate_series_against_flow_definition(
    series: MarketStructureSeriesDefinition,
    flow: InvestorFlowDefinition,
) -> None:
    """Reject a research overlay that relabels its canonical flow definition."""

    actual = (
        series.flow_code,
        series.flow_definition_version,
        series.actor_code,
        series.measure_kind,
        series.canonical_unit,
        series.frequency,
        series.source,
        series.is_proxy,
        series.proxy_target_actor_code,
        series.proxy_methodology_ref,
    )
    expected = (
        flow.flow_code,
        flow.definition_version,
        flow.actor_code,
        flow.measure_kind,
        flow.canonical_unit,
        flow.frequency,
        flow.source,
        flow.is_proxy,
        flow.proxy_target_actor_code,
        flow.proxy_methodology_ref,
    )
    if actual != expected:
        raise ValueError("market-structure series conflicts with canonical flow definition")
    if not flow.is_active or not series.is_active:
        raise ValueError("market-structure series definitions must be active")
    if series.effective_at < flow.effective_at or (
        flow.effective_to is not None and series.effective_at >= flow.effective_to
    ):
        raise ValueError("market-structure series falls outside flow definition interval")


@dataclass(frozen=True)
class MarketStructureSeriesRef:
    """Exact series version selected for one research run."""

    series_code: str
    series_version: int

    def __post_init__(self) -> None:
        _require_token(
            self.series_code,
            "MarketStructureSeriesRef.series_code",
            maximum=64,
        )
        if isinstance(self.series_version, bool) or self.series_version <= 0:
            raise ValueError("MarketStructureSeriesRef.series_version must be positive")

    def to_payload(self) -> dict[str, object]:
        """Return this exact version reference as a stable payload."""

        return {
            "series_code": self.series_code,
            "series_version": self.series_version,
        }


@dataclass(frozen=True)
class MarketStructurePeriodCalendar:
    """Caller-governed exact period schedule for one R2 research horizon."""

    calendar_code: str
    calendar_version: int
    frequency: str
    source: str
    revision_policy_ref: str
    available_at: datetime
    periods: tuple[datetime, ...]
    expires_at: datetime | None = None
    description: str = ""
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_token(
            self.calendar_code,
            "MarketStructurePeriodCalendar.calendar_code",
            maximum=64,
        )
        if isinstance(self.calendar_version, bool) or self.calendar_version <= 0:
            raise ValueError("MarketStructurePeriodCalendar.calendar_version must be positive")
        _require_token(
            self.frequency,
            "MarketStructurePeriodCalendar.frequency",
            maximum=40,
        )
        _require_token(
            self.source,
            "MarketStructurePeriodCalendar.source",
            maximum=100,
        )
        _require_text(
            self.revision_policy_ref,
            "MarketStructurePeriodCalendar.revision_policy_ref",
            maximum=300,
        )
        _require_aware(
            self.available_at,
            "MarketStructurePeriodCalendar.available_at",
        )
        if self.expires_at is not None:
            _require_aware(
                self.expires_at,
                "MarketStructurePeriodCalendar.expires_at",
            )
            if self.expires_at <= self.available_at:
                raise ValueError("period calendar expires_at must follow available_at")
        if not self.periods:
            raise ValueError("MarketStructurePeriodCalendar.periods cannot be empty")
        for period in self.periods:
            _require_aware(period, "MarketStructurePeriodCalendar.period")
        canonical_periods = tuple(sorted(self.periods))
        if canonical_periods != self.periods or len(set(self.periods)) != len(self.periods):
            raise ValueError("period calendar periods must be unique and strictly increasing")
        if not isinstance(self.is_active, bool):
            raise ValueError("MarketStructurePeriodCalendar.is_active must be a boolean")

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable period schedule for evidence sealing."""

        return {
            "available_at": _utc_iso(self.available_at),
            "calendar_code": self.calendar_code,
            "calendar_version": self.calendar_version,
            "description": self.description,
            "expires_at": _utc_iso(self.expires_at),
            "frequency": self.frequency,
            "is_active": self.is_active,
            "periods": [_utc_iso(period) for period in self.periods],
            "revision_policy_ref": self.revision_policy_ref,
            "source": self.source,
        }

    @property
    def calendar_hash(self) -> str:
        """Return the stable hash of the exact governed schedule."""

        return _canonical_hash(self.to_payload())


@dataclass(frozen=True)
class MarketStructurePeriodCalendarRef:
    """Exact period-calendar version selected for one research run."""

    calendar_code: str
    calendar_version: int

    def __post_init__(self) -> None:
        _require_token(
            self.calendar_code,
            "MarketStructurePeriodCalendarRef.calendar_code",
            maximum=64,
        )
        if isinstance(self.calendar_version, bool) or self.calendar_version <= 0:
            raise ValueError("MarketStructurePeriodCalendarRef.calendar_version must be positive")

    def to_payload(self) -> dict[str, object]:
        """Return this exact calendar reference as a stable payload."""

        return {
            "calendar_code": self.calendar_code,
            "calendar_version": self.calendar_version,
        }


@dataclass(frozen=True)
class MarketStructureAggregationPolicy:
    """Caller-governed thresholds and methodology for descriptive aggregation."""

    policy_code: str
    policy_version: int
    minimum_history_observations: int
    minimum_actor_count: int
    minimum_membership_coverage_ratio: Decimal
    percentile_method: EmpiricalPercentileMethod

    def __post_init__(self) -> None:
        _require_token(
            self.policy_code,
            "MarketStructureAggregationPolicy.policy_code",
            maximum=64,
        )
        if isinstance(self.policy_version, bool) or self.policy_version <= 0:
            raise ValueError("MarketStructureAggregationPolicy.policy_version must be positive")
        if (
            isinstance(self.minimum_history_observations, bool)
            or self.minimum_history_observations < 3
        ):
            raise ValueError("minimum_history_observations must support change and acceleration")
        if isinstance(self.minimum_actor_count, bool) or self.minimum_actor_count < 2:
            raise ValueError("minimum_actor_count must support cross-actor differences")
        _require_finite(
            self.minimum_membership_coverage_ratio,
            "minimum_membership_coverage_ratio",
        )
        if not Decimal("0") <= self.minimum_membership_coverage_ratio <= Decimal("1"):
            raise ValueError("minimum_membership_coverage_ratio must be within [0, 1]")
        if not isinstance(self.percentile_method, EmpiricalPercentileMethod):
            raise ValueError("percentile_method is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the explicit policy payload without hidden defaults."""

        return {
            "minimum_actor_count": self.minimum_actor_count,
            "minimum_history_observations": self.minimum_history_observations,
            "minimum_membership_coverage_ratio": str(self.minimum_membership_coverage_ratio),
            "percentile_method": self.percentile_method.value,
            "policy_code": self.policy_code,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class MarketStructureResearchRequest:
    """Versioned and PIT-bound request for one R2 descriptive research run."""

    evidence_key: str
    evidence_version: int
    as_of_time: datetime
    knowledge_scope: KnowledgeScope
    group_code: str
    group_revision: int
    period_calendar: MarketStructurePeriodCalendarRef
    method_version: str
    series: tuple[MarketStructureSeriesRef, ...]
    policy: MarketStructureAggregationPolicy

    def __post_init__(self) -> None:
        _require_token(
            self.evidence_key,
            "MarketStructureResearchRequest.evidence_key",
            maximum=128,
        )
        if isinstance(self.evidence_version, bool) or self.evidence_version <= 0:
            raise ValueError("MarketStructureResearchRequest.evidence_version must be positive")
        _require_aware(self.as_of_time, "MarketStructureResearchRequest.as_of_time")
        if not isinstance(self.knowledge_scope, KnowledgeScope):
            raise ValueError("MarketStructureResearchRequest.knowledge_scope is invalid")
        _require_token(
            self.group_code,
            "MarketStructureResearchRequest.group_code",
            maximum=64,
        )
        if isinstance(self.group_revision, bool) or self.group_revision <= 0:
            raise ValueError("MarketStructureResearchRequest.group_revision must be positive")
        if not isinstance(self.period_calendar, MarketStructurePeriodCalendarRef):
            raise ValueError("MarketStructureResearchRequest.period_calendar is invalid")
        _require_token(
            self.method_version,
            "MarketStructureResearchRequest.method_version",
            maximum=64,
        )
        if not self.series:
            raise ValueError("MarketStructureResearchRequest.series cannot be empty")
        identities = {(item.series_code, item.series_version) for item in self.series}
        if len(identities) != len(self.series):
            raise ValueError("MarketStructureResearchRequest.series cannot contain duplicates")

    def to_payload(self) -> dict[str, object]:
        """Return the versioned research request as canonical evidence input."""

        return {
            "as_of_time": _utc_iso(self.as_of_time),
            "evidence_key": self.evidence_key,
            "evidence_version": self.evidence_version,
            "group_code": self.group_code,
            "group_revision": self.group_revision,
            "knowledge_scope": self.knowledge_scope.value,
            "method_version": self.method_version,
            "period_calendar": self.period_calendar.to_payload(),
            "policy": self.policy.to_payload(),
            "series": [item.to_payload() for item in self.series],
        }


@dataclass(frozen=True)
class MarketStructureObservation:
    """One verified asset-level observation normalized from canonical PIT data."""

    series_code: str
    series_version: int
    actor_code: str
    asset_code: str
    measure_concept: MarketStructureMeasureConcept
    effective_at: datetime
    available_at: datetime
    value: Decimal
    unit: str
    frequency: str
    source: str
    revision_number: int
    is_proxy: bool
    evidence: VersionedEvidenceReference
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""

    def __post_init__(self) -> None:
        for value, field_name, maximum in (
            (self.series_code, "series_code", 64),
            (self.actor_code, "actor_code", 64),
            (self.asset_code, "asset_code", 40),
            (self.frequency, "frequency", 40),
            (self.source, "source", 100),
        ):
            _require_token(
                value,
                f"MarketStructureObservation.{field_name}",
                maximum=maximum,
            )
        if isinstance(self.series_version, bool) or self.series_version <= 0:
            raise ValueError("MarketStructureObservation.series_version must be positive")
        if not isinstance(self.measure_concept, MarketStructureMeasureConcept):
            raise ValueError("MarketStructureObservation.measure_concept is invalid")
        _require_aware(self.effective_at, "MarketStructureObservation.effective_at")
        _require_aware(self.available_at, "MarketStructureObservation.available_at")
        if self.available_at < self.effective_at:
            raise ValueError("market-structure observation cannot exist before effective_at")
        _require_finite(self.value, "MarketStructureObservation.value")
        _require_text(self.unit, "MarketStructureObservation.unit", maximum=40)
        if isinstance(self.revision_number, bool) or self.revision_number < 0:
            raise ValueError("MarketStructureObservation.revision_number cannot be negative")
        if not isinstance(self.is_proxy, bool):
            raise ValueError("MarketStructureObservation.is_proxy must be a boolean")
        if self.is_proxy:
            _require_token(
                self.proxy_target_actor_code,
                "MarketStructureObservation.proxy_target_actor_code",
                maximum=64,
            )
            _require_text(
                self.proxy_methodology_ref,
                "MarketStructureObservation.proxy_methodology_ref",
                maximum=300,
            )
        elif self.proxy_target_actor_code or self.proxy_methodology_ref:
            raise ValueError("direct observation cannot carry proxy metadata")


@dataclass(frozen=True)
class PITMembershipSnapshot:
    """Asset-group members effective at one event time and knowable by one clock."""

    group_code: str
    group_revision: int
    effective_at: datetime
    knowledge_at: datetime
    asset_codes: tuple[str, ...]
    evidence: tuple[VersionedEvidenceReference, ...]

    def __post_init__(self) -> None:
        _require_token(self.group_code, "PITMembershipSnapshot.group_code", maximum=64)
        if isinstance(self.group_revision, bool) or self.group_revision <= 0:
            raise ValueError("PITMembershipSnapshot.group_revision must be positive")
        _require_aware(self.effective_at, "PITMembershipSnapshot.effective_at")
        _require_aware(self.knowledge_at, "PITMembershipSnapshot.knowledge_at")
        if self.knowledge_at < self.effective_at:
            raise ValueError("membership knowledge_at cannot precede effective_at")
        if len(set(self.asset_codes)) != len(self.asset_codes):
            raise ValueError("PITMembershipSnapshot.asset_codes cannot contain duplicates")
        if len(self.asset_codes) != len(self.evidence):
            raise ValueError("each PIT membership requires exact immutable evidence")
        for asset_code in self.asset_codes:
            _require_token(asset_code, "PITMembershipSnapshot.asset_code", maximum=40)


@dataclass(frozen=True)
class SeriesPeriodCoverage:
    """Frozen expected/observed/missing PIT membership for one series-period."""

    series_code: str
    series_version: int
    effective_at: datetime
    expected_asset_codes: tuple[str, ...]
    observed_asset_codes: tuple[str, ...]
    missing_asset_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_token(self.series_code, "SeriesPeriodCoverage.series_code", maximum=64)
        if isinstance(self.series_version, bool) or self.series_version <= 0:
            raise ValueError("SeriesPeriodCoverage.series_version must be positive")
        _require_aware(self.effective_at, "SeriesPeriodCoverage.effective_at")
        expected = set(self.expected_asset_codes)
        observed = set(self.observed_asset_codes)
        missing = set(self.missing_asset_codes)
        if len(expected) != len(self.expected_asset_codes):
            raise ValueError("coverage expected assets cannot contain duplicates")
        if len(observed) != len(self.observed_asset_codes):
            raise ValueError("coverage observed assets cannot contain duplicates")
        if len(missing) != len(self.missing_asset_codes):
            raise ValueError("coverage missing assets cannot contain duplicates")
        if not observed.issubset(expected) or missing != expected - observed:
            raise ValueError("coverage observed/missing partition conflicts with expected assets")

    @property
    def coverage_ratio(self) -> Decimal:
        """Return exact observed membership coverage, or zero for no expected members."""

        if not self.expected_asset_codes:
            return Decimal("0")
        return Decimal(len(self.observed_asset_codes)) / Decimal(len(self.expected_asset_codes))

    def to_payload(self) -> dict[str, object]:
        """Return canonical coverage evidence for sealing."""

        return {
            "coverage_ratio": str(self.coverage_ratio),
            "effective_at": _utc_iso(self.effective_at),
            "expected_asset_codes": list(self.expected_asset_codes),
            "expected_count": len(self.expected_asset_codes),
            "missing_asset_codes": list(self.missing_asset_codes),
            "missing_count": len(self.missing_asset_codes),
            "observed_asset_codes": list(self.observed_asset_codes),
            "observed_count": len(self.observed_asset_codes),
            "series_code": self.series_code,
            "series_version": self.series_version,
        }


@dataclass(frozen=True)
class ActorStructureMetrics:
    """Total, dynamics and percentile for one comparable investor actor."""

    actor_code: str
    series_code: str
    measure_concept: MarketStructureMeasureConcept
    unit: str
    frequency: str
    source: str
    revision_policy_ref: str
    latest_effective_at: datetime
    history_count: int
    total: Decimal
    change: Decimal
    acceleration: Decimal
    historical_percentile: Decimal
    is_proxy: bool
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""

    def to_payload(self) -> dict[str, object]:
        """Return stable descriptive metrics with explicit proxy semantics."""

        return {
            "acceleration": str(self.acceleration),
            "actor_code": self.actor_code,
            "change": str(self.change),
            "frequency": self.frequency,
            "historical_percentile": str(self.historical_percentile),
            "history_count": self.history_count,
            "is_proxy": self.is_proxy,
            "latest_effective_at": _utc_iso(self.latest_effective_at),
            "measure_concept": self.measure_concept.value,
            "proxy_methodology_ref": self.proxy_methodology_ref,
            "proxy_target_actor_code": self.proxy_target_actor_code,
            "revision_policy_ref": self.revision_policy_ref,
            "series_code": self.series_code,
            "source": self.source,
            "total": str(self.total),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class CrossActorDifference:
    """Pairwise descriptive difference between comparable actor aggregates."""

    left_actor_code: str
    right_actor_code: str
    total_difference: Decimal
    change_difference: Decimal
    acceleration_difference: Decimal
    percentile_difference: Decimal

    def to_payload(self) -> dict[str, object]:
        """Return stable pairwise descriptive differences."""

        return {
            "acceleration_difference": str(self.acceleration_difference),
            "change_difference": str(self.change_difference),
            "left_actor_code": self.left_actor_code,
            "percentile_difference": str(self.percentile_difference),
            "right_actor_code": self.right_actor_code,
            "total_difference": str(self.total_difference),
        }


@dataclass(frozen=True)
class MarketStructureSnapshot:
    """Fail-closed, descriptive-only aggregate returned by the R2 domain."""

    status: MarketStructureResearchStatus
    as_of_time: datetime
    method_version: str
    actor_metrics: tuple[ActorStructureMetrics, ...]
    cross_actor_differences: tuple[CrossActorDifference, ...]
    blocked_reasons: tuple[str, ...]
    contains_proxy: bool
    coverage: tuple[SeriesPeriodCoverage, ...]
    deterministic_conclusion: None = None
    interpretation_scope: str = "structure_description_only"
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_aware(self.as_of_time, "MarketStructureSnapshot.as_of_time")
        _require_token(self.method_version, "MarketStructureSnapshot.method_version", maximum=64)
        if (
            not self.research_only
            or not self.must_not_use_for_decision
            or not self.must_not_execute
        ):
            raise ValueError("market-structure output must remain research-only")
        if self.deterministic_conclusion is not None:
            raise ValueError("market-structure research cannot publish a conclusion")
        if self.interpretation_scope != "structure_description_only":
            raise ValueError("market-structure output scope must remain descriptive")
        if self.status is MarketStructureResearchStatus.BLOCKED:
            if not self.blocked_reasons:
                raise ValueError("blocked market-structure output requires reasons")
            if self.actor_metrics or self.cross_actor_differences:
                raise ValueError("blocked market-structure output cannot publish aggregates")
        elif self.blocked_reasons:
            raise ValueError("available market-structure output cannot contain blockers")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical descriptive output used by evidence hashes."""

        return {
            "actor_metrics": [item.to_payload() for item in self.actor_metrics],
            "as_of_time": _utc_iso(self.as_of_time),
            "blocked_reasons": list(self.blocked_reasons),
            "contains_proxy": self.contains_proxy,
            "coverage": [item.to_payload() for item in self.coverage],
            "cross_actor_differences": [item.to_payload() for item in self.cross_actor_differences],
            "deterministic_conclusion": None,
            "interpretation_scope": self.interpretation_scope,
            "method_version": self.method_version,
            "must_not_execute": self.must_not_execute,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "research_only": self.research_only,
            "status": self.status.value,
        }


def _blocked_snapshot(
    *,
    request: MarketStructureResearchRequest,
    blockers: set[str],
    contains_proxy: bool,
    coverage: tuple[SeriesPeriodCoverage, ...],
) -> MarketStructureSnapshot:
    """Build a canonical fail-closed snapshot from stable blocker codes."""

    return MarketStructureSnapshot(
        status=MarketStructureResearchStatus.BLOCKED,
        as_of_time=request.as_of_time,
        method_version=request.method_version,
        actor_metrics=(),
        cross_actor_differences=(),
        blocked_reasons=tuple(sorted(blockers)),
        contains_proxy=contains_proxy,
        coverage=coverage,
    )


def aggregate_market_structure(
    *,
    request: MarketStructureResearchRequest,
    period_calendar: MarketStructurePeriodCalendar | None,
    definitions: tuple[MarketStructureSeriesDefinition, ...],
    observations: tuple[MarketStructureObservation, ...],
    external_blockers: tuple[str, ...] = (),
    coverage: tuple[SeriesPeriodCoverage, ...] = (),
) -> MarketStructureSnapshot:
    """Calculate comparable descriptive metrics or fail closed on any gap."""

    blockers = {reason for reason in external_blockers if reason.strip()}
    contains_proxy = any(definition.is_proxy for definition in definitions)
    calendar_periods: set[datetime] = set()
    if period_calendar is None:
        blockers.add("period_calendar_missing")
    else:
        selected_calendar = (
            period_calendar.calendar_code,
            period_calendar.calendar_version,
        )
        requested_calendar = (
            request.period_calendar.calendar_code,
            request.period_calendar.calendar_version,
        )
        if selected_calendar != requested_calendar:
            blockers.add("period_calendar_identity_mismatch")
        if (
            not period_calendar.is_active
            or period_calendar.available_at > request.as_of_time
            or (
                period_calendar.expires_at is not None
                and period_calendar.expires_at <= request.as_of_time
            )
        ):
            blockers.add("period_calendar_unavailable")
        calendar_periods = set(period_calendar.periods)
        for effective_at in period_calendar.periods:
            if effective_at > request.as_of_time:
                blockers.add(
                    "period_calendar_future_period:" f"{effective_at.astimezone(UTC).isoformat()}"
                )
        if len(period_calendar.periods) < request.policy.minimum_history_observations:
            blockers.add("period_calendar_history_insufficient")
    definitions_by_identity = {
        (definition.series_code, definition.series_version): definition
        for definition in definitions
    }
    if len(definitions_by_identity) != len(definitions):
        blockers.add("series_definition_duplicate")
    expected_identities = {
        (reference.series_code, reference.series_version) for reference in request.series
    }
    if set(definitions_by_identity) != expected_identities:
        blockers.add("series_definition_missing")
    actor_codes = [definition.actor_code for definition in definitions]
    if len(actor_codes) != len(set(actor_codes)):
        blockers.add("actor_series_ambiguous")
    if len(actor_codes) < request.policy.minimum_actor_count:
        blockers.add("actor_coverage_insufficient")
    if period_calendar is not None and any(
        definition.frequency != period_calendar.frequency for definition in definitions
    ):
        blockers.add("period_calendar_frequency_mismatch")
    coverage_identities = {
        (item.series_code, item.series_version, item.effective_at) for item in coverage
    }
    if len(coverage_identities) != len(coverage):
        blockers.add("membership_coverage_duplicate")
    expected_coverage_identities = {
        (reference.series_code, reference.series_version, effective_at)
        for reference in request.series
        for effective_at in calendar_periods
    }
    if coverage_identities != expected_coverage_identities:
        blockers.add("membership_coverage_incomplete")
    coverage_by_identity = {
        (item.series_code, item.series_version, item.effective_at): item for item in coverage
    }
    observation_assets_by_identity: dict[tuple[str, int, datetime], set[str]] = {}
    observation_counts_by_asset: dict[tuple[str, int, datetime, str], int] = {}
    for observation in observations:
        identity = (
            observation.series_code,
            observation.series_version,
            observation.effective_at,
        )
        if identity not in expected_coverage_identities:
            continue
        observation_assets_by_identity.setdefault(identity, set()).add(observation.asset_code)
        asset_identity = (*identity, observation.asset_code)
        observation_counts_by_asset[asset_identity] = (
            observation_counts_by_asset.get(asset_identity, 0) + 1
        )
    if any(count > 1 for count in observation_counts_by_asset.values()):
        blockers.add("observation_asset_duplicate")
    for item in coverage:
        identity = (item.series_code, item.series_version, item.effective_at)
        observed_assets = observation_assets_by_identity.get(identity, set())
        if observed_assets != set(item.observed_asset_codes):
            blockers.add("membership_coverage_observation_mismatch")
        if not observed_assets.issubset(set(item.expected_asset_codes)):
            blockers.add("observation_outside_membership")
        if item.coverage_ratio < request.policy.minimum_membership_coverage_ratio:
            blockers.add(
                "membership_coverage_insufficient:"
                f"{item.series_code}:v{item.series_version}:"
                f"{item.effective_at.astimezone(UTC).isoformat()}"
            )
    for effective_at in sorted(calendar_periods):
        if not any(
            observation_assets_by_identity.get(
                (reference.series_code, reference.series_version, effective_at),
                set(),
            )
            for reference in request.series
        ):
            blockers.add("period_all_series_missing:" f"{effective_at.astimezone(UTC).isoformat()}")

    concepts = {definition.measure_concept for definition in definitions}
    units = {definition.canonical_unit for definition in definitions}
    frequencies = {definition.frequency for definition in definitions}
    if len(concepts) > 1:
        blockers.add("measure_concept_not_comparable")
    if len(units) > 1:
        blockers.add("unit_not_comparable")
    if len(frequencies) > 1:
        blockers.add("frequency_not_comparable")

    values: dict[str, dict[datetime, Decimal]] = {
        definition.actor_code: {} for definition in definitions
    }
    for observation in observations:
        coverage_identity = (
            observation.series_code,
            observation.series_version,
            observation.effective_at,
        )
        if coverage_identity not in expected_coverage_identities:
            continue
        series_identity = (observation.series_code, observation.series_version)
        definition = definitions_by_identity.get(series_identity)
        if definition is None:
            blockers.add("observation_series_unknown")
            continue
        if observation.effective_at > request.as_of_time:
            blockers.add("observation_from_future")
            continue
        if observation.available_at > request.as_of_time:
            blockers.add("observation_not_knowable")
            continue
        semantic_actual = (
            observation.actor_code,
            observation.measure_concept,
            observation.unit,
            observation.frequency,
            observation.source,
            observation.is_proxy,
            observation.proxy_target_actor_code,
            observation.proxy_methodology_ref,
        )
        semantic_expected = (
            definition.actor_code,
            definition.measure_concept,
            definition.canonical_unit,
            definition.frequency,
            definition.source,
            definition.is_proxy,
            definition.proxy_target_actor_code,
            definition.proxy_methodology_ref,
        )
        if semantic_actual != semantic_expected:
            blockers.add("observation_semantics_mismatch")
            continue
        selected_coverage = coverage_by_identity.get(coverage_identity)
        if selected_coverage is None or observation.asset_code not in set(
            selected_coverage.expected_asset_codes
        ):
            continue
        actor_values = values[definition.actor_code]
        actor_values[observation.effective_at] = (
            actor_values.get(observation.effective_at, Decimal("0")) + observation.value
        )

    for definition in definitions:
        if len(values[definition.actor_code]) < request.policy.minimum_history_observations:
            blockers.add(f"history_insufficient:{definition.actor_code}")
    if blockers:
        return _blocked_snapshot(
            request=request,
            blockers=blockers,
            contains_proxy=contains_proxy,
            coverage=coverage,
        )

    metrics: list[ActorStructureMetrics] = []
    for definition in sorted(definitions, key=lambda item: item.actor_code):
        history = sorted(values[definition.actor_code].items())
        latest_at, latest_total = history[-1]
        previous_total = history[-2][1]
        before_previous_total = history[-3][1]
        change = latest_total - previous_total
        previous_change = previous_total - before_previous_total
        acceleration = change - previous_change
        percentile = Decimal(sum(1 for _, value in history if value <= latest_total)) / Decimal(
            len(history)
        )
        metrics.append(
            ActorStructureMetrics(
                actor_code=definition.actor_code,
                series_code=definition.series_code,
                measure_concept=definition.measure_concept,
                unit=definition.canonical_unit,
                frequency=definition.frequency,
                source=definition.source,
                revision_policy_ref=definition.revision_policy_ref,
                latest_effective_at=latest_at,
                history_count=len(history),
                total=latest_total,
                change=change,
                acceleration=acceleration,
                historical_percentile=percentile,
                is_proxy=definition.is_proxy,
                proxy_target_actor_code=definition.proxy_target_actor_code,
                proxy_methodology_ref=definition.proxy_methodology_ref,
            )
        )

    if len({metric.latest_effective_at for metric in metrics}) != 1:
        return _blocked_snapshot(
            request=request,
            blockers={"cross_actor_period_mismatch"},
            contains_proxy=contains_proxy,
            coverage=coverage,
        )
    differences = tuple(
        CrossActorDifference(
            left_actor_code=left.actor_code,
            right_actor_code=right.actor_code,
            total_difference=left.total - right.total,
            change_difference=left.change - right.change,
            acceleration_difference=left.acceleration - right.acceleration,
            percentile_difference=(left.historical_percentile - right.historical_percentile),
        )
        for left, right in combinations(metrics, 2)
    )
    return MarketStructureSnapshot(
        status=MarketStructureResearchStatus.AVAILABLE,
        as_of_time=request.as_of_time,
        method_version=request.method_version,
        actor_metrics=tuple(metrics),
        cross_actor_differences=differences,
        blocked_reasons=(),
        contains_proxy=contains_proxy,
        coverage=coverage,
    )


from .market_structure_evidence import (  # noqa: E402
    ImmutableMarketStructureEvidence,
    build_market_structure_evidence,
    market_structure_evidence_hash,
)

__all__ = [
    "MEASURE_KIND_BY_CONCEPT",
    "ActorStructureMetrics",
    "CrossActorDifference",
    "EmpiricalPercentileMethod",
    "ImmutableMarketStructureEvidence",
    "InvestorActorDefinition",
    "MARKET_STRUCTURE_CALENDAR_DATASET",
    "MARKET_STRUCTURE_TAXONOMY_DATASET",
    "MarketStructureAggregationPolicy",
    "MarketStructureGovernanceArtifactKind",
    "MarketStructureMeasureConcept",
    "MarketStructureObservation",
    "MarketStructurePeriodCalendar",
    "MarketStructurePeriodCalendarRef",
    "MarketStructurePublicationAttestation",
    "MarketStructureResearchRequest",
    "MarketStructureResearchStatus",
    "MarketStructureSeriesDefinition",
    "MarketStructureSeriesRef",
    "MarketStructureSnapshot",
    "PITMembershipSnapshot",
    "SeriesPeriodCoverage",
    "VersionedEvidenceReference",
    "aggregate_market_structure",
    "build_market_structure_evidence",
    "market_structure_evidence_hash",
    "market_structure_publication_attestation_hash",
    "validate_series_against_flow_definition",
]
