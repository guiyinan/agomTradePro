"""Validation and identity helpers for scenario research evidence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.research.domain.scenario_research_evidence import (
    ConditionalProbabilityEvidence,
    HistoricalAnalogyCandidateEvidence,
    MultiPeriodShockEvidence,
    PointInTimeFeatureValue,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
    TransitionProbabilityEvidence,
)
from apps.research.domain.scenario_research_hashing import hash_components, require_text


def _validate_path_distributions(
    *,
    scenario_revision_ids: tuple[UUID, ...],
    initial_state_revision_ids: tuple[UUID, ...],
    required_horizon_periods: int,
    pit_manifest: PointInTimeManifestReference,
    conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...],
    transition_probabilities: tuple[TransitionProbabilityEvidence, ...],
    tolerance: Decimal,
) -> None:
    _require_probability(tolerance, "probability_sum_tolerance")
    members = set(scenario_revision_ids)
    initial_states = set(initial_state_revision_ids)
    if not initial_states or not initial_states.issubset(members):
        raise ValueError("path initial states must be a non-empty subset of scenario scope")
    if isinstance(required_horizon_periods, bool) or required_horizon_periods < 1:
        raise ValueError("path required horizon must be positive")
    all_estimates: tuple[ConditionalProbabilityEvidence | TransitionProbabilityEvidence, ...] = (
        conditional_probabilities + transition_probabilities
    )
    if all_estimates:
        provenance = {
            (
                item.source_version,
                item.sample_definition_version,
                item.observation_count,
                item.pit_manifest_id,
                item.pit_manifest_version,
                item.pit_manifest_hash,
            )
            for item in all_estimates
        }
        if len(provenance) != 1:
            raise ValueError("path distributions must share exact sample and PIT provenance")
        sole = next(iter(provenance))
        if sole[3:] != (
            pit_manifest.manifest_id,
            pit_manifest.manifest_version,
            pit_manifest.manifest_hash,
        ):
            raise ValueError("path distribution PIT provenance does not match study manifest")
    conditional_groups: dict[tuple[int, str], list[ConditionalProbabilityEvidence]] = {}
    for conditional in conditional_probabilities:
        if conditional.target_scenario_revision_id not in members:
            raise ValueError("conditional probability target is outside scenario scope")
        if conditional.period_index > required_horizon_periods:
            raise ValueError("conditional probability period exceeds path horizon")
        conditional_groups.setdefault(
            (conditional.period_index, conditional.condition_key), []
        ).append(conditional)
    if {key[0] for key in conditional_groups} != set(range(1, required_horizon_periods + 1)):
        raise ValueError("conditional distributions do not cover every path period")
    for condition_key, conditionals in conditional_groups.items():
        targets = {conditional.target_scenario_revision_id for conditional in conditionals}
        if targets != members or len(targets) != len(conditionals):
            raise ValueError(f"conditional distribution {condition_key} is incomplete")
        _require_distribution_sum(
            (conditional.probability for conditional in conditionals),
            tolerance=tolerance,
            label=f"conditional distribution {condition_key}",
        )

    transition_groups: dict[tuple[UUID, int], list[TransitionProbabilityEvidence]] = {}
    for transition in transition_probabilities:
        if (
            transition.from_scenario_revision_id not in members
            or transition.to_scenario_revision_id not in members
        ):
            raise ValueError("transition probability is outside scenario scope")
        key = (transition.from_scenario_revision_id, transition.horizon_periods)
        transition_groups.setdefault(key, []).append(transition)
    expected_transition_groups = {
        (initial_state, period_index)
        for initial_state in initial_states
        for period_index in range(1, required_horizon_periods + 1)
    }
    if set(transition_groups) != expected_transition_groups:
        raise ValueError(
            "transition distributions do not cover the required horizon and initial states"
        )
    for key, transitions in transition_groups.items():
        targets = {transition.to_scenario_revision_id for transition in transitions}
        if targets != members or len(targets) != len(transitions):
            raise ValueError(f"transition distribution {key} is incomplete")
        _require_distribution_sum(
            (transition.probability for transition in transitions),
            tolerance=tolerance,
            label=f"transition distribution {key}",
        )


def _require_distribution_sum(
    probabilities: Iterable[Decimal],
    *,
    tolerance: Decimal,
    label: str,
) -> None:
    total = sum(probabilities, start=Decimal("0"))
    if abs(total - Decimal("1")) > tolerance:
        raise ValueError(f"{label} probabilities must sum to one")


def _analogy_candidate_hash(
    *,
    candidate_id: str,
    candidate_version: str,
    window_start: datetime,
    window_end: datetime,
    decision_cutoff: datetime,
    allowed_release_lag: timedelta,
    pit_manifest: PointInTimeManifestReference,
    feature_definition_version: str,
    features: tuple[PointInTimeFeatureValue, ...],
    similarity_score: Decimal,
    evidence_refs: tuple[str, ...],
) -> str:
    feature_parts = tuple(
        f"{item.feature_key}|{item.value}|{item.unit}|{item.source_version}|"
        f"{item.available_at.isoformat()}|{item.vintage_at.isoformat()}"
        for item in features
    )
    return hash_components(
        candidate_id,
        candidate_version,
        window_start.isoformat(),
        window_end.isoformat(),
        decision_cutoff.isoformat(),
        str(allowed_release_lag.total_seconds()),
        pit_manifest.reference_hash,
        feature_definition_version,
        *feature_parts,
        str(similarity_score),
        *evidence_refs,
    )


def _analogy_study_hash(
    *,
    study_version: str,
    scope_hash: str,
    query_manifest: PointInTimeManifestReference,
    feature_definition_version: str,
    candidates: tuple[HistoricalAnalogyCandidateEvidence, ...],
    generated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
) -> str:
    return hash_components(
        study_version,
        scope_hash,
        query_manifest.reference_hash,
        feature_definition_version,
        *(candidate.content_hash for candidate in candidates),
        generated_at.isoformat(),
        valid_until.isoformat(),
        *evidence_refs,
        "research_only",
        "must_not_use_for_decision",
    )


def _path_study_hash(
    *,
    study_version: str,
    scope_hash: str,
    scenario_set_revision_id: UUID | None,
    scenario_revision_ids: tuple[UUID, ...],
    pit_manifest: PointInTimeManifestReference,
    shocks: tuple[MultiPeriodShockEvidence, ...],
    conditional_probabilities: tuple[ConditionalProbabilityEvidence, ...],
    transition_probabilities: tuple[TransitionProbabilityEvidence, ...],
    generated_at: datetime,
    valid_until: datetime,
    evidence_refs: tuple[str, ...],
    probability_sum_tolerance: Decimal,
) -> str:
    shock_parts = tuple(
        f"{item.period_index}|{item.scenario_revision_id}|{item.period_start.isoformat()}|"
        f"{item.period_end.isoformat()}|{item.shock_key}|{item.magnitude}|{item.unit}|"
        f"{item.source_version}"
        for item in shocks
    )
    conditional_parts = tuple(
        f"{item.period_index}|{item.condition_key}|{item.target_scenario_revision_id}|"
        f"{item.probability}|"
        f"{item.observation_count}|{item.source_version}|{item.sample_definition_version}|"
        f"{item.pit_manifest_id}|{item.pit_manifest_version}|{item.pit_manifest_hash}"
        for item in conditional_probabilities
    )
    transition_parts = tuple(
        f"{item.from_scenario_revision_id}|{item.to_scenario_revision_id}|"
        f"{item.horizon_periods}|{item.probability}|{item.observation_count}|"
        f"{item.source_version}|{item.sample_definition_version}|{item.pit_manifest_id}|"
        f"{item.pit_manifest_version}|{item.pit_manifest_hash}"
        for item in transition_probabilities
    )
    return hash_components(
        study_version,
        scope_hash,
        str(scenario_set_revision_id or ""),
        *(str(revision_id) for revision_id in scenario_revision_ids),
        pit_manifest.reference_hash,
        *shock_parts,
        *conditional_parts,
        *transition_parts,
        generated_at.isoformat(),
        valid_until.isoformat(),
        *evidence_refs,
        str(probability_sum_tolerance),
        "research_only",
        "must_not_use_for_decision",
    )


def _require_evidence_refs(evidence_refs: tuple[str, ...]) -> None:
    if not evidence_refs:
        raise ValueError("research evidence requires at least one reference")
    for evidence_ref in evidence_refs:
        require_text(evidence_ref, "evidence_ref")


def _manifest_feature_part(item: PointInTimeManifestFeature) -> str:
    return (
        f"{item.feature_key}|{item.source_version}|{item.available_at.isoformat()}|"
        f"{item.vintage_at.isoformat()}|{item.content_hash}"
    )


def _require_positive_count(value: int, field_name: str) -> None:
    if isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be positive")


def _require_probability(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= 1:
        raise ValueError(f"{field_name} must be a finite Decimal within [0, 1]")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
