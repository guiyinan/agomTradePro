"""Fail-closed calibration metrics over immutable scenario ledger outcomes."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from apps.research.domain.scenario_probability_contracts import (
    CalibrationBinResult,
    CalibrationBlocker,
    ForecastLedgerOutcomeObservation,
    MulticlassCalibrationMetrics,
    ProbabilitySourceCalibrationReport,
    ResearchEvidenceStatus,
    RevisionCalibrationMetrics,
    ScenarioCalibrationReport,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
    probability_source_calibration_hash,
)
from apps.research.domain.scenario_research_hashing import hash_components
from apps.signal.domain.forecast_scenario_evidence import ScenarioProbabilitySource

_REPORT_VERSION = "scenario-calibration-report.v1"
_SOURCE_REPORT_VERSION = "scenario-source-calibration.v1"


def evaluate_scenario_probability_calibration(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    observations: tuple[ForecastLedgerOutcomeObservation, ...],
    evaluated_at: datetime,
) -> ScenarioCalibrationReport:
    """Evaluate source-separated Brier metrics only after every policy gate passes."""

    _require_aware(evaluated_at, "evaluated_at")
    _validate_observation_scope(
        scope=scope,
        policy=policy,
        observations=observations,
        evaluated_at=evaluated_at,
    )
    policy_active = policy.is_active(evaluated_at)
    subjective = _evaluate_source(
        scope=scope,
        policy=policy,
        observations=observations,
        evaluated_at=evaluated_at,
        source=ScenarioProbabilitySource.SUBJECTIVE,
        policy_active=policy_active,
    )
    model_inferred = _evaluate_source(
        scope=scope,
        policy=policy,
        observations=observations,
        evaluated_at=evaluated_at,
        source=ScenarioProbabilitySource.MODEL_INFERRED,
        policy_active=policy_active,
    )
    content_hash = hash_components(
        _REPORT_VERSION,
        policy.policy_version,
        scope.content_hash,
        evaluated_at.isoformat(),
        subjective.content_hash,
        model_inferred.content_hash,
        "False",
        "True",
        "True",
    )
    return ScenarioCalibrationReport(
        report_version=_REPORT_VERSION,
        policy_version=policy.policy_version,
        scope_hash=scope.content_hash,
        evaluated_at=evaluated_at,
        subjective=subjective,
        model_inferred=model_inferred,
        trains_probability_model=False,
        research_only=True,
        must_not_use_for_decision=True,
        content_hash=content_hash,
    )


def _evaluate_source(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    observations: tuple[ForecastLedgerOutcomeObservation, ...],
    evaluated_at: datetime,
    source: ScenarioProbabilitySource,
    policy_active: bool,
) -> ProbabilitySourceCalibrationReport:
    source_rows = tuple(
        observation
        for observation in observations
        if observation.probability_for(source) is not None
    )
    blockers: list[CalibrationBlocker] = []
    blocked = False
    if not policy_active:
        blocked = True
        blockers.append(
            CalibrationBlocker(
                "scenario_calibration.policy.inactive",
                "scenario probability research policy is not active",
            )
        )
    if not source_rows:
        blockers.append(
            CalibrationBlocker(
                f"scenario_calibration.{source.value}.probability.missing",
                "no explicitly stored probability exists for this source",
            )
        )

    source_versions = {_source_version(row, source) for row in source_rows}
    if len(source_versions) > 1:
        blocked = True
        blockers.append(
            CalibrationBlocker(
                f"scenario_calibration.{source.value}.version.mixed",
                "one calibration run cannot mix probability source versions",
            )
        )
    if source is ScenarioProbabilitySource.MODEL_INFERRED:
        promotion_ids = {row.binding.model_promotion_decision_id for row in source_rows}
        if len(promotion_ids) > 1:
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.model_inferred.promotion.mixed",
                    "one model calibration run cannot mix promotion decisions",
                )
            )

    usable_by_revision: dict[UUID, tuple[ForecastLedgerOutcomeObservation, ...]] = {}
    for revision_id in scope.scenario_revision_ids:
        revision_rows = tuple(
            row for row in source_rows if row.binding.scenario_revision_id == revision_id
        )
        if len(revision_rows) < policy.minimum_forecasts_per_revision:
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.sample.forecasts_insufficient",
                    "forecast count is below the versioned policy minimum",
                    scenario_revision_id=revision_id,
                )
            )
        usable: list[ForecastLedgerOutcomeObservation] = []
        for row in revision_rows:
            if row.scenario_realized is None:
                continue
            assert row.outcome_recorded_at is not None
            assert row.outcome_evidence_valid_until is not None
            if (
                row.outcome_evidence_valid_until <= evaluated_at
                or row.outcome_recorded_at + policy.maximum_outcome_evidence_age <= evaluated_at
            ):
                blocked = True
                blockers.append(
                    CalibrationBlocker(
                        "scenario_calibration.outcome_evidence.expired",
                        "forecast outcome evidence has expired under the active policy",
                        scenario_revision_id=revision_id,
                        entry_id=row.entry_id,
                    )
                )
                continue
            usable.append(row)
        usable_rows = tuple(usable)
        usable_by_revision[revision_id] = usable_rows
        if len(usable_rows) < policy.minimum_resolved_outcomes_per_revision:
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.sample.outcomes_insufficient",
                    "resolved outcome count is below the versioned policy minimum",
                    scenario_revision_id=revision_id,
                )
            )
        coverage = _coverage(len(usable_rows), len(revision_rows))
        if coverage < policy.minimum_outcome_coverage:
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.sample.coverage_insufficient",
                    "outcome coverage is below the versioned policy minimum",
                    scenario_revision_id=revision_id,
                )
            )
        realized_count = sum(row.scenario_realized is True for row in usable_rows)
        not_realized_count = sum(row.scenario_realized is False for row in usable_rows)
        if (
            realized_count < policy.minimum_binary_class_observations
            or not_realized_count < policy.minimum_binary_class_observations
        ):
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.sample.binary_class_support_insufficient",
                    "realized and not-realized classes both require policy support",
                    scenario_revision_id=revision_id,
                )
            )

    multiclass_rows: tuple[tuple[ForecastLedgerOutcomeObservation, ...], ...] = ()
    multiclass_counts: tuple[tuple[UUID, int], ...] = ()
    if scope.scenario_set_revision_id is not None:
        multiclass_rows, multiclass_counts, multiclass_blockers, set_blocked = (
            _collect_multiclass_groups(
                scope=scope,
                policy=policy,
                source_rows=source_rows,
                evaluated_at=evaluated_at,
                source=source,
            )
        )
        blockers.extend(multiclass_blockers)
        blocked = blocked or set_blocked

    if blockers:
        status = (
            ResearchEvidenceStatus.BLOCKED
            if blocked
            else ResearchEvidenceStatus.INSUFFICIENT_EVIDENCE
        )
        revision_metrics: tuple[RevisionCalibrationMetrics, ...] = ()
        multiclass_metrics = None
    else:
        status = ResearchEvidenceStatus.AVAILABLE
        sole_version = next(iter(source_versions))
        revision_metrics = tuple(
            _build_revision_metrics(
                revision_id=revision_id,
                source=source,
                source_version=sole_version,
                all_rows=tuple(
                    row for row in source_rows if row.binding.scenario_revision_id == revision_id
                ),
                usable_rows=usable_by_revision[revision_id],
                policy=policy,
            )
            for revision_id in scope.scenario_revision_ids
        )
        multiclass_metrics = (
            None
            if scope.scenario_set_revision_id is None
            else _build_multiclass_metrics(
                scenario_set_revision_id=scope.scenario_set_revision_id,
                groups=multiclass_rows,
                class_counts=multiclass_counts,
                source=source,
            )
        )

    report_hash = probability_source_calibration_hash(
        report_version=_SOURCE_REPORT_VERSION,
        source=source,
        policy_version=policy.policy_version,
        scope_hash=scope.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        revision_metrics=revision_metrics,
        multiclass_metrics=multiclass_metrics,
        blockers=tuple(blockers),
    )
    return ProbabilitySourceCalibrationReport(
        report_version=_SOURCE_REPORT_VERSION,
        probability_source=source,
        policy_version=policy.policy_version,
        scope_hash=scope.content_hash,
        evaluated_at=evaluated_at,
        status=status,
        revision_metrics=revision_metrics,
        multiclass_metrics=multiclass_metrics,
        blockers=tuple(blockers),
        content_hash=report_hash,
    )


def _collect_multiclass_groups(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    source_rows: tuple[ForecastLedgerOutcomeObservation, ...],
    evaluated_at: datetime,
    source: ScenarioProbabilitySource,
) -> tuple[
    tuple[tuple[ForecastLedgerOutcomeObservation, ...], ...],
    tuple[tuple[UUID, int], ...],
    tuple[CalibrationBlocker, ...],
    bool,
]:
    grouped: dict[str, list[ForecastLedgerOutcomeObservation]] = defaultdict(list)
    for row in source_rows:
        grouped[row.forecast_group_id].append(row)
    members = set(scope.scenario_revision_ids)
    usable_groups: list[tuple[ForecastLedgerOutcomeObservation, ...]] = []
    class_counts = dict.fromkeys(scope.scenario_revision_ids, 0)
    blockers: list[CalibrationBlocker] = []
    blocked = False
    for group_id, rows in grouped.items():
        row_members = [row.binding.scenario_revision_id for row in rows]
        if set(row_members) != members or len(row_members) != len(members):
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.multiclass.group_incomplete",
                    "forecast group does not contain each set revision exactly once",
                    entry_id=group_id,
                )
            )
            continue
        group_identity = {
            (
                row.published_at,
                row.horizon_end,
                row.pit_manifest_id,
                row.pit_manifest_version,
                row.pit_manifest_hash,
                _source_version(row, source),
                (
                    row.binding.model_promotion_decision_id
                    if source is ScenarioProbabilitySource.MODEL_INFERRED
                    else None
                ),
            )
            for row in rows
        }
        if len(group_identity) != 1:
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.multiclass.group_identity_mixed",
                    "forecast group must share publication, horizon, PIT manifest, source version, and promotion",
                    entry_id=group_id,
                )
            )
            continue
        probabilities = tuple(row.probability_for(source) for row in rows)
        if any(probability is None for probability in probabilities):
            raise ValueError("multiclass group is missing the selected probability source")
        total = sum(
            (probability for probability in probabilities if probability is not None),
            start=Decimal("0"),
        )
        if abs(total - Decimal("1")) > policy.probability_sum_tolerance:
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.multiclass.probability_sum_invalid",
                    "scenario-set probabilities do not sum to one within policy tolerance",
                    entry_id=group_id,
                )
            )
            continue
        if any(row.scenario_realized is None for row in rows):
            continue
        if any(_outcome_expired(row, policy, evaluated_at) for row in rows):
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.multiclass.outcome_evidence_expired",
                    "multiclass outcome evidence has expired under the active policy",
                    entry_id=group_id,
                )
            )
            continue
        realized = tuple(row for row in rows if row.scenario_realized is True)
        if len(realized) != 1:
            blocked = True
            blockers.append(
                CalibrationBlocker(
                    "scenario_calibration.multiclass.realization_invalid",
                    "a complete scenario-set outcome must realize exactly one revision",
                    entry_id=group_id,
                )
            )
            continue
        class_counts[realized[0].binding.scenario_revision_id] += 1
        usable_groups.append(
            tuple(sorted(rows, key=lambda row: str(row.binding.scenario_revision_id)))
        )

    if len(usable_groups) < policy.minimum_multiclass_groups:
        blockers.append(
            CalibrationBlocker(
                "scenario_calibration.multiclass.groups_insufficient",
                "resolved scenario-set groups are below the versioned policy minimum",
            )
        )
    if any(count < policy.minimum_multiclass_class_observations for count in class_counts.values()):
        blockers.append(
            CalibrationBlocker(
                "scenario_calibration.multiclass.class_support_insufficient",
                "each scenario-set class requires the versioned policy support",
            )
        )
    return (
        tuple(usable_groups),
        tuple(class_counts.items()),
        tuple(blockers),
        blocked,
    )


def _build_revision_metrics(
    *,
    revision_id: UUID,
    source: ScenarioProbabilitySource,
    source_version: str,
    all_rows: tuple[ForecastLedgerOutcomeObservation, ...],
    usable_rows: tuple[ForecastLedgerOutcomeObservation, ...],
    policy: ScenarioProbabilityResearchPolicy,
) -> RevisionCalibrationMetrics:
    scores = tuple(_binary_brier(row, source) for row in usable_rows)
    bins: list[CalibrationBinResult] = []
    for index, (lower, upper) in enumerate(
        zip(
            policy.calibration_bin_edges,
            policy.calibration_bin_edges[1:],
            strict=False,
        )
    ):
        is_final = index == len(policy.calibration_bin_edges) - 2
        rows_in_bin = tuple(
            row
            for row in usable_rows
            if _in_bin(_required_probability(row, source), lower, upper, is_final)
        )
        if not rows_in_bin:
            continue
        probabilities = tuple(_required_probability(row, source) for row in rows_in_bin)
        hit_count = sum(row.scenario_realized is True for row in rows_in_bin)
        bins.append(
            CalibrationBinResult(
                lower_bound=lower,
                upper_bound=upper,
                sample_count=len(rows_in_bin),
                mean_forecast_probability=sum(probabilities, start=Decimal("0"))
                / Decimal(len(probabilities)),
                observed_hit_rate=Decimal(hit_count) / Decimal(len(rows_in_bin)),
            )
        )
    return RevisionCalibrationMetrics(
        scenario_revision_id=revision_id,
        probability_source_version=source_version,
        forecast_count=len(all_rows),
        resolved_outcome_count=len(usable_rows),
        outcome_coverage=_coverage(len(usable_rows), len(all_rows)),
        realized_count=sum(row.scenario_realized is True for row in usable_rows),
        not_realized_count=sum(row.scenario_realized is False for row in usable_rows),
        mean_brier_score=sum(scores, start=Decimal("0")) / Decimal(len(scores)),
        bins=tuple(bins),
    )


def _build_multiclass_metrics(
    *,
    scenario_set_revision_id: UUID,
    groups: tuple[tuple[ForecastLedgerOutcomeObservation, ...], ...],
    class_counts: tuple[tuple[UUID, int], ...],
    source: ScenarioProbabilitySource,
) -> MulticlassCalibrationMetrics:
    scores = tuple(
        sum((_binary_brier(row, source) for row in group), start=Decimal("0")) for group in groups
    )
    return MulticlassCalibrationMetrics(
        scenario_set_revision_id=scenario_set_revision_id,
        resolved_group_count=len(groups),
        mean_multiclass_brier_score=sum(scores, start=Decimal("0")) / Decimal(len(scores)),
        realized_class_counts=class_counts,
    )


def _validate_observation_scope(
    *,
    scope: ScenarioResearchScope,
    policy: ScenarioProbabilityResearchPolicy,
    observations: tuple[ForecastLedgerOutcomeObservation, ...],
    evaluated_at: datetime,
) -> None:
    entry_ids = [row.entry_id for row in observations]
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("forecast ledger observations contain duplicate entry_id values")
    members = set(scope.scenario_revision_ids)
    if scope.forecast_horizon != policy.forecast_horizon:
        raise ValueError("scenario research scope forecast horizon does not match policy")
    if scope.censoring_rule_version != policy.censoring_rule_version:
        raise ValueError("scenario research scope censoring rule does not match policy")
    if scope.path_horizon_periods != policy.path_horizon_periods:
        raise ValueError("scenario research scope path horizon does not match policy")
    if (
        policy.require_all_path_initial_states
        and set(scope.path_initial_state_revision_ids) != members
    ):
        raise ValueError("scenario research scope must cover every path initial state")
    for row in observations:
        if row.binding.scenario_revision_id not in members:
            raise ValueError("forecast ledger observation scenario revision is out of scope")
        if row.binding.scenario_set_revision_id != scope.scenario_set_revision_id:
            raise ValueError("forecast ledger observation scenario-set revision mismatch")
        if not policy.sample_window_start <= row.published_at < policy.sample_window_end:
            raise ValueError("forecast ledger observation is outside the policy sample window")
        if row.horizon_end - row.published_at != scope.forecast_horizon:
            raise ValueError("forecast ledger observation horizon does not match exact scope")
        if row.censoring_rule_version != scope.censoring_rule_version:
            raise ValueError("forecast ledger observation censoring rule mismatch")
        if row.published_at > evaluated_at:
            raise ValueError("forecast ledger observation cannot be future-dated")
        if row.outcome_recorded_at is not None and row.outcome_recorded_at > evaluated_at:
            raise ValueError("forecast ledger outcome cannot be future-dated")
        if row.invalidation is not None and row.invalidation.invalidated_at > evaluated_at:
            raise ValueError("scenario invalidation cannot be future-dated")
        if (
            row.scenario_realized is None
            and row.invalidation is None
            and evaluated_at >= row.horizon_end + policy.censoring_lag
        ):
            raise ValueError("forecast ledger observation exceeded the exact censoring lag")


def _outcome_expired(
    row: ForecastLedgerOutcomeObservation,
    policy: ScenarioProbabilityResearchPolicy,
    evaluated_at: datetime,
) -> bool:
    assert row.outcome_recorded_at is not None
    assert row.outcome_evidence_valid_until is not None
    return (
        row.outcome_evidence_valid_until <= evaluated_at
        or row.outcome_recorded_at + policy.maximum_outcome_evidence_age <= evaluated_at
    )


def _source_version(
    row: ForecastLedgerOutcomeObservation,
    source: ScenarioProbabilitySource,
) -> str:
    if source is ScenarioProbabilitySource.SUBJECTIVE:
        return row.binding.subjective_probability_source_version
    assert row.binding.model_probability_source_version is not None
    return row.binding.model_probability_source_version


def _required_probability(
    row: ForecastLedgerOutcomeObservation,
    source: ScenarioProbabilitySource,
) -> Decimal:
    probability = row.probability_for(source)
    if probability is None:
        raise ValueError("selected probability source is absent")
    return probability


def _binary_brier(
    row: ForecastLedgerOutcomeObservation,
    source: ScenarioProbabilitySource,
) -> Decimal:
    if row.scenario_realized is None:
        raise ValueError("Brier score requires an explicit scenario outcome")
    outcome = Decimal(1 if row.scenario_realized else 0)
    return (_required_probability(row, source) - outcome) ** 2


def _coverage(resolved: int, total: int) -> Decimal:
    if total == 0:
        return Decimal("0")
    return Decimal(resolved) / Decimal(total)


def _in_bin(
    probability: Decimal,
    lower: Decimal,
    upper: Decimal,
    final_bin: bool,
) -> bool:
    return lower <= probability <= upper if final_bin else lower <= probability < upper


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
