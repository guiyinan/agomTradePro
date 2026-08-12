"""R2 explanatory trial evaluation and monitoring assessments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from apps.research.domain.r2_market_structure_trial_contracts import (
    REQUIRED_R2_EXPLANATORY_METRICS,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExplanatoryMetricKey,
    R2MarketCycleDefinition,
    R2MarketStructureTrialPolicy,
    R2MonitoringStatus,
    R2MultipleTestingRule,
    R2PublicationKind,
    R2PublicationProjectionSeal,
    R2PublicationRef,
    R2TrialBlockerCode,
    R2TrialStatus,
    _decimal,
    _hash,
    _r2_explanatory_metric_domain_is_valid,
    _require_aware,
    _require_finite,
    _require_hash,
    _require_r2_explanatory_metric_domain,
    _require_token,
    _utc,
    derive_r2_pit_manifest_ref,
    r2_cycle_pit_evidence_hash,
    r2_publication_evidence_hash,
    r2_trial_policy_hash,
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
    "R2_AUDIT_OUTCOME_VERSION",
    "R2_MONITORING_FACT_VERSION",
    "R2AuditExplanatoryOutcome",
    "R2AuditMetric",
    "R2ExplanatoryTrialAssessment",
    "R2HolmAdjustedPValue",
    "R2MonitoringAssessment",
    "R2MonitoringMetricObservation",
    "R2MonitoringRawFact",
    "derive_r2_audit_outcome_id",
    "derive_r2_holm_adjustments",
    "derive_r2_monitoring_fact_id",
    "evaluate_r2_explanatory_trial",
    "evaluate_r2_monitoring",
    "r2_audit_outcome_hash",
    "r2_monitoring_assessment_hash",
    "r2_monitoring_fact_hash",
    "r2_trial_assessment_hash",
]
