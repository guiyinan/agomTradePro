"""Immutable contracts for R7 scenario probability calibration research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID

from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_text,
    require_token,
)
from apps.signal.domain.forecast_scenario_evidence import (
    ScenarioForecastBinding,
    ScenarioProbabilitySource,
)


class ResearchEvidenceStatus(str, Enum):
    """Availability state for evidence-gated R7 research outputs."""

    AVAILABLE = "available"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ScenarioResearchScope:
    """Exact immutable scenario revision or scenario-set revision scope."""

    scope_version: str
    scenario_set_revision_id: UUID | None
    scenario_revision_ids: tuple[UUID, ...]
    forecast_horizon: timedelta
    censoring_rule_version: str
    path_horizon_periods: int
    path_initial_state_revision_ids: tuple[UUID, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        scope_version: str,
        scenario_set_revision_id: UUID | None,
        scenario_revision_ids: tuple[UUID, ...],
        forecast_horizon: timedelta,
        censoring_rule_version: str,
        path_horizon_periods: int,
        path_initial_state_revision_ids: tuple[UUID, ...],
    ) -> ScenarioResearchScope:
        """Create a canonical scope with stable member ordering and hash."""

        ordered = tuple(sorted(scenario_revision_ids, key=str))
        ordered_initial_states = tuple(sorted(path_initial_state_revision_ids, key=str))
        digest = hash_components(
            scope_version,
            str(scenario_set_revision_id or ""),
            *(str(revision_id) for revision_id in ordered),
            str(forecast_horizon.total_seconds()),
            censoring_rule_version,
            str(path_horizon_periods),
            *(str(revision_id) for revision_id in ordered_initial_states),
        )
        return cls(
            scope_version,
            scenario_set_revision_id,
            ordered,
            forecast_horizon,
            censoring_rule_version,
            path_horizon_periods,
            ordered_initial_states,
            digest,
        )

    def __post_init__(self) -> None:
        """Reject ambiguous membership, ordering, or a forged scope hash."""

        require_token(self.scope_version, "scope_version")
        if not self.scenario_revision_ids:
            raise ValueError("scenario research scope requires at least one revision")
        if len(set(self.scenario_revision_ids)) != len(self.scenario_revision_ids):
            raise ValueError("scenario research scope contains duplicate revisions")
        if self.scenario_revision_ids != tuple(sorted(self.scenario_revision_ids, key=str)):
            raise ValueError("scenario research scope revisions must be canonicalized")
        if self.scenario_set_revision_id is None and len(self.scenario_revision_ids) != 1:
            raise ValueError("standalone scenario scope must contain exactly one revision")
        if self.scenario_set_revision_id is not None and len(self.scenario_revision_ids) < 2:
            raise ValueError("scenario-set scope requires at least two revisions")
        if self.forecast_horizon <= timedelta(0):
            raise ValueError("forecast_horizon must be positive")
        require_token(self.censoring_rule_version, "censoring_rule_version")
        if isinstance(self.path_horizon_periods, bool) or self.path_horizon_periods < 1:
            raise ValueError("path_horizon_periods must be positive")
        if (
            not self.path_initial_state_revision_ids
            or len(set(self.path_initial_state_revision_ids))
            != len(self.path_initial_state_revision_ids)
            or self.path_initial_state_revision_ids
            != tuple(sorted(self.path_initial_state_revision_ids, key=str))
        ):
            raise ValueError("path initial states must be non-empty, unique, and canonicalized")
        if not set(self.path_initial_state_revision_ids).issubset(self.scenario_revision_ids):
            raise ValueError("path initial states must belong to the scenario scope")
        expected = hash_components(
            self.scope_version,
            str(self.scenario_set_revision_id or ""),
            *(str(revision_id) for revision_id in self.scenario_revision_ids),
            str(self.forecast_horizon.total_seconds()),
            self.censoring_rule_version,
            str(self.path_horizon_periods),
            *(str(revision_id) for revision_id in self.path_initial_state_revision_ids),
        )
        require_sha256(self.content_hash, "scope content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario research scope content_hash mismatch")


@dataclass(frozen=True)
class ScenarioProbabilityResearchPolicy:
    """Injected, versioned fail-closed policy for R7 evidence evaluation."""

    policy_version: str
    activated_at: datetime
    valid_until: datetime
    sample_window_start: datetime
    sample_window_end: datetime
    forecast_horizon: timedelta
    censoring_lag: timedelta
    censoring_rule_version: str
    minimum_forecasts_per_revision: int
    minimum_resolved_outcomes_per_revision: int
    minimum_outcome_coverage: Decimal
    minimum_binary_class_observations: int
    minimum_multiclass_groups: int
    minimum_multiclass_class_observations: int
    maximum_outcome_evidence_age: timedelta
    calibration_bin_edges: tuple[Decimal, ...]
    probability_sum_tolerance: Decimal
    minimum_historical_analogies: int
    minimum_path_probability_observations: int
    path_horizon_periods: int
    require_all_path_initial_states: bool
    maximum_research_evidence_age: timedelta
    invalidation_review_delay: timedelta
    approved_by: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        activated_at: datetime,
        valid_until: datetime,
        sample_window_start: datetime,
        sample_window_end: datetime,
        forecast_horizon: timedelta,
        censoring_lag: timedelta,
        censoring_rule_version: str,
        minimum_forecasts_per_revision: int,
        minimum_resolved_outcomes_per_revision: int,
        minimum_outcome_coverage: Decimal,
        minimum_binary_class_observations: int,
        minimum_multiclass_groups: int,
        minimum_multiclass_class_observations: int,
        maximum_outcome_evidence_age: timedelta,
        calibration_bin_edges: tuple[Decimal, ...],
        probability_sum_tolerance: Decimal,
        minimum_historical_analogies: int,
        minimum_path_probability_observations: int,
        path_horizon_periods: int,
        require_all_path_initial_states: bool,
        maximum_research_evidence_age: timedelta,
        invalidation_review_delay: timedelta,
        approved_by: str,
    ) -> ScenarioProbabilityResearchPolicy:
        """Build one policy and bind every safety threshold into its hash."""

        components = cls._hash_components(
            policy_version=policy_version,
            activated_at=activated_at,
            valid_until=valid_until,
            sample_window_start=sample_window_start,
            sample_window_end=sample_window_end,
            forecast_horizon=forecast_horizon,
            censoring_lag=censoring_lag,
            censoring_rule_version=censoring_rule_version,
            minimum_forecasts_per_revision=minimum_forecasts_per_revision,
            minimum_resolved_outcomes_per_revision=minimum_resolved_outcomes_per_revision,
            minimum_outcome_coverage=minimum_outcome_coverage,
            minimum_binary_class_observations=minimum_binary_class_observations,
            minimum_multiclass_groups=minimum_multiclass_groups,
            minimum_multiclass_class_observations=minimum_multiclass_class_observations,
            maximum_outcome_evidence_age=maximum_outcome_evidence_age,
            calibration_bin_edges=calibration_bin_edges,
            probability_sum_tolerance=probability_sum_tolerance,
            minimum_historical_analogies=minimum_historical_analogies,
            minimum_path_probability_observations=minimum_path_probability_observations,
            path_horizon_periods=path_horizon_periods,
            require_all_path_initial_states=require_all_path_initial_states,
            maximum_research_evidence_age=maximum_research_evidence_age,
            invalidation_review_delay=invalidation_review_delay,
            approved_by=approved_by,
        )
        return cls(
            policy_version=policy_version,
            activated_at=activated_at,
            valid_until=valid_until,
            sample_window_start=sample_window_start,
            sample_window_end=sample_window_end,
            forecast_horizon=forecast_horizon,
            censoring_lag=censoring_lag,
            censoring_rule_version=censoring_rule_version,
            minimum_forecasts_per_revision=minimum_forecasts_per_revision,
            minimum_resolved_outcomes_per_revision=minimum_resolved_outcomes_per_revision,
            minimum_outcome_coverage=minimum_outcome_coverage,
            minimum_binary_class_observations=minimum_binary_class_observations,
            minimum_multiclass_groups=minimum_multiclass_groups,
            minimum_multiclass_class_observations=minimum_multiclass_class_observations,
            maximum_outcome_evidence_age=maximum_outcome_evidence_age,
            calibration_bin_edges=calibration_bin_edges,
            probability_sum_tolerance=probability_sum_tolerance,
            minimum_historical_analogies=minimum_historical_analogies,
            minimum_path_probability_observations=minimum_path_probability_observations,
            path_horizon_periods=path_horizon_periods,
            require_all_path_initial_states=require_all_path_initial_states,
            maximum_research_evidence_age=maximum_research_evidence_age,
            invalidation_review_delay=invalidation_review_delay,
            approved_by=approved_by,
            content_hash=hash_components(*components),
        )

    def __post_init__(self) -> None:
        """Validate policy clocks, thresholds, bins, and immutable hash."""

        require_token(self.policy_version, "policy_version")
        require_token(self.approved_by, "approved_by")
        for field_name, timestamp in (
            ("activated_at", self.activated_at),
            ("valid_until", self.valid_until),
            ("sample_window_start", self.sample_window_start),
            ("sample_window_end", self.sample_window_end),
        ):
            _require_aware(timestamp, field_name)
        if self.valid_until <= self.activated_at:
            raise ValueError("policy valid_until must follow activated_at")
        if self.sample_window_end <= self.sample_window_start:
            raise ValueError("sample_window_end must follow sample_window_start")
        if self.forecast_horizon <= timedelta(0):
            raise ValueError("forecast_horizon must be positive")
        if self.censoring_lag < timedelta(0):
            raise ValueError("censoring_lag cannot be negative")
        require_token(self.censoring_rule_version, "censoring_rule_version")
        for field_name, count in (
            ("minimum_forecasts_per_revision", self.minimum_forecasts_per_revision),
            (
                "minimum_resolved_outcomes_per_revision",
                self.minimum_resolved_outcomes_per_revision,
            ),
            ("minimum_binary_class_observations", self.minimum_binary_class_observations),
            ("minimum_multiclass_groups", self.minimum_multiclass_groups),
            (
                "minimum_multiclass_class_observations",
                self.minimum_multiclass_class_observations,
            ),
            ("minimum_historical_analogies", self.minimum_historical_analogies),
            (
                "minimum_path_probability_observations",
                self.minimum_path_probability_observations,
            ),
            ("path_horizon_periods", self.path_horizon_periods),
        ):
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        _require_probability(self.minimum_outcome_coverage, "minimum_outcome_coverage")
        if self.minimum_outcome_coverage == 0:
            raise ValueError("minimum_outcome_coverage must be greater than zero")
        _require_probability(self.probability_sum_tolerance, "probability_sum_tolerance")
        if self.probability_sum_tolerance == 0:
            raise ValueError("probability_sum_tolerance must be greater than zero")
        for field_name, duration in (
            ("maximum_outcome_evidence_age", self.maximum_outcome_evidence_age),
            ("maximum_research_evidence_age", self.maximum_research_evidence_age),
        ):
            if duration <= timedelta(0):
                raise ValueError(f"{field_name} must be positive")
        if self.invalidation_review_delay < timedelta(0):
            raise ValueError("invalidation_review_delay cannot be negative")
        _validate_bin_edges(self.calibration_bin_edges)
        expected = hash_components(
            *self._hash_components(
                policy_version=self.policy_version,
                activated_at=self.activated_at,
                valid_until=self.valid_until,
                sample_window_start=self.sample_window_start,
                sample_window_end=self.sample_window_end,
                forecast_horizon=self.forecast_horizon,
                censoring_lag=self.censoring_lag,
                censoring_rule_version=self.censoring_rule_version,
                minimum_forecasts_per_revision=self.minimum_forecasts_per_revision,
                minimum_resolved_outcomes_per_revision=(
                    self.minimum_resolved_outcomes_per_revision
                ),
                minimum_outcome_coverage=self.minimum_outcome_coverage,
                minimum_binary_class_observations=(self.minimum_binary_class_observations),
                minimum_multiclass_groups=self.minimum_multiclass_groups,
                minimum_multiclass_class_observations=(self.minimum_multiclass_class_observations),
                maximum_outcome_evidence_age=self.maximum_outcome_evidence_age,
                calibration_bin_edges=self.calibration_bin_edges,
                probability_sum_tolerance=self.probability_sum_tolerance,
                minimum_historical_analogies=self.minimum_historical_analogies,
                minimum_path_probability_observations=(self.minimum_path_probability_observations),
                path_horizon_periods=self.path_horizon_periods,
                require_all_path_initial_states=self.require_all_path_initial_states,
                maximum_research_evidence_age=self.maximum_research_evidence_age,
                invalidation_review_delay=self.invalidation_review_delay,
                approved_by=self.approved_by,
            )
        )
        require_sha256(self.content_hash, "policy content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario probability research policy content_hash mismatch")

    @staticmethod
    def _hash_components(
        *,
        policy_version: str,
        activated_at: datetime,
        valid_until: datetime,
        sample_window_start: datetime,
        sample_window_end: datetime,
        forecast_horizon: timedelta,
        censoring_lag: timedelta,
        censoring_rule_version: str,
        minimum_forecasts_per_revision: int,
        minimum_resolved_outcomes_per_revision: int,
        minimum_outcome_coverage: Decimal,
        minimum_binary_class_observations: int,
        minimum_multiclass_groups: int,
        minimum_multiclass_class_observations: int,
        maximum_outcome_evidence_age: timedelta,
        calibration_bin_edges: tuple[Decimal, ...],
        probability_sum_tolerance: Decimal,
        minimum_historical_analogies: int,
        minimum_path_probability_observations: int,
        path_horizon_periods: int,
        require_all_path_initial_states: bool,
        maximum_research_evidence_age: timedelta,
        invalidation_review_delay: timedelta,
        approved_by: str,
    ) -> tuple[str, ...]:
        return (
            policy_version,
            activated_at.isoformat(),
            valid_until.isoformat(),
            sample_window_start.isoformat(),
            sample_window_end.isoformat(),
            str(forecast_horizon.total_seconds()),
            str(censoring_lag.total_seconds()),
            censoring_rule_version,
            str(minimum_forecasts_per_revision),
            str(minimum_resolved_outcomes_per_revision),
            str(minimum_outcome_coverage),
            str(minimum_binary_class_observations),
            str(minimum_multiclass_groups),
            str(minimum_multiclass_class_observations),
            str(maximum_outcome_evidence_age.total_seconds()),
            *(str(edge) for edge in calibration_bin_edges),
            str(probability_sum_tolerance),
            str(minimum_historical_analogies),
            str(minimum_path_probability_observations),
            str(path_horizon_periods),
            str(require_all_path_initial_states),
            str(maximum_research_evidence_age.total_seconds()),
            str(invalidation_review_delay.total_seconds()),
            approved_by,
        )

    def is_active(self, evaluated_at: datetime) -> bool:
        """Return whether the policy is active at the injected evaluation time."""

        _require_aware(evaluated_at, "evaluated_at")
        return self.activated_at <= evaluated_at < self.valid_until


@dataclass(frozen=True)
class ScenarioInvalidationEvidence:
    """Immutable evidence that one exact scenario revision was invalidated."""

    evidence_version: str
    scenario_revision_id: UUID
    scenario_set_revision_id: UUID | None
    invalidated_at: datetime
    invalidation_rule_version: str
    pit_manifest_id: str
    evidence_refs: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        evidence_version: str,
        scenario_revision_id: UUID,
        scenario_set_revision_id: UUID | None,
        invalidated_at: datetime,
        invalidation_rule_version: str,
        pit_manifest_id: str,
        evidence_refs: tuple[str, ...],
    ) -> ScenarioInvalidationEvidence:
        """Build an invalidation record and freeze its provenance hash."""

        digest = hash_components(
            evidence_version,
            str(scenario_revision_id),
            str(scenario_set_revision_id or ""),
            invalidated_at.isoformat(),
            invalidation_rule_version,
            pit_manifest_id,
            *evidence_refs,
        )
        return cls(
            evidence_version=evidence_version,
            scenario_revision_id=scenario_revision_id,
            scenario_set_revision_id=scenario_set_revision_id,
            invalidated_at=invalidated_at,
            invalidation_rule_version=invalidation_rule_version,
            pit_manifest_id=pit_manifest_id,
            evidence_refs=evidence_refs,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Reject unversioned, naive, or unverifiable invalidation evidence."""

        for field_name, value in (
            ("evidence_version", self.evidence_version),
            ("invalidation_rule_version", self.invalidation_rule_version),
            ("pit_manifest_id", self.pit_manifest_id),
        ):
            require_token(value, field_name)
        _require_aware(self.invalidated_at, "invalidated_at")
        if not self.evidence_refs:
            raise ValueError("scenario invalidation requires evidence references")
        for evidence_ref in self.evidence_refs:
            require_text(evidence_ref, "evidence_ref")
        expected = hash_components(
            self.evidence_version,
            str(self.scenario_revision_id),
            str(self.scenario_set_revision_id or ""),
            self.invalidated_at.isoformat(),
            self.invalidation_rule_version,
            self.pit_manifest_id,
            *self.evidence_refs,
        )
        require_sha256(self.content_hash, "invalidation content_hash")
        if self.content_hash != expected:
            raise ValueError("scenario invalidation content_hash mismatch")


@dataclass(frozen=True)
class ForecastLedgerOutcomeObservation:
    """One immutable scenario-bound ledger row consumed by R7 research."""

    observation_version: str
    entry_id: str
    forecast_group_id: str
    binding: ScenarioForecastBinding
    pit_manifest_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    censoring_rule_version: str
    published_at: datetime
    horizon_end: datetime
    scenario_realized: bool | None
    outcome_recorded_at: datetime | None
    outcome_evidence_valid_until: datetime | None
    invalidation: ScenarioInvalidationEvidence | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        observation_version: str,
        entry_id: str,
        forecast_group_id: str,
        binding: ScenarioForecastBinding,
        pit_manifest_id: str,
        pit_manifest_version: str,
        pit_manifest_hash: str,
        censoring_rule_version: str,
        published_at: datetime,
        horizon_end: datetime,
        scenario_realized: bool | None,
        outcome_recorded_at: datetime | None,
        outcome_evidence_valid_until: datetime | None,
        invalidation: ScenarioInvalidationEvidence | None = None,
    ) -> ForecastLedgerOutcomeObservation:
        """Build a ledger observation without deriving or filling an outcome."""

        digest = _ledger_observation_hash(
            observation_version=observation_version,
            entry_id=entry_id,
            forecast_group_id=forecast_group_id,
            binding=binding,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_version=pit_manifest_version,
            pit_manifest_hash=pit_manifest_hash,
            censoring_rule_version=censoring_rule_version,
            published_at=published_at,
            horizon_end=horizon_end,
            scenario_realized=scenario_realized,
            outcome_recorded_at=outcome_recorded_at,
            outcome_evidence_valid_until=outcome_evidence_valid_until,
            invalidation=invalidation,
        )
        return cls(
            observation_version=observation_version,
            entry_id=entry_id,
            forecast_group_id=forecast_group_id,
            binding=binding,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_version=pit_manifest_version,
            pit_manifest_hash=pit_manifest_hash,
            censoring_rule_version=censoring_rule_version,
            published_at=published_at,
            horizon_end=horizon_end,
            scenario_realized=scenario_realized,
            outcome_recorded_at=outcome_recorded_at,
            outcome_evidence_valid_until=outcome_evidence_valid_until,
            invalidation=invalidation,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        """Reject mixed revisions, partial outcomes, and forged row hashes."""

        for field_name, value in (
            ("observation_version", self.observation_version),
            ("entry_id", self.entry_id),
            ("forecast_group_id", self.forecast_group_id),
            ("pit_manifest_id", self.pit_manifest_id),
            ("pit_manifest_version", self.pit_manifest_version),
            ("censoring_rule_version", self.censoring_rule_version),
        ):
            require_token(value, field_name)
        require_sha256(self.pit_manifest_hash, "pit_manifest_hash")
        _require_aware(self.published_at, "published_at")
        _require_aware(self.horizon_end, "horizon_end")
        if self.horizon_end <= self.published_at:
            raise ValueError("horizon_end must follow published_at")
        outcome_fields = (
            self.scenario_realized,
            self.outcome_recorded_at,
            self.outcome_evidence_valid_until,
        )
        if all(value is None for value in outcome_fields):
            pass
        elif any(value is None for value in outcome_fields):
            raise ValueError("scenario outcome fields must be complete or all absent")
        else:
            if not isinstance(self.scenario_realized, bool):
                raise ValueError("scenario_realized must be boolean")
            assert self.outcome_recorded_at is not None
            assert self.outcome_evidence_valid_until is not None
            _require_aware(self.outcome_recorded_at, "outcome_recorded_at")
            _require_aware(
                self.outcome_evidence_valid_until,
                "outcome_evidence_valid_until",
            )
            if self.outcome_recorded_at < self.horizon_end:
                raise ValueError("scenario outcome cannot precede horizon_end")
            if self.outcome_evidence_valid_until <= self.outcome_recorded_at:
                raise ValueError("outcome evidence validity must follow recording")
        if self.invalidation is not None:
            if self.scenario_realized is not None:
                raise ValueError("invalidated scenario cannot also be a realized outcome")
            if (
                self.invalidation.scenario_revision_id != self.binding.scenario_revision_id
                or self.invalidation.scenario_set_revision_id
                != self.binding.scenario_set_revision_id
            ):
                raise ValueError("invalidation does not match ledger scenario binding")
            if self.invalidation.invalidated_at < self.published_at:
                raise ValueError("invalidation cannot precede forecast publication")
        expected = _ledger_observation_hash(
            observation_version=self.observation_version,
            entry_id=self.entry_id,
            forecast_group_id=self.forecast_group_id,
            binding=self.binding,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_version=self.pit_manifest_version,
            pit_manifest_hash=self.pit_manifest_hash,
            censoring_rule_version=self.censoring_rule_version,
            published_at=self.published_at,
            horizon_end=self.horizon_end,
            scenario_realized=self.scenario_realized,
            outcome_recorded_at=self.outcome_recorded_at,
            outcome_evidence_valid_until=self.outcome_evidence_valid_until,
            invalidation=self.invalidation,
        )
        require_sha256(self.content_hash, "ledger observation content_hash")
        if self.content_hash != expected:
            raise ValueError("forecast ledger observation content_hash mismatch")

    def probability_for(self, source: ScenarioProbabilitySource) -> Decimal | None:
        """Return only the explicitly requested probability column."""

        if source is ScenarioProbabilitySource.SUBJECTIVE:
            return self.binding.subjective_probability
        return self.binding.model_probability


@dataclass(frozen=True)
class CalibrationBlocker:
    """Stable fail-closed reason attached to one source-specific report."""

    reason_code: str
    detail: str
    scenario_revision_id: UUID | None = None
    entry_id: str | None = None


@dataclass(frozen=True)
class CalibrationBinResult:
    """Observed hit rate for one policy-defined forecast-probability bin."""

    lower_bound: Decimal
    upper_bound: Decimal
    sample_count: int
    mean_forecast_probability: Decimal
    observed_hit_rate: Decimal


@dataclass(frozen=True)
class RevisionCalibrationMetrics:
    """Binary Brier and calibration bins for one exact scenario revision."""

    scenario_revision_id: UUID
    probability_source_version: str
    forecast_count: int
    resolved_outcome_count: int
    outcome_coverage: Decimal
    realized_count: int
    not_realized_count: int
    mean_brier_score: Decimal
    bins: tuple[CalibrationBinResult, ...]


@dataclass(frozen=True)
class MulticlassCalibrationMetrics:
    """Set-level multiclass Brier score over complete forecast groups."""

    scenario_set_revision_id: UUID
    resolved_group_count: int
    mean_multiclass_brier_score: Decimal
    realized_class_counts: tuple[tuple[UUID, int], ...]


@dataclass(frozen=True)
class ProbabilitySourceCalibrationReport:
    """Calibration report for exactly one non-interchangeable probability source."""

    report_version: str
    probability_source: ScenarioProbabilitySource
    policy_version: str
    scope_hash: str
    evaluated_at: datetime
    status: ResearchEvidenceStatus
    revision_metrics: tuple[RevisionCalibrationMetrics, ...]
    multiclass_metrics: MulticlassCalibrationMetrics | None
    blockers: tuple[CalibrationBlocker, ...]
    content_hash: str

    def __post_init__(self) -> None:
        """Validate source identity and fail-closed metric publication semantics."""

        require_token(self.report_version, "source report_version")
        require_token(self.policy_version, "source policy_version")
        require_sha256(self.scope_hash, "source scope_hash")
        require_sha256(self.content_hash, "source report content_hash")
        _require_aware(self.evaluated_at, "source evaluated_at")
        if self.status is ResearchEvidenceStatus.AVAILABLE:
            if not self.revision_metrics or self.blockers:
                raise ValueError("available calibration requires metrics without blockers")
        elif self.revision_metrics or self.multiclass_metrics is not None:
            raise ValueError("blocked calibration cannot publish partial metrics")
        elif not self.blockers:
            raise ValueError("unavailable calibration requires blockers")
        expected = probability_source_calibration_hash(
            report_version=self.report_version,
            source=self.probability_source,
            policy_version=self.policy_version,
            scope_hash=self.scope_hash,
            evaluated_at=self.evaluated_at,
            status=self.status,
            revision_metrics=self.revision_metrics,
            multiclass_metrics=self.multiclass_metrics,
            blockers=self.blockers,
        )
        if self.content_hash != expected:
            raise ValueError("source calibration report content_hash mismatch")


@dataclass(frozen=True)
class ScenarioCalibrationReport:
    """R7 report with subjective and model evidence in separate fields."""

    report_version: str
    policy_version: str
    scope_hash: str
    evaluated_at: datetime
    subjective: ProbabilitySourceCalibrationReport
    model_inferred: ProbabilitySourceCalibrationReport
    trains_probability_model: bool
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Keep source reports separate and prohibit training or decision use."""

        require_token(self.report_version, "report_version")
        require_token(self.policy_version, "policy_version")
        require_sha256(self.scope_hash, "scope_hash")
        require_sha256(self.content_hash, "calibration report content_hash")
        _require_aware(self.evaluated_at, "calibration evaluated_at")
        if self.subjective.probability_source is not ScenarioProbabilitySource.SUBJECTIVE:
            raise ValueError("subjective report must use the subjective source")
        if self.model_inferred.probability_source is not ScenarioProbabilitySource.MODEL_INFERRED:
            raise ValueError("model report must use the model_inferred source")
        for source_report in (self.subjective, self.model_inferred):
            if (
                source_report.policy_version != self.policy_version
                or source_report.scope_hash != self.scope_hash
                or source_report.evaluated_at != self.evaluated_at
            ):
                raise ValueError("source report identity does not match calibration report")
        if self.trains_probability_model:
            raise ValueError("calibration report cannot train a probability model")
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("calibration report must remain research-only")
        expected = hash_components(
            self.report_version,
            self.policy_version,
            self.scope_hash,
            self.evaluated_at.isoformat(),
            self.subjective.content_hash,
            self.model_inferred.content_hash,
            "False",
            "True",
            "True",
        )
        if self.content_hash != expected:
            raise ValueError("scenario calibration report content_hash mismatch")


def probability_source_calibration_hash(
    *,
    report_version: str,
    source: ScenarioProbabilitySource,
    policy_version: str,
    scope_hash: str,
    evaluated_at: datetime,
    status: ResearchEvidenceStatus,
    revision_metrics: tuple[RevisionCalibrationMetrics, ...],
    multiclass_metrics: MulticlassCalibrationMetrics | None,
    blockers: tuple[CalibrationBlocker, ...],
) -> str:
    """Hash one source-specific report without collapsing probability semantics."""

    metric_parts = tuple(
        f"{metric.scenario_revision_id}|{metric.probability_source_version}|"
        f"{metric.forecast_count}|{metric.resolved_outcome_count}|"
        f"{metric.outcome_coverage}|{metric.realized_count}|"
        f"{metric.not_realized_count}|{metric.mean_brier_score}|"
        + ";".join(
            f"{bin_result.lower_bound},{bin_result.upper_bound},"
            f"{bin_result.sample_count},{bin_result.mean_forecast_probability},"
            f"{bin_result.observed_hit_rate}"
            for bin_result in metric.bins
        )
        for metric in revision_metrics
    )
    multiclass_part = ""
    if multiclass_metrics is not None:
        multiclass_part = (
            f"{multiclass_metrics.scenario_set_revision_id}|"
            f"{multiclass_metrics.resolved_group_count}|"
            f"{multiclass_metrics.mean_multiclass_brier_score}|"
            + ";".join(
                f"{revision_id},{count}"
                for revision_id, count in multiclass_metrics.realized_class_counts
            )
        )
    blocker_parts = tuple(
        f"{blocker.reason_code}|{blocker.detail}|"
        f"{blocker.scenario_revision_id or ''}|{blocker.entry_id or ''}"
        for blocker in blockers
    )
    return hash_components(
        report_version,
        source.value,
        policy_version,
        scope_hash,
        evaluated_at.isoformat(),
        status.value,
        *metric_parts,
        multiclass_part,
        *blocker_parts,
    )


def _validate_bin_edges(edges: tuple[Decimal, ...]) -> None:
    if len(edges) < 2 or edges[0] != 0 or edges[-1] != 1:
        raise ValueError("calibration bins must span exactly [0, 1]")
    for edge in edges:
        _require_probability(edge, "calibration bin edge")
    if any(left >= right for left, right in zip(edges, edges[1:], strict=False)):
        raise ValueError("calibration bin edges must be strictly increasing")


def _require_probability(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be a finite Decimal within [0, 1]")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _ledger_observation_hash(
    *,
    observation_version: str,
    entry_id: str,
    forecast_group_id: str,
    binding: ScenarioForecastBinding,
    pit_manifest_id: str,
    pit_manifest_version: str,
    pit_manifest_hash: str,
    censoring_rule_version: str,
    published_at: datetime,
    horizon_end: datetime,
    scenario_realized: bool | None,
    outcome_recorded_at: datetime | None,
    outcome_evidence_valid_until: datetime | None,
    invalidation: ScenarioInvalidationEvidence | None,
) -> str:
    return hash_components(
        observation_version,
        entry_id,
        forecast_group_id,
        str(binding.scenario_revision_id),
        str(binding.scenario_set_revision_id or ""),
        str(binding.subjective_probability),
        binding.subjective_probability_source_version,
        str(binding.model_probability if binding.model_probability is not None else ""),
        str(binding.model_probability_source_version or ""),
        str(binding.model_promotion_decision_id or ""),
        pit_manifest_id,
        pit_manifest_version,
        pit_manifest_hash,
        censoring_rule_version,
        published_at.isoformat(),
        horizon_end.isoformat(),
        str(scenario_realized),
        outcome_recorded_at.isoformat() if outcome_recorded_at else "",
        outcome_evidence_valid_until.isoformat() if outcome_evidence_valid_until else "",
        invalidation.content_hash if invalidation else "",
    )
