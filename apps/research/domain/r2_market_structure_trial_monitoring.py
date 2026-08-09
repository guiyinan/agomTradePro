"""Pure R2 explanatory-trial and monitoring contracts.

This module deliberately cannot publish predictive signals, current state,
decisions, lifecycle changes, or execution instructions.  Synthetic evidence
can exercise these contracts but cannot attest that production R2 data is ready.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_text(value: str, field_name: str, *, maximum: int = 500) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be bounded non-blank text")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class R2PublicationKind(str, Enum):
    """Canonical governance Publication required by the R2 trial."""

    TAXONOMY = "taxonomy"
    EXPECTED_PERIOD_CALENDAR = "expected_period_calendar"


class R2MeasureKind(str, Enum):
    """Non-interchangeable investor-flow measure semantics."""

    FLOW = "flow"
    HOLDING_CHANGE = "holding_change"
    STOCK = "stock"
    TRANSACTION_NET_FLOW = "transaction_net_flow"


class R2ExplanatoryMetricKey(str, Enum):
    """Descriptive/explanatory metrics allowed in the bounded trial."""

    COVERAGE_RATIO = "coverage_ratio"
    STABILITY_SCORE = "stability_score"
    INCREMENTAL_EXPLANATORY_POWER = "incremental_explanatory_power"


def _require_r2_explanatory_metric_domain(
    *,
    metric_key: R2ExplanatoryMetricKey,
    unit: str,
    value: Decimal,
    field_name: str,
) -> None:
    """Validate the canonical unit and bounded explanatory metric domain."""

    if metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER and unit != "delta_r2":
        raise ValueError(f"{field_name} incremental explanatory power requires delta_r2")
    _require_finite(value, field_name)
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{field_name} must be within [0, 1]")


def _r2_explanatory_metric_domain_is_valid(
    *,
    metric_key: object,
    unit: object,
    value: object,
) -> bool:
    """Return whether reread metric content still satisfies its live contract."""

    try:
        if (
            not isinstance(metric_key, R2ExplanatoryMetricKey)
            or not isinstance(unit, str)
            or not isinstance(value, Decimal)
        ):
            return False
        _require_r2_explanatory_metric_domain(
            metric_key=metric_key,
            unit=unit,
            value=value,
            field_name="R2 explanatory metric value",
        )
    except (TypeError, ValueError):
        return False
    return True


REQUIRED_R2_EXPLANATORY_METRICS: frozenset[R2ExplanatoryMetricKey] = frozenset(
    R2ExplanatoryMetricKey
)


class R2ThresholdDirection(str, Enum):
    """Direction in which a metric satisfies its preregistered threshold."""

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class R2TrialStatus(str, Enum):
    """Research-only trial assessment state."""

    PASSED = "passed"
    BREACHED = "breached"
    BLOCKED = "blocked"


class R2MonitoringStatus(str, Enum):
    """Research-only monitoring state with manual review only."""

    HEALTHY = "healthy"
    BREACHED = "breached"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"
    BLOCKED = "blocked"


class R2TrialBlockerCode(str, Enum):
    """Stable fail-closed reasons for trial and monitoring evaluation."""

    POLICY_MISSING = "r2_explanatory.policy.missing"
    POLICY_IDENTITY_MISMATCH = "r2_explanatory.policy.identity_mismatch"
    POLICY_HASH_MISMATCH = "r2_explanatory.policy.hash_mismatch"
    POLICY_INACTIVE = "r2_explanatory.policy.inactive"
    POLICY_FROM_FUTURE = "r2_explanatory.policy.from_future"
    SELECTION_LEAKAGE = "r2_explanatory.selection.leakage"
    TAXONOMY_PUBLICATION_MISSING = "r2_explanatory.taxonomy_publication.missing"
    TAXONOMY_PUBLICATION_INVALID = "r2_explanatory.taxonomy_publication.invalid"
    CALENDAR_PUBLICATION_MISSING = "r2_explanatory.calendar_publication.missing"
    CALENDAR_PUBLICATION_INVALID = "r2_explanatory.calendar_publication.invalid"
    PUBLICATION_REPLACED = "r2_explanatory.publication.replaced"
    PUBLICATION_FROM_FUTURE = "r2_explanatory.publication.from_future"
    PUBLICATION_STALE = "r2_explanatory.publication.stale"
    CYCLE_EVIDENCE_MISSING = "r2_explanatory.cycle_evidence.missing"
    CYCLE_EVIDENCE_REPLACED = "r2_explanatory.cycle_evidence.replaced"
    CYCLE_EVIDENCE_INVALID = "r2_explanatory.cycle_evidence.invalid"
    CYCLE_EVIDENCE_FROM_FUTURE = "r2_explanatory.cycle_evidence.from_future"
    CYCLE_EVIDENCE_STALE = "r2_explanatory.cycle_evidence.stale"
    CYCLE_PERIOD_INCOMPLETE = "r2_explanatory.cycle_period.incomplete"
    CYCLE_PERIOD_OVERLAP = "r2_explanatory.cycle_period.overlap"
    MEASURE_SEMANTICS_MISMATCH = "r2_explanatory.measure_semantics.mismatch"
    UNIT_MISMATCH = "r2_explanatory.unit.mismatch"
    SAMPLE_DENOMINATOR_INVALID = "r2_explanatory.sample_denominator.invalid"
    AUDIT_OUTCOME_MISSING = "r2_explanatory.audit_outcome.missing"
    AUDIT_OUTCOME_REPLACED = "r2_explanatory.audit_outcome.replaced"
    AUDIT_OUTCOME_INVALID = "r2_explanatory.audit_outcome.invalid"
    AUDIT_OUTCOME_FROM_FUTURE = "r2_explanatory.audit_outcome.from_future"
    AUDIT_OUTCOME_STALE = "r2_explanatory.audit_outcome.stale"
    METRIC_SET_INVALID = "r2_explanatory.metric_set.invalid"
    METRIC_DOMAIN_INVALID = "r2_explanatory.metric.domain_invalid"
    MULTIPLE_TEST_BINDING_INVALID = "r2_explanatory.multiple_test.invalid"
    MONITORING_FACTS_MISSING = "r2_monitoring.facts.missing"
    MONITORING_FACT_REPLACED = "r2_monitoring.fact.replaced"
    MONITORING_FACT_FROM_FUTURE = "r2_monitoring.fact.from_future"
    MONITORING_FACT_STALE = "r2_monitoring.fact.stale"
    MONITORING_PERIOD_INVALID = "r2_monitoring.period.invalid"
    MONITORING_PERIOD_OVERLAP = "r2_monitoring.period.overlap"
    LABEL_PROTOCOL_MISMATCH = "r2_monitoring.label_protocol.mismatch"
    AUTHORITATIVE_CLOCK_UNAVAILABLE = "r2_explanatory.authoritative_clock.unavailable"
    OWNER_EVIDENCE_UNAVAILABLE = "r2_explanatory.owner_evidence.unavailable"


@dataclass(frozen=True)
class R2EvidenceRef:
    """Exact ID/version/hash selector for one owner artifact."""

    evidence_id: str
    evidence_version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "R2EvidenceRef.evidence_id")
        _require_token(self.evidence_version, "R2EvidenceRef.evidence_version")
        _require_hash(self.content_hash, "R2EvidenceRef.content_hash")

    def payload(self) -> dict[str, str]:
        """Return the exact selector payload."""

        return {
            "evidence_id": self.evidence_id,
            "evidence_version": self.evidence_version,
            "content_hash": self.content_hash.lower(),
        }


R2_PIT_MANIFEST_VERSION = "r2-pit-manifest.v1"


def derive_r2_pit_manifest_ref(
    *,
    period_id: str,
    series_code: str,
    series_version: str,
    observation_refs: tuple[R2EvidenceRef, ...],
) -> R2EvidenceRef:
    """Derive an exact PIT manifest identity and seal from raw membership."""

    _require_token(period_id, "derive_r2_pit_manifest_ref.period_id")
    _require_token(series_code, "derive_r2_pit_manifest_ref.series_code")
    _require_token(series_version, "derive_r2_pit_manifest_ref.series_version")
    ordered_refs = tuple(
        sorted(
            observation_refs,
            key=lambda item: (
                item.evidence_id,
                item.evidence_version,
                item.content_hash,
            ),
        )
    )
    cell_hash = _hash(
        {
            "period_id": period_id,
            "series_code": series_code,
            "series_version": series_version,
        }
    )
    return R2EvidenceRef(
        evidence_id=f"r2-pit-manifest:{cell_hash}",
        evidence_version=R2_PIT_MANIFEST_VERSION,
        content_hash=_hash(
            {
                "schema": R2_PIT_MANIFEST_VERSION,
                "period_id": period_id,
                "series_code": series_code,
                "series_version": series_version,
                "observation_refs": [item.payload() for item in ordered_refs],
            }
        ),
    )


@dataclass(frozen=True)
class R2PublicationRef:
    """Exact canonical owner/id/version/hash Publication identity."""

    owner: str
    publication_id: str
    publication_version: str
    publication_hash: str
    artifact_hash: str

    def __post_init__(self) -> None:
        _require_token(self.owner, "R2PublicationRef.owner")
        _require_token(self.publication_id, "R2PublicationRef.publication_id")
        _require_token(self.publication_version, "R2PublicationRef.publication_version")
        _require_hash(self.publication_hash, "R2PublicationRef.publication_hash")
        _require_hash(self.artifact_hash, "R2PublicationRef.artifact_hash")

    def payload(self) -> dict[str, str]:
        """Return canonical Publication identity."""

        return {
            "owner": self.owner,
            "publication_id": self.publication_id,
            "publication_version": self.publication_version,
            "publication_hash": self.publication_hash.lower(),
            "artifact_hash": self.artifact_hash.lower(),
        }


@dataclass(frozen=True)
class R2PublicationProjectionSeal:
    """Selection-known exact seal for one canonical Publication projection."""

    reference: R2PublicationRef
    projection_hash: str
    available_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require_hash(
            self.projection_hash,
            "R2PublicationProjectionSeal.projection_hash",
        )
        _require_aware(
            self.available_at,
            "R2PublicationProjectionSeal.available_at",
        )
        _require_aware(
            self.recorded_at,
            "R2PublicationProjectionSeal.recorded_at",
        )
        if self.available_at > self.recorded_at:
            raise ValueError("R2 Publication projection knowledge clocks are invalid")

    def payload(self) -> dict[str, object]:
        """Return the exact projection selector and knowledge clocks."""

        return {
            "reference": self.reference.payload(),
            "projection_hash": self.projection_hash.lower(),
            "available_at": _utc(self.available_at),
            "recorded_at": _utc(self.recorded_at),
        }


@dataclass(frozen=True)
class R2MeasureSemantic:
    """Exact direct/proxy semantics for one selected canonical series."""

    series_code: str
    series_version: str
    actor_code: str
    measure_kind: R2MeasureKind
    unit: str
    frequency: str
    source: str
    revision_policy_ref: str
    is_proxy: bool
    proxy_target_actor_code: str = ""
    proxy_methodology_ref: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.series_code, "series_code"),
            (self.series_version, "series_version"),
            (self.actor_code, "actor_code"),
            (self.unit, "unit"),
            (self.frequency, "frequency"),
            (self.source, "source"),
        ):
            _require_token(value, f"R2MeasureSemantic.{name}")
        if not isinstance(self.measure_kind, R2MeasureKind):
            raise ValueError("R2MeasureSemantic.measure_kind is invalid")
        _require_text(self.revision_policy_ref, "R2MeasureSemantic.revision_policy_ref")
        if not isinstance(self.is_proxy, bool):
            raise ValueError("R2MeasureSemantic.is_proxy must be boolean")
        if self.is_proxy:
            _require_token(
                self.proxy_target_actor_code,
                "R2MeasureSemantic.proxy_target_actor_code",
            )
            _require_text(
                self.proxy_methodology_ref,
                "R2MeasureSemantic.proxy_methodology_ref",
            )
        elif self.proxy_target_actor_code or self.proxy_methodology_ref:
            raise ValueError("direct measure cannot carry proxy semantics")

    def payload(self) -> dict[str, object]:
        """Return exact measure/proxy semantics."""

        return {
            "series_code": self.series_code,
            "series_version": self.series_version,
            "actor_code": self.actor_code,
            "measure_kind": self.measure_kind.value,
            "unit": self.unit,
            "frequency": self.frequency,
            "source": self.source,
            "revision_policy_ref": self.revision_policy_ref,
            "is_proxy": self.is_proxy,
            "proxy_target_actor_code": self.proxy_target_actor_code,
            "proxy_methodology_ref": self.proxy_methodology_ref,
        }


@dataclass(frozen=True)
class R2ExpectedPeriod:
    """One exact non-overlapping member of the canonical expected calendar."""

    period_id: str
    period_start: datetime
    period_end: datetime

    def __post_init__(self) -> None:
        _require_token(self.period_id, "R2ExpectedPeriod.period_id")
        _require_aware(self.period_start, "R2ExpectedPeriod.period_start")
        _require_aware(self.period_end, "R2ExpectedPeriod.period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R2 expected period must be non-empty")

    def payload(self) -> dict[str, str]:
        """Return exact expected-period content."""

        return {
            "period_id": self.period_id,
            "period_start": _utc(self.period_start),
            "period_end": _utc(self.period_end),
        }


@dataclass(frozen=True)
class R2ExpectedSeriesPeriodEntry:
    """Canonical calendar cell and its preregistered raw-observation manifest."""

    period_id: str
    series_code: str
    series_version: str
    expected_observation_refs: tuple[R2EvidenceRef, ...]
    pit_manifest_ref: R2EvidenceRef

    def __post_init__(self) -> None:
        _require_token(self.period_id, "R2ExpectedSeriesPeriodEntry.period_id")
        _require_token(self.series_code, "R2ExpectedSeriesPeriodEntry.series_code")
        _require_token(
            self.series_version,
            "R2ExpectedSeriesPeriodEntry.series_version",
        )
        if not self.expected_observation_refs:
            raise ValueError("R2 expected series/period observations are required")
        identities = tuple(
            (item.evidence_id, item.evidence_version) for item in self.expected_observation_refs
        )
        if len(identities) != len(set(identities)):
            raise ValueError("R2 expected observation identities must be unique")
        if self.expected_observation_refs != tuple(
            sorted(
                self.expected_observation_refs,
                key=lambda item: (
                    item.evidence_id,
                    item.evidence_version,
                    item.content_hash,
                ),
            )
        ):
            raise ValueError("R2 expected observation refs must be in canonical order")
        if self.pit_manifest_ref != derive_r2_pit_manifest_ref(
            period_id=self.period_id,
            series_code=self.series_code,
            series_version=self.series_version,
            observation_refs=self.expected_observation_refs,
        ):
            raise ValueError("R2 expected PIT manifest seal is invalid")

    def payload(self) -> dict[str, object]:
        """Return the exact canonical cell and raw-observation membership."""

        return {
            "period_id": self.period_id,
            "series_code": self.series_code,
            "series_version": self.series_version,
            "expected_observation_refs": [
                item.payload() for item in self.expected_observation_refs
            ],
            "pit_manifest_ref": self.pit_manifest_ref.payload(),
        }


@dataclass(frozen=True)
class R2MarketCycleDefinition:
    """One preregistered complete market-cycle window."""

    cycle_id: str
    cycle_label: str
    classification_version: str
    cycle_start: datetime
    cycle_end: datetime
    expected_period_ids: tuple[str, ...]
    evidence_ref: R2EvidenceRef

    def __post_init__(self) -> None:
        _require_token(self.cycle_id, "R2MarketCycleDefinition.cycle_id")
        _require_token(self.cycle_label, "R2MarketCycleDefinition.cycle_label")
        _require_token(
            self.classification_version,
            "R2MarketCycleDefinition.classification_version",
        )
        _require_aware(self.cycle_start, "R2MarketCycleDefinition.cycle_start")
        _require_aware(self.cycle_end, "R2MarketCycleDefinition.cycle_end")
        if self.cycle_start >= self.cycle_end or not self.expected_period_ids:
            raise ValueError("R2 market cycle window must be complete and non-empty")
        for period_id in self.expected_period_ids:
            _require_token(period_id, "R2MarketCycleDefinition.expected_period_id")
        if len(self.expected_period_ids) != len(set(self.expected_period_ids)):
            raise ValueError("R2 market cycle periods must be unique")

    def payload(self) -> dict[str, object]:
        """Return exact cycle definition and owner evidence selector."""

        return {
            "cycle_id": self.cycle_id,
            "cycle_label": self.cycle_label,
            "classification_version": self.classification_version,
            "cycle_start": _utc(self.cycle_start),
            "cycle_end": _utc(self.cycle_end),
            "expected_period_ids": list(self.expected_period_ids),
            "evidence_ref": self.evidence_ref.payload(),
        }


@dataclass(frozen=True)
class R2MetricRule:
    """Preregistered trial threshold and monitoring invalidation rule."""

    metric_key: R2ExplanatoryMetricKey
    unit: str
    direction: R2ThresholdDirection
    trial_threshold: Decimal
    monitoring_threshold: Decimal
    retirement_review_consecutive_breaches: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R2ExplanatoryMetricKey):
            raise ValueError("R2MetricRule.metric_key is invalid")
        _require_token(self.unit, "R2MetricRule.unit")
        if not isinstance(self.direction, R2ThresholdDirection):
            raise ValueError("R2MetricRule.direction is invalid")
        if self.direction is not R2ThresholdDirection.AT_LEAST:
            raise ValueError("R2 explanatory metrics require an at-least direction")
        _require_r2_explanatory_metric_domain(
            metric_key=self.metric_key,
            unit=self.unit,
            value=self.trial_threshold,
            field_name="R2MetricRule.trial_threshold",
        )
        _require_r2_explanatory_metric_domain(
            metric_key=self.metric_key,
            unit=self.unit,
            value=self.monitoring_threshold,
            field_name="R2MetricRule.monitoring_threshold",
        )
        if (
            isinstance(self.retirement_review_consecutive_breaches, bool)
            or self.retirement_review_consecutive_breaches < 1
        ):
            raise ValueError("R2 invalidation consecutive-breach count must be positive")

    def is_satisfied(self, value: Decimal, *, monitoring: bool = False) -> bool:
        """Apply the exact preregistered direction and threshold."""

        _require_finite(value, "R2MetricRule.value")
        threshold = self.monitoring_threshold if monitoring else self.trial_threshold
        if self.direction is R2ThresholdDirection.AT_LEAST:
            return value >= threshold
        return value <= threshold

    def payload(self) -> dict[str, object]:
        """Return exact metric and invalidation rules."""

        return {
            "metric_key": self.metric_key.value,
            "unit": self.unit,
            "direction": self.direction.value,
            "trial_threshold": _decimal(self.trial_threshold),
            "monitoring_threshold": _decimal(self.monitoring_threshold),
            "retirement_review_consecutive_breaches": (self.retirement_review_consecutive_breaches),
        }


@dataclass(frozen=True)
class R2MultipleTestingRule:
    """Exact preregistered family and adjusted-significance gate."""

    family_id: str
    method_version: str
    hypothesis_count: int
    maximum_adjusted_p_value: Decimal

    def __post_init__(self) -> None:
        _require_token(self.family_id, "R2MultipleTestingRule.family_id")
        _require_token(self.method_version, "R2MultipleTestingRule.method_version")
        if self.method_version != "holm-v1":
            raise ValueError("R2 multiple testing supports only holm-v1")
        if isinstance(self.hypothesis_count, bool) or self.hypothesis_count < 1:
            raise ValueError("R2 multiple-test hypothesis_count must be positive")
        _require_finite(
            self.maximum_adjusted_p_value,
            "R2MultipleTestingRule.maximum_adjusted_p_value",
        )
        if not Decimal("0") <= self.maximum_adjusted_p_value <= Decimal("1"):
            raise ValueError("R2 adjusted p-value threshold must be within [0, 1]")

    def payload(self) -> dict[str, object]:
        """Return exact multiple-test family content."""

        return {
            "family_id": self.family_id,
            "method_version": self.method_version,
            "hypothesis_count": self.hypothesis_count,
            "maximum_adjusted_p_value": _decimal(self.maximum_adjusted_p_value),
        }


@dataclass(frozen=True)
class R2MarketStructureTrialPolicy:
    """Selection-time-preregistered, content-addressed R2 explanatory policy."""

    policy_id: str
    policy_version: str
    taxonomy_publication_ref: R2PublicationRef
    calendar_publication_ref: R2PublicationRef
    taxonomy_projection_seal: R2PublicationProjectionSeal
    calendar_projection_seal: R2PublicationProjectionSeal
    measure_semantics: tuple[R2MeasureSemantic, ...]
    expected_periods: tuple[R2ExpectedPeriod, ...]
    expected_series_period_entries: tuple[R2ExpectedSeriesPeriodEntry, ...]
    cycles: tuple[R2MarketCycleDefinition, ...]
    metric_rules: tuple[R2MetricRule, ...]
    multiple_testing: R2MultipleTestingRule
    audit_plan_ref: R2EvidenceRef
    expected_cycle_evidence_owner: str
    expected_audit_owner: str
    minimum_observations_per_series_period: int
    minimum_monitoring_sample_count: int
    maximum_monitoring_age_seconds: int
    label_protocol_version: str
    expected_label_set_hash: str
    registered_at: datetime
    selection_as_of: datetime
    active_from: datetime
    active_until: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R2MarketStructureTrialPolicy.policy_id")
        _require_token(self.policy_version, "R2MarketStructureTrialPolicy.policy_version")
        if not self.measure_semantics:
            raise ValueError("R2 policy requires explicit measure/proxy semantics")
        semantic_ids = tuple(
            (item.series_code, item.series_version) for item in self.measure_semantics
        )
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("R2 policy measure semantics must be unique")
        if (
            self.taxonomy_projection_seal.reference != self.taxonomy_publication_ref
            or self.calendar_projection_seal.reference != self.calendar_publication_ref
        ):
            raise ValueError("R2 policy Publication projection refs are inconsistent")
        if not self.expected_periods:
            raise ValueError("R2 policy requires an expected-period calendar")
        periods = tuple(
            sorted(
                self.expected_periods,
                key=lambda item: (item.period_start, item.period_end, item.period_id),
            )
        )
        if periods != self.expected_periods:
            raise ValueError("R2 expected periods must be in canonical order")
        period_ids = tuple(item.period_id for item in periods)
        if len(period_ids) != len(set(period_ids)):
            raise ValueError("R2 expected period identities must be unique")
        if any(
            current.period_start < previous.period_end
            for previous, current in zip(periods, periods[1:], strict=False)
        ):
            raise ValueError("R2 expected periods cannot overlap")
        entry_identities = tuple(
            (item.period_id, item.series_code, item.series_version)
            for item in self.expected_series_period_entries
        )
        expected_entry_identities = tuple(
            (period.period_id, series_code, series_version)
            for period in periods
            for series_code, series_version in semantic_ids
        )
        if entry_identities != expected_entry_identities:
            raise ValueError(
                "R2 calendar manifest must define every series/period cell canonically"
            )
        if len(self.cycles) != 2:
            raise ValueError("R2 explanatory trial requires exactly two market cycles")
        ordered_cycles = tuple(sorted(self.cycles, key=lambda item: item.cycle_start))
        if ordered_cycles != self.cycles:
            raise ValueError("R2 market cycles must be in canonical order")
        if ordered_cycles[1].cycle_start < ordered_cycles[0].cycle_end:
            raise ValueError("R2 market cycles cannot overlap")
        cycle_ids = tuple(item.cycle_id for item in self.cycles)
        if len(cycle_ids) != len(set(cycle_ids)):
            raise ValueError("R2 market cycle identities must be unique")
        period_by_id = {item.period_id: item for item in periods}
        used_cycle_periods: set[str] = set()
        for cycle in self.cycles:
            if not set(cycle.expected_period_ids).issubset(period_by_id):
                raise ValueError("R2 market cycle references an unknown expected period")
            if used_cycle_periods & set(cycle.expected_period_ids):
                raise ValueError("R2 market cycles cannot share expected periods")
            used_cycle_periods.update(cycle.expected_period_ids)
            cycle_periods = tuple(period_by_id[item] for item in cycle.expected_period_ids)
            if (
                cycle_periods[0].period_start != cycle.cycle_start
                or cycle_periods[-1].period_end != cycle.cycle_end
                or any(
                    current.period_start != previous.period_end
                    for previous, current in zip(
                        cycle_periods,
                        cycle_periods[1:],
                        strict=False,
                    )
                )
            ):
                raise ValueError("R2 market cycle must span its complete expected-period set")
        metric_keys = tuple(item.metric_key for item in self.metric_rules)
        if len(metric_keys) != len(set(metric_keys)) or frozenset(metric_keys) != (
            REQUIRED_R2_EXPLANATORY_METRICS
        ):
            raise ValueError("R2 policy must preregister every explanatory metric exactly")
        if self.multiple_testing.hypothesis_count != len(self.cycles):
            raise ValueError("R2 multiple-test family must cover both cycle hypotheses")
        _require_token(
            self.expected_cycle_evidence_owner,
            "R2MarketStructureTrialPolicy.expected_cycle_evidence_owner",
        )
        _require_token(
            self.expected_audit_owner,
            "R2MarketStructureTrialPolicy.expected_audit_owner",
        )
        for numeric_value, name in (
            (
                self.minimum_observations_per_series_period,
                "minimum_observations_per_series_period",
            ),
            (self.minimum_monitoring_sample_count, "minimum_monitoring_sample_count"),
            (self.maximum_monitoring_age_seconds, "maximum_monitoring_age_seconds"),
        ):
            if isinstance(numeric_value, bool) or numeric_value < 1:
                raise ValueError(f"R2 policy {name} must be positive")
        if any(
            len(item.expected_observation_refs) < self.minimum_observations_per_series_period
            for item in self.expected_series_period_entries
        ):
            raise ValueError(
                "R2 calendar manifest cannot be smaller than the preregistered minimum"
            )
        _require_token(
            self.label_protocol_version,
            "R2MarketStructureTrialPolicy.label_protocol_version",
        )
        _require_hash(
            self.expected_label_set_hash,
            "R2MarketStructureTrialPolicy.expected_label_set_hash",
        )
        for clock_value, name in (
            (self.registered_at, "registered_at"),
            (self.selection_as_of, "selection_as_of"),
            (self.active_from, "active_from"),
            (self.active_until, "active_until"),
        ):
            _require_aware(clock_value, f"R2MarketStructureTrialPolicy.{name}")
        if not self.registered_at < self.selection_as_of:
            raise ValueError("R2 policy must be registered before selection")
        for seal in (self.taxonomy_projection_seal, self.calendar_projection_seal):
            if seal.available_at > self.registered_at or seal.recorded_at > self.registered_at:
                raise ValueError(
                    "R2 Publication projection must be known before policy registration"
                )
        if not self.active_from <= self.selection_as_of < self.active_until:
            raise ValueError("R2 policy selection clock must lie in its active window")
        object.__setattr__(self, "content_hash", r2_trial_policy_hash(self))

    @property
    def reference(self) -> R2EvidenceRef:
        """Return the exact content-addressed policy selector."""

        return R2EvidenceRef(self.policy_id, self.policy_version, self.content_hash)

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this preregistered policy is active at ``as_of``."""

        _require_aware(as_of, "R2MarketStructureTrialPolicy.as_of")
        return self.active_from <= as_of < self.active_until


def r2_trial_policy_hash(policy: R2MarketStructureTrialPolicy) -> str:
    """Recompute the complete preregistered policy seal."""

    return _hash(
        {
            "schema": "r2-market-structure-explanatory-policy.v1",
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "taxonomy_publication_ref": policy.taxonomy_publication_ref.payload(),
            "calendar_publication_ref": policy.calendar_publication_ref.payload(),
            "taxonomy_projection_seal": policy.taxonomy_projection_seal.payload(),
            "calendar_projection_seal": policy.calendar_projection_seal.payload(),
            "measure_semantics": [
                item.payload()
                for item in sorted(
                    policy.measure_semantics,
                    key=lambda value: (value.series_code, value.series_version),
                )
            ],
            "expected_periods": [item.payload() for item in policy.expected_periods],
            "expected_series_period_entries": [
                item.payload() for item in policy.expected_series_period_entries
            ],
            "cycles": [item.payload() for item in policy.cycles],
            "metric_rules": [
                item.payload()
                for item in sorted(policy.metric_rules, key=lambda value: value.metric_key.value)
            ],
            "multiple_testing": policy.multiple_testing.payload(),
            "audit_plan_ref": policy.audit_plan_ref.payload(),
            "expected_cycle_evidence_owner": policy.expected_cycle_evidence_owner,
            "expected_audit_owner": policy.expected_audit_owner,
            "minimum_observations_per_series_period": (
                policy.minimum_observations_per_series_period
            ),
            "minimum_monitoring_sample_count": policy.minimum_monitoring_sample_count,
            "maximum_monitoring_age_seconds": policy.maximum_monitoring_age_seconds,
            "label_protocol_version": policy.label_protocol_version,
            "expected_label_set_hash": policy.expected_label_set_hash.lower(),
            "registered_at": _utc(policy.registered_at),
            "selection_as_of": _utc(policy.selection_as_of),
            "active_from": _utc(policy.active_from),
            "active_until": _utc(policy.active_until),
        }
    )


@dataclass(frozen=True)
class R2CanonicalPublicationEvidence:
    """Application projection of one canonical taxonomy or calendar Publication."""

    kind: R2PublicationKind
    reference: R2PublicationRef
    available_at: datetime
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    measure_semantics: tuple[R2MeasureSemantic, ...] = ()
    expected_periods: tuple[R2ExpectedPeriod, ...] = ()
    expected_series_period_entries: tuple[R2ExpectedSeriesPeriodEntry, ...] = ()
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, R2PublicationKind):
            raise ValueError("R2 canonical Publication kind is invalid")
        for clock_value, name in (
            (self.available_at, "available_at"),
            (self.recorded_at, "recorded_at"),
            (self.valid_from, "valid_from"),
            (self.valid_until, "valid_until"),
        ):
            _require_aware(clock_value, f"R2CanonicalPublicationEvidence.{name}")
        if self.available_at > self.recorded_at or self.valid_from >= self.valid_until:
            raise ValueError("R2 canonical Publication clocks are invalid")
        if self.kind is R2PublicationKind.TAXONOMY:
            if (
                not self.measure_semantics
                or self.expected_periods
                or self.expected_series_period_entries
            ):
                raise ValueError("R2 taxonomy Publication must carry only measure semantics")
        elif (
            not self.expected_periods
            or not self.expected_series_period_entries
            or self.measure_semantics
        ):
            raise ValueError("R2 calendar Publication must carry only expected periods")
        object.__setattr__(self, "content_hash", r2_publication_evidence_hash(self))

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the Publication is known and valid at ``as_of``."""

        _require_aware(as_of, "R2CanonicalPublicationEvidence.as_of")
        return (
            self.available_at <= as_of
            and self.recorded_at <= as_of
            and self.valid_from <= as_of < self.valid_until
        )


def r2_publication_evidence_hash(evidence: R2CanonicalPublicationEvidence) -> str:
    """Recompute a canonical Publication projection seal."""

    return _hash(
        {
            "schema": "r2-canonical-publication-evidence.v1",
            "kind": evidence.kind.value,
            "reference": evidence.reference.payload(),
            "available_at": _utc(evidence.available_at),
            "recorded_at": _utc(evidence.recorded_at),
            "valid_from": _utc(evidence.valid_from),
            "valid_until": _utc(evidence.valid_until),
            "measure_semantics": [
                item.payload()
                for item in sorted(
                    evidence.measure_semantics,
                    key=lambda value: (value.series_code, value.series_version),
                )
            ],
            "expected_periods": [item.payload() for item in evidence.expected_periods],
            "expected_series_period_entries": [
                item.payload() for item in evidence.expected_series_period_entries
            ],
        }
    )


@dataclass(frozen=True)
class R2SeriesPeriodSample:
    """One exact PIT series/period coverage cell within a market cycle."""

    period_id: str
    series_code: str
    series_version: str
    measure_kind: R2MeasureKind
    is_proxy: bool
    unit: str
    observation_refs: tuple[R2EvidenceRef, ...]
    available_at: datetime
    pit_manifest_ref: R2EvidenceRef
    evidence_ref: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.period_id, "period_id"),
            (self.series_code, "series_code"),
            (self.series_version, "series_version"),
            (self.unit, "unit"),
        ):
            _require_token(value, f"R2SeriesPeriodSample.{name}")
        if not isinstance(self.measure_kind, R2MeasureKind):
            raise ValueError("R2SeriesPeriodSample.measure_kind is invalid")
        if not isinstance(self.is_proxy, bool):
            raise ValueError("R2SeriesPeriodSample.is_proxy must be boolean")
        identities = tuple(
            (item.evidence_id, item.evidence_version) for item in self.observation_refs
        )
        if len(identities) != len(set(identities)):
            raise ValueError("R2 series/period observation refs must be unique")
        if self.observation_refs != tuple(
            sorted(
                self.observation_refs,
                key=lambda item: (
                    item.evidence_id,
                    item.evidence_version,
                    item.content_hash,
                ),
            )
        ):
            raise ValueError("R2 series/period observation refs must be canonical")
        _require_aware(self.available_at, "R2SeriesPeriodSample.available_at")
        if self.pit_manifest_ref != derive_r2_pit_manifest_ref(
            period_id=self.period_id,
            series_code=self.series_code,
            series_version=self.series_version,
            observation_refs=self.observation_refs,
        ):
            raise ValueError("R2 series/period PIT manifest seal is invalid")
        _require_text(self.evidence_ref, "R2SeriesPeriodSample.evidence_ref")

    @property
    def observation_count(self) -> int:
        """Derive actual coverage from exact raw-observation membership."""

        return len(self.observation_refs)

    def payload(self) -> dict[str, object]:
        """Return the exact PIT cell and denominator."""

        return {
            "period_id": self.period_id,
            "series_code": self.series_code,
            "series_version": self.series_version,
            "measure_kind": self.measure_kind.value,
            "is_proxy": self.is_proxy,
            "unit": self.unit,
            "observation_refs": [item.payload() for item in self.observation_refs],
            "available_at": _utc(self.available_at),
            "pit_manifest_ref": self.pit_manifest_ref.payload(),
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class R2CyclePITEvidence:
    """Content-addressed PIT coverage for one complete preregistered cycle."""

    evidence_id: str
    evidence_version: str
    source_owner: str
    cycle_id: str
    taxonomy_publication_ref: R2PublicationRef
    calendar_publication_ref: R2PublicationRef
    samples: tuple[R2SeriesPeriodSample, ...]
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.evidence_id, "R2CyclePITEvidence.evidence_id")
        _require_token(self.evidence_version, "R2CyclePITEvidence.evidence_version")
        _require_token(self.source_owner, "R2CyclePITEvidence.source_owner")
        _require_token(self.cycle_id, "R2CyclePITEvidence.cycle_id")
        if not self.samples:
            raise ValueError("R2 cycle PIT evidence requires samples")
        identities = tuple(
            (item.period_id, item.series_code, item.series_version) for item in self.samples
        )
        if len(identities) != len(set(identities)):
            raise ValueError("R2 cycle PIT samples must have unique identities")
        for clock_value, name in (
            (self.observed_at, "observed_at"),
            (self.available_at, "available_at"),
            (self.recorded_at, "recorded_at"),
            (self.valid_from, "valid_from"),
            (self.valid_until, "valid_until"),
        ):
            _require_aware(clock_value, f"R2CyclePITEvidence.{name}")
        if not self.observed_at <= self.available_at <= self.recorded_at:
            raise ValueError("R2 cycle PIT knowledge clocks are invalid")
        if self.valid_from >= self.valid_until:
            raise ValueError("R2 cycle PIT validity clocks are invalid")
        object.__setattr__(self, "content_hash", r2_cycle_pit_evidence_hash(self))

    @property
    def reference(self) -> R2EvidenceRef:
        """Return the exact owner evidence selector."""

        return R2EvidenceRef(self.evidence_id, self.evidence_version, self.content_hash)

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the exact cycle evidence is known and valid."""

        _require_aware(as_of, "R2CyclePITEvidence.as_of")
        return self.recorded_at <= as_of and self.valid_from <= as_of < self.valid_until


def r2_cycle_pit_evidence_hash(evidence: R2CyclePITEvidence) -> str:
    """Recompute the exact two-clock cycle PIT seal."""

    return _hash(
        {
            "schema": "r2-cycle-pit-evidence.v1",
            "evidence_id": evidence.evidence_id,
            "evidence_version": evidence.evidence_version,
            "source_owner": evidence.source_owner,
            "cycle_id": evidence.cycle_id,
            "taxonomy_publication_ref": evidence.taxonomy_publication_ref.payload(),
            "calendar_publication_ref": evidence.calendar_publication_ref.payload(),
            "samples": [
                item.payload()
                for item in sorted(
                    evidence.samples,
                    key=lambda value: (
                        value.period_id,
                        value.series_code,
                        value.series_version,
                    ),
                )
            ],
            "observed_at": _utc(evidence.observed_at),
            "available_at": _utc(evidence.available_at),
            "recorded_at": _utc(evidence.recorded_at),
            "valid_from": _utc(evidence.valid_from),
            "valid_until": _utc(evidence.valid_until),
        }
    )


@dataclass(frozen=True)
class R2AuditMetric:
    """Audit-owned typed explanatory metric for exactly one cycle."""

    cycle_id: str
    metric_key: R2ExplanatoryMetricKey
    unit: str
    value: Decimal
    sample_count: int
    expected_sample_count: int
    raw_p_value: Decimal | None = None
    test_family_id: str = ""
    multiple_testing_method_version: str = ""

    def __post_init__(self) -> None:
        _require_token(self.cycle_id, "R2AuditMetric.cycle_id")
        if not isinstance(self.metric_key, R2ExplanatoryMetricKey):
            raise ValueError("R2AuditMetric.metric_key is invalid")
        _require_token(self.unit, "R2AuditMetric.unit")
        _require_r2_explanatory_metric_domain(
            metric_key=self.metric_key,
            unit=self.unit,
            value=self.value,
            field_name="R2AuditMetric.value",
        )
        if (
            isinstance(self.sample_count, bool)
            or self.sample_count < 0
            or isinstance(self.expected_sample_count, bool)
            or self.expected_sample_count < 1
            or self.sample_count > self.expected_sample_count
        ):
            raise ValueError("R2 Audit metric sample denominator is invalid")
        significance = self.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
        if significance != (self.raw_p_value is not None):
            raise ValueError("only incremental explanatory power requires significance evidence")
        if significance:
            assert self.raw_p_value is not None
            _require_finite(self.raw_p_value, "R2AuditMetric.raw_p_value")
            if not Decimal("0") <= self.raw_p_value <= Decimal("1"):
                raise ValueError("R2AuditMetric.raw_p_value must be within [0, 1]")
            _require_token(self.test_family_id, "R2AuditMetric.test_family_id")
            _require_token(
                self.multiple_testing_method_version,
                "R2AuditMetric.multiple_testing_method_version",
            )
        elif self.test_family_id or self.multiple_testing_method_version:
            raise ValueError("non-significance metrics cannot carry a test family")

    def payload(self) -> dict[str, object]:
        """Return exact typed Audit metric evidence."""

        return {
            "cycle_id": self.cycle_id,
            "metric_key": self.metric_key.value,
            "unit": self.unit,
            "value": _decimal(self.value),
            "sample_count": self.sample_count,
            "expected_sample_count": self.expected_sample_count,
            "raw_p_value": None if self.raw_p_value is None else _decimal(self.raw_p_value),
            "test_family_id": self.test_family_id,
            "multiple_testing_method_version": self.multiple_testing_method_version,
        }


@dataclass(frozen=True)
class R2HolmAdjustedPValue:
    """Locally recomputed Holm-v1 result for one canonical hypothesis."""

    hypothesis_id: str
    raw_p_value: Decimal
    adjusted_p_value: Decimal
    rank: int
    hypothesis_count: int

    def __post_init__(self) -> None:
        _require_token(self.hypothesis_id, "R2HolmAdjustedPValue.hypothesis_id")
        for value, name in (
            (self.raw_p_value, "raw_p_value"),
            (self.adjusted_p_value, "adjusted_p_value"),
        ):
            _require_finite(value, f"R2HolmAdjustedPValue.{name}")
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"R2HolmAdjustedPValue.{name} must be within [0, 1]")
        if (
            isinstance(self.rank, bool)
            or isinstance(self.hypothesis_count, bool)
            or not 1 <= self.rank <= self.hypothesis_count
        ):
            raise ValueError("R2 Holm rank/count is invalid")

    def payload(self) -> dict[str, object]:
        """Return deterministic locally derived significance evidence."""

        return {
            "hypothesis_id": self.hypothesis_id,
            "raw_p_value": _decimal(self.raw_p_value),
            "adjusted_p_value": _decimal(self.adjusted_p_value),
            "rank": self.rank,
            "hypothesis_count": self.hypothesis_count,
        }


def derive_r2_holm_adjustments(
    metrics: tuple[R2AuditMetric, ...],
    rule: R2MultipleTestingRule,
) -> tuple[R2HolmAdjustedPValue, ...]:
    """Recompute canonical Holm-v1 adjusted p-values from owner raw p-values."""

    hypotheses = tuple(
        item
        for item in metrics
        if item.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
    )
    if (
        rule.method_version != "holm-v1"
        or len(hypotheses) != rule.hypothesis_count
        or any(
            item.test_family_id != rule.family_id
            or item.multiple_testing_method_version != rule.method_version
            for item in hypotheses
        )
    ):
        raise ValueError("R2 Holm-v1 hypothesis family is incomplete")
    ordered = tuple(
        sorted(
            hypotheses,
            key=lambda item: (
                item.raw_p_value if item.raw_p_value is not None else Decimal("2"),
                item.cycle_id,
                item.metric_key.value,
            ),
        )
    )
    derived: list[R2HolmAdjustedPValue] = []
    running = Decimal("0")
    for index, metric in enumerate(ordered):
        assert metric.raw_p_value is not None
        candidate = min(
            Decimal("1"),
            metric.raw_p_value * Decimal(rule.hypothesis_count - index),
        )
        running = max(running, candidate)
        derived.append(
            R2HolmAdjustedPValue(
                hypothesis_id=(f"{metric.cycle_id}:{metric.metric_key.value}"),
                raw_p_value=metric.raw_p_value,
                adjusted_p_value=running,
                rank=index + 1,
                hypothesis_count=rule.hypothesis_count,
            )
        )
    return tuple(sorted(derived, key=lambda item: item.hypothesis_id))


R2_AUDIT_OUTCOME_VERSION = "r2-audit-outcome.v1"


def derive_r2_audit_outcome_id(
    *,
    policy_ref: R2EvidenceRef,
    audit_plan_ref: R2EvidenceRef,
    cycle_evidence_refs: tuple[R2EvidenceRef, ...],
) -> str:
    """Derive the sole Audit outcome identity permitted by the policy graph."""

    return f"r2-audit-outcome:{_hash({'schema': R2_AUDIT_OUTCOME_VERSION, 'policy_ref': policy_ref.payload(), 'audit_plan_ref': audit_plan_ref.payload(), 'cycle_evidence_refs': [item.payload() for item in cycle_evidence_refs]})}"


@dataclass(frozen=True)
class R2AuditExplanatoryOutcome:
    """Authoritative Audit outcome; callers can select it only through the policy."""

    outcome_id: str
    outcome_version: str
    source_owner: str
    policy_ref: R2EvidenceRef
    audit_plan_ref: R2EvidenceRef
    taxonomy_publication_ref: R2PublicationRef
    calendar_publication_ref: R2PublicationRef
    cycle_evidence_refs: tuple[R2EvidenceRef, ...]
    selection_as_of: datetime
    metrics: tuple[R2AuditMetric, ...]
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.outcome_id, "R2AuditExplanatoryOutcome.outcome_id")
        _require_token(self.outcome_version, "R2AuditExplanatoryOutcome.outcome_version")
        _require_token(self.source_owner, "R2AuditExplanatoryOutcome.source_owner")
        if len(self.cycle_evidence_refs) != 2:
            raise ValueError("R2 Audit outcome must bind exactly two cycle evidence refs")
        identities = tuple(
            (item.evidence_id, item.evidence_version) for item in self.cycle_evidence_refs
        )
        if len(identities) != len(set(identities)):
            raise ValueError("R2 Audit cycle evidence refs must be unique")
        metric_ids = tuple((item.cycle_id, item.metric_key) for item in self.metrics)
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("R2 Audit metric identities must be unique")
        _require_aware(self.selection_as_of, "R2AuditExplanatoryOutcome.selection_as_of")
        for value, name in (
            (self.observed_at, "observed_at"),
            (self.available_at, "available_at"),
            (self.recorded_at, "recorded_at"),
            (self.valid_from, "valid_from"),
            (self.valid_until, "valid_until"),
        ):
            _require_aware(value, f"R2AuditExplanatoryOutcome.{name}")
        if not self.observed_at <= self.available_at <= self.recorded_at:
            raise ValueError("R2 Audit outcome knowledge clocks are invalid")
        if self.valid_from >= self.valid_until:
            raise ValueError("R2 Audit outcome validity clocks are invalid")
        object.__setattr__(self, "content_hash", r2_audit_outcome_hash(self))

    @property
    def reference(self) -> R2EvidenceRef:
        """Return the content-addressed Audit outcome selector."""

        return R2EvidenceRef(self.outcome_id, self.outcome_version, self.content_hash)

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this Audit result is known and still valid."""

        _require_aware(as_of, "R2AuditExplanatoryOutcome.as_of")
        return self.recorded_at <= as_of and self.valid_from <= as_of < self.valid_until


def r2_audit_outcome_hash(outcome: R2AuditExplanatoryOutcome) -> str:
    """Recompute the exact owner outcome seal."""

    return _hash(
        {
            "schema": "r2-audit-explanatory-outcome.v1",
            "outcome_id": outcome.outcome_id,
            "outcome_version": outcome.outcome_version,
            "source_owner": outcome.source_owner,
            "policy_ref": outcome.policy_ref.payload(),
            "audit_plan_ref": outcome.audit_plan_ref.payload(),
            "taxonomy_publication_ref": outcome.taxonomy_publication_ref.payload(),
            "calendar_publication_ref": outcome.calendar_publication_ref.payload(),
            "cycle_evidence_refs": [item.payload() for item in outcome.cycle_evidence_refs],
            "selection_as_of": _utc(outcome.selection_as_of),
            "metrics": [
                item.payload()
                for item in sorted(
                    outcome.metrics,
                    key=lambda value: (value.cycle_id, value.metric_key.value),
                )
            ],
            "observed_at": _utc(outcome.observed_at),
            "available_at": _utc(outcome.available_at),
            "recorded_at": _utc(outcome.recorded_at),
            "valid_from": _utc(outcome.valid_from),
            "valid_until": _utc(outcome.valid_until),
        }
    )


@dataclass(frozen=True)
class R2ExplanatoryTrialAssessment:
    """Derived explanatory-only assessment with every downstream use prohibited."""

    assessed_at: datetime
    status: R2TrialStatus
    policy_ref: R2EvidenceRef | None
    audit_outcome_ref: R2EvidenceRef | None
    metrics: tuple[R2AuditMetric, ...]
    holm_adjustments: tuple[R2HolmAdjustedPValue, ...]
    breached_metrics: tuple[R2ExplanatoryMetricKey, ...]
    blockers: tuple[R2TrialBlockerCode, ...]
    content_hash: str = field(init=False)
    research_only: bool = True
    must_not_use_as_predictive_signal: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    is_attested_ready: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.assessed_at, "R2ExplanatoryTrialAssessment.assessed_at")
        if not isinstance(self.status, R2TrialStatus):
            raise ValueError("R2 explanatory trial status is invalid")
        if self.status is R2TrialStatus.BLOCKED:
            if (
                not self.blockers
                or self.metrics
                or self.holm_adjustments
                or self.audit_outcome_ref is not None
            ):
                raise ValueError("blocked R2 trial assessment requires blockers only")
        elif self.blockers or self.policy_ref is None or self.audit_outcome_ref is None:
            raise ValueError("evaluated R2 trial assessment cannot contain blockers")
        elif not self.holm_adjustments:
            raise ValueError("evaluated R2 trial requires locally derived Holm evidence")
        if self.status is R2TrialStatus.PASSED and self.breached_metrics:
            raise ValueError("passed R2 trial cannot carry breached metrics")
        if self.status is R2TrialStatus.BREACHED and not self.breached_metrics:
            raise ValueError("breached R2 trial requires metric breaches")
        if (
            not all(
                (
                    self.research_only,
                    self.must_not_use_as_predictive_signal,
                    self.must_not_publish_current,
                    self.must_not_use_for_decision,
                    self.must_not_execute,
                )
            )
            or self.is_attested_ready
        ):
            raise ValueError("R2 trial assessment cannot authorize production use")
        object.__setattr__(self, "content_hash", r2_trial_assessment_hash(self))

    @classmethod
    def blocked(
        cls,
        *,
        assessed_at: datetime,
        blockers: tuple[R2TrialBlockerCode, ...],
        policy_ref: R2EvidenceRef | None = None,
    ) -> R2ExplanatoryTrialAssessment:
        """Build one stable fail-closed assessment."""

        return cls(
            assessed_at=assessed_at,
            status=R2TrialStatus.BLOCKED,
            policy_ref=policy_ref,
            audit_outcome_ref=None,
            metrics=(),
            holm_adjustments=(),
            breached_metrics=(),
            blockers=tuple(dict.fromkeys(blockers)),
        )


def r2_trial_assessment_hash(assessment: R2ExplanatoryTrialAssessment) -> str:
    """Seal a trial assessment without changing its research-only authority."""

    return _hash(
        {
            "schema": "r2-explanatory-trial-assessment.v1",
            "assessed_at": _utc(assessment.assessed_at),
            "status": assessment.status.value,
            "policy_ref": (
                None if assessment.policy_ref is None else assessment.policy_ref.payload()
            ),
            "audit_outcome_ref": (
                None
                if assessment.audit_outcome_ref is None
                else assessment.audit_outcome_ref.payload()
            ),
            "metrics": [
                item.payload()
                for item in sorted(
                    assessment.metrics,
                    key=lambda value: (value.cycle_id, value.metric_key.value),
                )
            ],
            "holm_adjustments": [item.payload() for item in assessment.holm_adjustments],
            "breached_metrics": sorted(item.value for item in assessment.breached_metrics),
            "blockers": [item.value for item in assessment.blockers],
            "research_only": assessment.research_only,
            "must_not_use_as_predictive_signal": (assessment.must_not_use_as_predictive_signal),
            "must_not_publish_current": assessment.must_not_publish_current,
            "must_not_use_for_decision": assessment.must_not_use_for_decision,
            "must_not_execute": assessment.must_not_execute,
            "is_attested_ready": assessment.is_attested_ready,
        }
    )


def _publication_blockers(
    *,
    evidence: R2CanonicalPublicationEvidence,
    expected_kind: R2PublicationKind,
    expected_seal: R2PublicationProjectionSeal,
    known_by: datetime,
    as_of: datetime,
) -> list[R2TrialBlockerCode]:
    blockers: list[R2TrialBlockerCode] = []
    if evidence.kind is not expected_kind:
        blockers.append(
            R2TrialBlockerCode.TAXONOMY_PUBLICATION_INVALID
            if expected_kind is R2PublicationKind.TAXONOMY
            else R2TrialBlockerCode.CALENDAR_PUBLICATION_INVALID
        )
    if (
        evidence.reference != expected_seal.reference
        or evidence.content_hash != expected_seal.projection_hash
        or evidence.available_at != expected_seal.available_at
        or evidence.recorded_at != expected_seal.recorded_at
        or evidence.content_hash != r2_publication_evidence_hash(evidence)
    ):
        blockers.append(R2TrialBlockerCode.PUBLICATION_REPLACED)
    if evidence.available_at > known_by or evidence.recorded_at > known_by:
        blockers.append(R2TrialBlockerCode.SELECTION_LEAKAGE)
    if evidence.available_at > as_of or evidence.recorded_at > as_of:
        blockers.append(R2TrialBlockerCode.PUBLICATION_FROM_FUTURE)
    elif not evidence.is_active_at(as_of):
        blockers.append(R2TrialBlockerCode.PUBLICATION_STALE)
    return blockers


def _cycle_blockers(
    *,
    policy: R2MarketStructureTrialPolicy,
    cycle: R2MarketCycleDefinition,
    evidence: R2CyclePITEvidence,
    as_of: datetime,
) -> list[R2TrialBlockerCode]:
    blockers: list[R2TrialBlockerCode] = []
    if evidence.reference != cycle.evidence_ref or evidence.cycle_id != cycle.cycle_id:
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_REPLACED)
    if evidence.content_hash != r2_cycle_pit_evidence_hash(evidence):
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_REPLACED)
    if evidence.source_owner != policy.expected_cycle_evidence_owner:
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID)
    if (
        evidence.taxonomy_publication_ref != policy.taxonomy_publication_ref
        or evidence.calendar_publication_ref != policy.calendar_publication_ref
    ):
        blockers.append(R2TrialBlockerCode.PUBLICATION_REPLACED)
    if (
        evidence.available_at > policy.selection_as_of
        or evidence.recorded_at > policy.selection_as_of
        or any(item.available_at > policy.selection_as_of for item in evidence.samples)
    ):
        blockers.append(R2TrialBlockerCode.SELECTION_LEAKAGE)
    if (
        evidence.observed_at > as_of
        or evidence.available_at > as_of
        or evidence.recorded_at > as_of
        or any(item.available_at > as_of for item in evidence.samples)
    ):
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_FROM_FUTURE)
    elif not evidence.is_active_at(as_of):
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_STALE)
    period_by_id = {item.period_id: item for item in policy.expected_periods}
    semantics_by_id = {
        (item.series_code, item.series_version): item for item in policy.measure_semantics
    }
    expected_entry_by_cell = {
        (item.period_id, item.series_code, item.series_version): item
        for item in policy.expected_series_period_entries
    }
    expected_cells = {
        (period_id, series_code, series_version)
        for period_id in cycle.expected_period_ids
        for series_code, series_version in semantics_by_id
    }
    actual_cells = {
        (item.period_id, item.series_code, item.series_version) for item in evidence.samples
    }
    if actual_cells != expected_cells:
        blockers.append(R2TrialBlockerCode.CYCLE_PERIOD_INCOMPLETE)
    if evidence.observed_at < cycle.cycle_end:
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID)
    for sample in evidence.samples:
        semantic = semantics_by_id.get((sample.series_code, sample.series_version))
        expected_entry = expected_entry_by_cell.get(
            (sample.period_id, sample.series_code, sample.series_version)
        )
        if sample.period_id not in period_by_id:
            blockers.append(R2TrialBlockerCode.CYCLE_PERIOD_INCOMPLETE)
        else:
            period = period_by_id[sample.period_id]
            if (
                sample.available_at < period.period_end
                or sample.available_at > evidence.available_at
            ):
                blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID)
        if semantic is None or (
            sample.measure_kind is not semantic.measure_kind
            or sample.is_proxy is not semantic.is_proxy
        ):
            blockers.append(R2TrialBlockerCode.MEASURE_SEMANTICS_MISMATCH)
        elif sample.unit != semantic.unit:
            blockers.append(R2TrialBlockerCode.UNIT_MISMATCH)
        if expected_entry is None:
            blockers.append(R2TrialBlockerCode.CYCLE_PERIOD_INCOMPLETE)
            continue
        expected_refs = set(expected_entry.expected_observation_refs)
        actual_refs = set(sample.observation_refs)
        if not actual_refs.issubset(expected_refs):
            blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
        if sample.pit_manifest_ref != derive_r2_pit_manifest_ref(
            period_id=sample.period_id,
            series_code=sample.series_code,
            series_version=sample.series_version,
            observation_refs=sample.observation_refs,
        ):
            blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_INVALID)
        if sample.observation_count < policy.minimum_observations_per_series_period:
            blockers.append(R2TrialBlockerCode.CYCLE_PERIOD_INCOMPLETE)
        if sample.observation_count > len(expected_entry.expected_observation_refs):
            blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
    return blockers


def _cycle_denominators(
    *,
    policy: R2MarketStructureTrialPolicy,
    evidence: R2CyclePITEvidence,
) -> tuple[int, int]:
    expected_entry_by_cell = {
        (item.period_id, item.series_code, item.series_version): item
        for item in policy.expected_series_period_entries
    }
    observed = sum(item.observation_count for item in evidence.samples)
    expected = sum(
        len(
            expected_entry_by_cell[
                (item.period_id, item.series_code, item.series_version)
            ].expected_observation_refs
        )
        for item in evidence.samples
        if (item.period_id, item.series_code, item.series_version) in expected_entry_by_cell
    )
    return observed, expected


def _audit_blockers(
    *,
    policy: R2MarketStructureTrialPolicy,
    cycles: tuple[R2CyclePITEvidence, ...],
    outcome: R2AuditExplanatoryOutcome,
    as_of: datetime,
) -> list[R2TrialBlockerCode]:
    blockers: list[R2TrialBlockerCode] = []
    if outcome.content_hash != r2_audit_outcome_hash(outcome):
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED)
    expected_outcome_id = derive_r2_audit_outcome_id(
        policy_ref=policy.reference,
        audit_plan_ref=policy.audit_plan_ref,
        cycle_evidence_refs=tuple(item.reference for item in cycles),
    )
    if (
        outcome.outcome_id != expected_outcome_id
        or outcome.outcome_version != R2_AUDIT_OUTCOME_VERSION
    ):
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED)
    if outcome.policy_ref != policy.reference or outcome.audit_plan_ref != policy.audit_plan_ref:
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED)
    if outcome.source_owner != policy.expected_audit_owner:
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_INVALID)
    if (
        outcome.taxonomy_publication_ref != policy.taxonomy_publication_ref
        or outcome.calendar_publication_ref != policy.calendar_publication_ref
        or outcome.cycle_evidence_refs != tuple(item.reference for item in cycles)
    ):
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED)
    latest_cycle_knowledge = max(item.recorded_at for item in cycles)
    if (
        outcome.selection_as_of != policy.selection_as_of
        or outcome.observed_at < policy.selection_as_of
        or outcome.observed_at <= latest_cycle_knowledge
        or outcome.recorded_at <= policy.selection_as_of
    ):
        blockers.append(R2TrialBlockerCode.SELECTION_LEAKAGE)
    if outcome.observed_at > as_of or outcome.available_at > as_of or outcome.recorded_at > as_of:
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_FROM_FUTURE)
    elif not outcome.is_active_at(as_of):
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_STALE)
    expected_metric_ids = {
        (cycle.cycle_id, metric_key)
        for cycle in policy.cycles
        for metric_key in REQUIRED_R2_EXPLANATORY_METRICS
    }
    actual_metric_ids = {(item.cycle_id, item.metric_key) for item in outcome.metrics}
    if actual_metric_ids != expected_metric_ids:
        blockers.append(R2TrialBlockerCode.METRIC_SET_INVALID)
    rules = {item.metric_key: item for item in policy.metric_rules}
    cycle_by_id = {item.cycle_id: item for item in cycles}
    incremental_count = 0
    for metric in outcome.metrics:
        rule = rules[metric.metric_key]
        cycle_evidence = cycle_by_id.get(metric.cycle_id)
        if not _r2_explanatory_metric_domain_is_valid(
            metric_key=metric.metric_key,
            unit=metric.unit,
            value=metric.value,
        ):
            blockers.append(R2TrialBlockerCode.METRIC_DOMAIN_INVALID)
        if metric.unit != rule.unit:
            blockers.append(R2TrialBlockerCode.UNIT_MISMATCH)
        if cycle_evidence is None:
            blockers.append(R2TrialBlockerCode.METRIC_SET_INVALID)
            continue
        cycle_definition = next(item for item in policy.cycles if item.cycle_id == metric.cycle_id)
        if metric.metric_key is R2ExplanatoryMetricKey.COVERAGE_RATIO:
            observed, expected = _cycle_denominators(
                policy=policy,
                evidence=cycle_evidence,
            )
            if (
                expected < 1
                or metric.sample_count != observed
                or metric.expected_sample_count != expected
                or metric.value != Decimal(observed) / Decimal(expected)
            ):
                blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
        elif metric.sample_count != len(
            cycle_definition.expected_period_ids
        ) or metric.expected_sample_count != len(cycle_definition.expected_period_ids):
            blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
        if metric.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER:
            incremental_count += 1
            if (
                metric.test_family_id != policy.multiple_testing.family_id
                or metric.multiple_testing_method_version != policy.multiple_testing.method_version
            ):
                blockers.append(R2TrialBlockerCode.MULTIPLE_TEST_BINDING_INVALID)
    if incremental_count != policy.multiple_testing.hypothesis_count:
        blockers.append(R2TrialBlockerCode.MULTIPLE_TEST_BINDING_INVALID)
    return blockers


def evaluate_r2_explanatory_trial(
    *,
    policy: R2MarketStructureTrialPolicy,
    taxonomy_publication: R2CanonicalPublicationEvidence,
    calendar_publication: R2CanonicalPublicationEvidence,
    cycle_evidence: tuple[R2CyclePITEvidence, ...],
    audit_outcome: R2AuditExplanatoryOutcome,
    assessed_at: datetime,
) -> R2ExplanatoryTrialAssessment:
    """Validate exact owner evidence and assess explanatory thresholds only."""

    _require_aware(assessed_at, "evaluate_r2_explanatory_trial.assessed_at")
    blockers: list[R2TrialBlockerCode] = []
    if policy.content_hash != r2_trial_policy_hash(policy):
        blockers.append(R2TrialBlockerCode.POLICY_HASH_MISMATCH)
    if policy.registered_at > assessed_at:
        blockers.append(R2TrialBlockerCode.POLICY_FROM_FUTURE)
    if not policy.registered_at < policy.selection_as_of:
        blockers.append(R2TrialBlockerCode.SELECTION_LEAKAGE)
    if not policy.is_active_at(assessed_at):
        blockers.append(R2TrialBlockerCode.POLICY_INACTIVE)
    if any(
        not _r2_explanatory_metric_domain_is_valid(
            metric_key=rule.metric_key,
            unit=rule.unit,
            value=threshold,
        )
        for rule in policy.metric_rules
        for threshold in (rule.trial_threshold, rule.monitoring_threshold)
    ):
        blockers.append(R2TrialBlockerCode.METRIC_DOMAIN_INVALID)
    blockers.extend(
        _publication_blockers(
            evidence=taxonomy_publication,
            expected_kind=R2PublicationKind.TAXONOMY,
            expected_seal=policy.taxonomy_projection_seal,
            known_by=policy.registered_at,
            as_of=assessed_at,
        )
    )
    blockers.extend(
        _publication_blockers(
            evidence=calendar_publication,
            expected_kind=R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
            expected_seal=policy.calendar_projection_seal,
            known_by=policy.registered_at,
            as_of=assessed_at,
        )
    )
    if taxonomy_publication.measure_semantics != policy.measure_semantics:
        blockers.append(R2TrialBlockerCode.MEASURE_SEMANTICS_MISMATCH)
    if (
        calendar_publication.expected_periods != policy.expected_periods
        or calendar_publication.expected_series_period_entries
        != policy.expected_series_period_entries
    ):
        blockers.append(R2TrialBlockerCode.PUBLICATION_REPLACED)
    cycle_by_id = {item.cycle_id: item for item in cycle_evidence}
    if len(cycle_by_id) != 2 or set(cycle_by_id) != {item.cycle_id for item in policy.cycles}:
        blockers.append(R2TrialBlockerCode.CYCLE_EVIDENCE_MISSING)
    ordered_cycles: list[R2CyclePITEvidence] = []
    for cycle in policy.cycles:
        evidence = cycle_by_id.get(cycle.cycle_id)
        if evidence is None:
            continue
        ordered_cycles.append(evidence)
        blockers.extend(
            _cycle_blockers(
                policy=policy,
                cycle=cycle,
                evidence=evidence,
                as_of=assessed_at,
            )
        )
    if len(ordered_cycles) == 2:
        blockers.extend(
            _audit_blockers(
                policy=policy,
                cycles=tuple(ordered_cycles),
                outcome=audit_outcome,
                as_of=assessed_at,
            )
        )
    if blockers:
        return R2ExplanatoryTrialAssessment.blocked(
            assessed_at=assessed_at,
            policy_ref=policy.reference,
            blockers=tuple(blockers),
        )
    holm_adjustments = derive_r2_holm_adjustments(
        audit_outcome.metrics,
        policy.multiple_testing,
    )
    adjusted_by_hypothesis = {
        item.hypothesis_id: item.adjusted_p_value for item in holm_adjustments
    }
    rules = {item.metric_key: item for item in policy.metric_rules}
    breached: set[R2ExplanatoryMetricKey] = set()
    for metric in audit_outcome.metrics:
        if not rules[metric.metric_key].is_satisfied(metric.value):
            breached.add(metric.metric_key)
        if (
            metric.metric_key is R2ExplanatoryMetricKey.INCREMENTAL_EXPLANATORY_POWER
            and adjusted_by_hypothesis[f"{metric.cycle_id}:{metric.metric_key.value}"]
            > policy.multiple_testing.maximum_adjusted_p_value
        ):
            breached.add(metric.metric_key)
    return R2ExplanatoryTrialAssessment(
        assessed_at=assessed_at,
        status=R2TrialStatus.BREACHED if breached else R2TrialStatus.PASSED,
        policy_ref=policy.reference,
        audit_outcome_ref=audit_outcome.reference,
        metrics=audit_outcome.metrics,
        holm_adjustments=holm_adjustments,
        breached_metrics=tuple(sorted(breached, key=lambda item: item.value)),
        blockers=(),
    )


@dataclass(frozen=True)
class R2MonitoringMetricObservation:
    """One Audit-owned raw explanatory metric for a monitoring period."""

    metric_key: R2ExplanatoryMetricKey
    unit: str
    value: Decimal
    sample_count: int
    expected_sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.metric_key, R2ExplanatoryMetricKey):
            raise ValueError("R2 monitoring metric_key is invalid")
        _require_token(self.unit, "R2MonitoringMetricObservation.unit")
        _require_r2_explanatory_metric_domain(
            metric_key=self.metric_key,
            unit=self.unit,
            value=self.value,
            field_name="R2MonitoringMetricObservation.value",
        )
        if (
            isinstance(self.sample_count, bool)
            or self.sample_count < 0
            or isinstance(self.expected_sample_count, bool)
            or self.expected_sample_count < 1
            or self.sample_count > self.expected_sample_count
        ):
            raise ValueError("R2 monitoring metric sample denominator is invalid")

    def payload(self) -> dict[str, object]:
        """Return raw metric content without a caller-declared status."""

        return {
            "metric_key": self.metric_key.value,
            "unit": self.unit,
            "value": _decimal(self.value),
            "sample_count": self.sample_count,
            "expected_sample_count": self.expected_sample_count,
        }


R2_MONITORING_FACT_VERSION = "r2-monitoring-fact.v1"


def derive_r2_monitoring_fact_id(
    *,
    policy_ref: R2EvidenceRef,
    period_id: str,
) -> str:
    """Derive the sole monitoring fact identity for a policy/period pair."""

    _require_token(period_id, "derive_r2_monitoring_fact_id.period_id")
    return f"r2-monitoring-fact:{_hash({'schema': R2_MONITORING_FACT_VERSION, 'policy_ref': policy_ref.payload(), 'period_id': period_id})}"


@dataclass(frozen=True)
class R2MonitoringRawFact:
    """Hash-sealed owner fact with observation, knowledge, record and validity clocks."""

    fact_id: str
    fact_version: str
    source_owner: str
    policy_ref: R2EvidenceRef
    taxonomy_publication_ref: R2PublicationRef
    calendar_publication_ref: R2PublicationRef
    period_id: str
    period_start: datetime
    period_end: datetime
    metrics: tuple[R2MonitoringMetricObservation, ...]
    label_protocol_version: str
    observed_label_set_hash: str
    observed_at: datetime
    available_at: datetime
    recorded_at: datetime
    valid_from: datetime
    valid_until: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.fact_id, "fact_id"),
            (self.fact_version, "fact_version"),
            (self.source_owner, "source_owner"),
            (self.period_id, "period_id"),
            (self.label_protocol_version, "label_protocol_version"),
        ):
            _require_token(value, f"R2MonitoringRawFact.{name}")
        _require_hash(
            self.observed_label_set_hash,
            "R2MonitoringRawFact.observed_label_set_hash",
        )
        _require_aware(self.period_start, "R2MonitoringRawFact.period_start")
        _require_aware(self.period_end, "R2MonitoringRawFact.period_end")
        if self.period_start >= self.period_end:
            raise ValueError("R2 monitoring period must be non-empty")
        metric_keys = tuple(item.metric_key for item in self.metrics)
        if len(metric_keys) != len(set(metric_keys)) or frozenset(metric_keys) != (
            REQUIRED_R2_EXPLANATORY_METRICS
        ):
            raise ValueError("R2 monitoring fact must carry each raw metric exactly")
        for clock_value, name in (
            (self.observed_at, "observed_at"),
            (self.available_at, "available_at"),
            (self.recorded_at, "recorded_at"),
            (self.valid_from, "valid_from"),
            (self.valid_until, "valid_until"),
        ):
            _require_aware(clock_value, f"R2MonitoringRawFact.{name}")
        if not self.observed_at <= self.available_at <= self.recorded_at:
            raise ValueError("R2 monitoring fact knowledge clocks are invalid")
        if self.valid_from >= self.valid_until:
            raise ValueError("R2 monitoring fact validity clocks are invalid")
        object.__setattr__(self, "content_hash", r2_monitoring_fact_hash(self))

    @property
    def reference(self) -> R2EvidenceRef:
        """Return exact content-addressed raw-fact identity."""

        return R2EvidenceRef(self.fact_id, self.fact_version, self.content_hash)

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether the raw fact is known and valid."""

        _require_aware(as_of, "R2MonitoringRawFact.as_of")
        return self.recorded_at <= as_of and self.valid_from <= as_of < self.valid_until


def r2_monitoring_fact_hash(fact: R2MonitoringRawFact) -> str:
    """Recompute one raw monitoring fact seal."""

    return _hash(
        {
            "schema": "r2-market-structure-monitoring-fact.v1",
            "fact_id": fact.fact_id,
            "fact_version": fact.fact_version,
            "source_owner": fact.source_owner,
            "policy_ref": fact.policy_ref.payload(),
            "taxonomy_publication_ref": fact.taxonomy_publication_ref.payload(),
            "calendar_publication_ref": fact.calendar_publication_ref.payload(),
            "period_id": fact.period_id,
            "period_start": _utc(fact.period_start),
            "period_end": _utc(fact.period_end),
            "metrics": [
                item.payload()
                for item in sorted(fact.metrics, key=lambda value: value.metric_key.value)
            ],
            "label_protocol_version": fact.label_protocol_version,
            "observed_label_set_hash": fact.observed_label_set_hash.lower(),
            "observed_at": _utc(fact.observed_at),
            "available_at": _utc(fact.available_at),
            "recorded_at": _utc(fact.recorded_at),
            "valid_from": _utc(fact.valid_from),
            "valid_until": _utc(fact.valid_until),
        }
    )


@dataclass(frozen=True)
class R2MonitoringAssessment:
    """Derived monitoring assessment that can request manual review only."""

    assessed_at: datetime
    status: R2MonitoringStatus
    policy_ref: R2EvidenceRef | None
    trial_assessment_hash: str | None
    fact_refs: tuple[R2EvidenceRef, ...]
    current_breaches: tuple[R2ExplanatoryMetricKey, ...]
    review_reasons: tuple[str, ...]
    blockers: tuple[R2TrialBlockerCode, ...]
    content_hash: str = field(init=False)
    retirement_review_required: bool = False
    automatic_retirement: bool = False
    research_only: bool = True
    must_not_use_as_predictive_signal: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        _require_aware(self.assessed_at, "R2MonitoringAssessment.assessed_at")
        if not isinstance(self.status, R2MonitoringStatus):
            raise ValueError("R2 monitoring status is invalid")
        if self.trial_assessment_hash is not None:
            _require_hash(
                self.trial_assessment_hash,
                "R2MonitoringAssessment.trial_assessment_hash",
            )
        if self.status is R2MonitoringStatus.BLOCKED:
            if not self.blockers or self.fact_refs or self.retirement_review_required:
                raise ValueError("blocked R2 monitoring assessment requires blockers only")
        elif self.blockers or self.policy_ref is None or self.trial_assessment_hash is None:
            raise ValueError("evaluated R2 monitoring assessment cannot contain blockers")
        expected_review = self.status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
        if self.retirement_review_required != expected_review:
            raise ValueError("R2 monitoring review flag conflicts with status")
        if self.automatic_retirement:
            raise ValueError("R2 Phase A monitoring cannot retire automatically")
        if not all(
            (
                self.research_only,
                self.must_not_use_as_predictive_signal,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("R2 monitoring cannot authorize production use")
        object.__setattr__(self, "content_hash", r2_monitoring_assessment_hash(self))

    @classmethod
    def blocked(
        cls,
        *,
        assessed_at: datetime,
        blockers: tuple[R2TrialBlockerCode, ...],
        policy_ref: R2EvidenceRef | None = None,
    ) -> R2MonitoringAssessment:
        """Build one stable fail-closed monitoring assessment."""

        return cls(
            assessed_at=assessed_at,
            status=R2MonitoringStatus.BLOCKED,
            policy_ref=policy_ref,
            trial_assessment_hash=None,
            fact_refs=(),
            current_breaches=(),
            review_reasons=(),
            blockers=tuple(dict.fromkeys(blockers)),
        )


def r2_monitoring_assessment_hash(assessment: R2MonitoringAssessment) -> str:
    """Seal a manual-review-only monitoring assessment."""

    return _hash(
        {
            "schema": "r2-market-structure-monitoring-assessment.v1",
            "assessed_at": _utc(assessment.assessed_at),
            "status": assessment.status.value,
            "policy_ref": (
                None if assessment.policy_ref is None else assessment.policy_ref.payload()
            ),
            "trial_assessment_hash": assessment.trial_assessment_hash,
            "fact_refs": [item.payload() for item in assessment.fact_refs],
            "current_breaches": sorted(item.value for item in assessment.current_breaches),
            "review_reasons": list(assessment.review_reasons),
            "blockers": [item.value for item in assessment.blockers],
            "retirement_review_required": assessment.retirement_review_required,
            "automatic_retirement": assessment.automatic_retirement,
            "research_only": assessment.research_only,
            "must_not_use_as_predictive_signal": (assessment.must_not_use_as_predictive_signal),
            "must_not_publish_current": assessment.must_not_publish_current,
            "must_not_use_for_decision": assessment.must_not_use_for_decision,
            "must_not_execute": assessment.must_not_execute,
        }
    )


def evaluate_r2_monitoring(
    *,
    policy: R2MarketStructureTrialPolicy,
    taxonomy_publication: R2CanonicalPublicationEvidence,
    calendar_publication: R2CanonicalPublicationEvidence,
    trial_assessment: R2ExplanatoryTrialAssessment,
    facts: tuple[R2MonitoringRawFact, ...],
    assessed_at: datetime,
) -> R2MonitoringAssessment:
    """Evaluate fresh raw facts and derive breach/manual-review status only."""

    _require_aware(assessed_at, "evaluate_r2_monitoring.assessed_at")
    blockers: list[R2TrialBlockerCode] = []
    if policy.content_hash != r2_trial_policy_hash(policy):
        blockers.append(R2TrialBlockerCode.POLICY_HASH_MISMATCH)
    if not policy.is_active_at(assessed_at):
        blockers.append(R2TrialBlockerCode.POLICY_INACTIVE)
    blockers.extend(
        _publication_blockers(
            evidence=taxonomy_publication,
            expected_kind=R2PublicationKind.TAXONOMY,
            expected_seal=policy.taxonomy_projection_seal,
            known_by=policy.registered_at,
            as_of=assessed_at,
        )
    )
    blockers.extend(
        _publication_blockers(
            evidence=calendar_publication,
            expected_kind=R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
            expected_seal=policy.calendar_projection_seal,
            known_by=policy.registered_at,
            as_of=assessed_at,
        )
    )
    if (
        trial_assessment.status is not R2TrialStatus.PASSED
        or trial_assessment.policy_ref != policy.reference
        or trial_assessment.content_hash != r2_trial_assessment_hash(trial_assessment)
    ):
        blockers.append(R2TrialBlockerCode.AUDIT_OUTCOME_INVALID)
    if not facts:
        blockers.append(R2TrialBlockerCode.MONITORING_FACTS_MISSING)
    ordered = tuple(sorted(facts, key=lambda item: (item.period_start, item.period_end)))
    identities = tuple((item.fact_id, item.fact_version) for item in ordered)
    period_ids = tuple(item.period_id for item in ordered)
    if len(identities) != len(set(identities)) or len(period_ids) != len(set(period_ids)):
        blockers.append(R2TrialBlockerCode.MONITORING_PERIOD_INVALID)
    if any(
        current.period_start < previous.period_end
        for previous, current in zip(ordered, ordered[1:], strict=False)
    ):
        blockers.append(R2TrialBlockerCode.MONITORING_PERIOD_OVERLAP)
    calendar_by_id = {item.period_id: item for item in policy.expected_periods}
    completed_monitoring_period_ids = tuple(
        item.period_id
        for item in policy.expected_periods
        if item.period_start >= policy.selection_as_of and item.period_end <= assessed_at
    )
    if period_ids != completed_monitoring_period_ids:
        blockers.append(R2TrialBlockerCode.MONITORING_PERIOD_INVALID)
    rules = {item.metric_key: item for item in policy.metric_rules}
    if any(
        not _r2_explanatory_metric_domain_is_valid(
            metric_key=rule.metric_key,
            unit=rule.unit,
            value=threshold,
        )
        for rule in policy.metric_rules
        for threshold in (rule.trial_threshold, rule.monitoring_threshold)
    ):
        blockers.append(R2TrialBlockerCode.METRIC_DOMAIN_INVALID)
    for fact in ordered:
        if fact.content_hash != r2_monitoring_fact_hash(fact):
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_REPLACED)
        if (
            fact.source_owner != policy.expected_audit_owner
            or fact.policy_ref != policy.reference
            or fact.taxonomy_publication_ref != policy.taxonomy_publication_ref
            or fact.calendar_publication_ref != policy.calendar_publication_ref
        ):
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_REPLACED)
        expected_fact_id = derive_r2_monitoring_fact_id(
            policy_ref=policy.reference,
            period_id=fact.period_id,
        )
        if fact.fact_id != expected_fact_id or fact.fact_version != R2_MONITORING_FACT_VERSION:
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_REPLACED)
        period = calendar_by_id.get(fact.period_id)
        if (
            period is None
            or period.period_start != fact.period_start
            or period.period_end != fact.period_end
            or fact.period_start < policy.selection_as_of
            or fact.observed_at > fact.period_end
            or fact.available_at < fact.period_end
            or fact.recorded_at < fact.period_end
        ):
            blockers.append(R2TrialBlockerCode.MONITORING_PERIOD_INVALID)
        if (
            fact.observed_at > assessed_at
            or fact.available_at > assessed_at
            or fact.recorded_at > assessed_at
        ):
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_FROM_FUTURE)
        elif not fact.is_active_at(assessed_at):
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_STALE)
        if fact.label_protocol_version != policy.label_protocol_version:
            blockers.append(R2TrialBlockerCode.LABEL_PROTOCOL_MISMATCH)
        for metric in fact.metrics:
            rule = rules[metric.metric_key]
            if not _r2_explanatory_metric_domain_is_valid(
                metric_key=metric.metric_key,
                unit=metric.unit,
                value=metric.value,
            ):
                blockers.append(R2TrialBlockerCode.METRIC_DOMAIN_INVALID)
            if metric.unit != rule.unit:
                blockers.append(R2TrialBlockerCode.UNIT_MISMATCH)
            if (
                metric.sample_count < policy.minimum_monitoring_sample_count
                or metric.expected_sample_count < policy.minimum_monitoring_sample_count
            ):
                blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
            if (
                metric.metric_key is R2ExplanatoryMetricKey.COVERAGE_RATIO
                and metric.value
                != Decimal(metric.sample_count) / Decimal(metric.expected_sample_count)
            ):
                blockers.append(R2TrialBlockerCode.SAMPLE_DENOMINATOR_INVALID)
    if ordered:
        latest = ordered[-1]
        freshness_anchor = min(latest.period_end, latest.observed_at)
        age_seconds = Decimal(str((assessed_at - freshness_anchor).total_seconds()))
        if age_seconds < 0:
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_FROM_FUTURE)
        elif age_seconds > policy.maximum_monitoring_age_seconds:
            blockers.append(R2TrialBlockerCode.MONITORING_FACT_STALE)
    if blockers:
        return R2MonitoringAssessment.blocked(
            assessed_at=assessed_at,
            policy_ref=policy.reference,
            blockers=tuple(blockers),
        )
    assert ordered
    current_breaches = {
        item.metric_key
        for item in ordered[-1].metrics
        if not rules[item.metric_key].is_satisfied(item.value, monitoring=True)
    }
    review_reasons: list[str] = []
    if any(fact.observed_label_set_hash != policy.expected_label_set_hash for fact in ordered):
        review_reasons.append("label_drift")
    for metric_key, rule in rules.items():
        consecutive = 0
        for fact in reversed(ordered):
            value = next(item.value for item in fact.metrics if item.metric_key is metric_key)
            if rule.is_satisfied(value, monitoring=True):
                break
            consecutive += 1
        if consecutive >= rule.retirement_review_consecutive_breaches:
            review_reasons.append(f"consecutive_breach:{metric_key.value}")
    review_reasons = list(dict.fromkeys(review_reasons))
    if review_reasons:
        status = R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED
    elif current_breaches:
        status = R2MonitoringStatus.BREACHED
    else:
        status = R2MonitoringStatus.HEALTHY
    return R2MonitoringAssessment(
        assessed_at=assessed_at,
        status=status,
        policy_ref=policy.reference,
        trial_assessment_hash=trial_assessment.content_hash,
        fact_refs=tuple(item.reference for item in ordered),
        current_breaches=tuple(sorted(current_breaches, key=lambda item: item.value)),
        review_reasons=tuple(review_reasons),
        blockers=(),
        retirement_review_required=(status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED),
    )


__all__ = [
    "REQUIRED_R2_EXPLANATORY_METRICS",
    "R2_AUDIT_OUTCOME_VERSION",
    "R2_MONITORING_FACT_VERSION",
    "R2_PIT_MANIFEST_VERSION",
    "R2AuditExplanatoryOutcome",
    "R2AuditMetric",
    "R2CanonicalPublicationEvidence",
    "R2CyclePITEvidence",
    "R2EvidenceRef",
    "R2ExpectedPeriod",
    "R2ExpectedSeriesPeriodEntry",
    "R2ExplanatoryMetricKey",
    "R2ExplanatoryTrialAssessment",
    "R2HolmAdjustedPValue",
    "R2MarketCycleDefinition",
    "R2MarketStructureTrialPolicy",
    "R2MeasureKind",
    "R2MeasureSemantic",
    "R2MetricRule",
    "R2MonitoringAssessment",
    "R2MonitoringMetricObservation",
    "R2MonitoringRawFact",
    "R2MonitoringStatus",
    "R2MultipleTestingRule",
    "R2PublicationKind",
    "R2PublicationProjectionSeal",
    "R2PublicationRef",
    "R2SeriesPeriodSample",
    "R2ThresholdDirection",
    "R2TrialBlockerCode",
    "R2TrialStatus",
    "derive_r2_audit_outcome_id",
    "derive_r2_holm_adjustments",
    "derive_r2_monitoring_fact_id",
    "derive_r2_pit_manifest_ref",
    "evaluate_r2_explanatory_trial",
    "evaluate_r2_monitoring",
    "r2_audit_outcome_hash",
    "r2_cycle_pit_evidence_hash",
    "r2_monitoring_assessment_hash",
    "r2_monitoring_fact_hash",
    "r2_publication_evidence_hash",
    "r2_trial_assessment_hash",
    "r2_trial_policy_hash",
]
