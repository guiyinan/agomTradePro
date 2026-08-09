"""Hashing and policy-gate helpers for Research R1 forecast promotion."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from apps.equity.domain.forecast_baseline import ForecastBaselineTrialResult
from apps.research.domain.r1_forecast_promotion_decision import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1ForecastTrialPromotionSeal,
    R1PromotionDecisionOutcome,
    R1PromotionForecastIdentity,
    R1PromotionGateCode,
    R1PromotionInvalidationEvidence,
    R1PromotionMetricEvidence,
    R1PromotionPolicyGateOutcome,
    R1PromotionScope,
    R1PromotionTrialState,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _utc_text,
)


def _promotion_decision_payload(
    *,
    decision_id: str,
    decision_version: str,
    owner: str,
    capability: str,
    purpose: str,
    promotion_scope: R1PromotionScope,
    outcome: R1PromotionDecisionOutcome,
    policy: R1ForecastPromotionPolicy,
    trial: R1ForecastTrialPromotionSeal,
    policy_gate_outcomes: tuple[R1PromotionPolicyGateOutcome, ...],
    reason_codes: tuple[str, ...],
    decided_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r1-forecast-promotion-decision.v1",
        "identity": [decision_id, decision_version, owner, capability, purpose],
        "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
        "outcome": outcome.value,
        "policy": [
            policy.policy_id,
            policy.policy_version,
            policy.content_hash,
            policy.owner,
            policy.capability,
            policy.purpose,
        ],
        "policy_gate_outcomes": [
            [
                item.gate_code.value,
                item.passes,
                item.reason_code,
                (
                    _decimal_text(item.observed_coverage)
                    if item.observed_coverage is not None
                    else None
                ),
                (
                    _decimal_text(item.required_coverage)
                    if item.required_coverage is not None
                    else None
                ),
            ]
            for item in policy_gate_outcomes
        ],
        "trial": {
            "result": [trial.result_id, trial.result_version, trial.result_content_hash],
            "spec": [trial.spec_id, trial.spec_version, trial.spec_content_hash],
            "artifact": [
                trial.artifact_id,
                trial.artifact_version,
                trial.artifact_content_hash,
            ],
            "forecast_identities": [
                [item.forecast_id, item.forecast_version, item.content_hash]
                for item in trial.forecasts
            ],
            "research_authorization": [
                trial.research_trial_id,
                trial.research_trial_version,
                trial.research_trial_content_hash,
                trial.split_spec_hash,
                trial.parameter_hash,
                trial.calendar_schedule_hash,
                trial.evaluation_policy_id,
                trial.evaluation_policy_version,
                trial.evaluation_policy_content_hash,
            ],
            "actual_manifest": [
                trial.actual_manifest_id,
                trial.actual_manifest_version,
                trial.actual_manifest_content_hash,
            ],
            "promotion_seal_hash": trial.content_hash,
        },
        "reason_codes": list(reason_codes),
        "window": [_utc_text(decided_at), _utc_text(recorded_at), _utc_text(valid_until)],
        "research_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }


def r1_forecast_promotion_decision_hash(decision: R1ForecastPromotionDecision) -> str:
    """Recompute one exact Research promotion decision digest."""

    return _hash_payload(
        _promotion_decision_payload(
            decision_id=decision.decision_id,
            decision_version=decision.decision_version,
            owner=decision.owner,
            capability=decision.capability,
            purpose=decision.purpose,
            promotion_scope=decision.promotion_scope,
            outcome=decision.outcome,
            policy=decision.policy,
            trial=decision.trial,
            policy_gate_outcomes=decision.policy_gate_outcomes,
            reason_codes=decision.reason_codes,
            decided_at=decision.decided_at,
            recorded_at=decision.recorded_at,
            valid_until=decision.valid_until,
        )
    )


def _evaluate_policy_gates(
    policy: R1ForecastPromotionPolicy,
    trial: R1ForecastTrialPromotionSeal,
) -> tuple[R1PromotionPolicyGateOutcome, ...]:
    minimum_coverage = min(item.coverage for item in trial.metric_evidence)
    values = (
        (
            R1PromotionGateCode.REQUIRED_TRIAL_STATE,
            trial.trial_state is policy.required_trial_state,
            None,
            None,
        ),
        (
            R1PromotionGateCode.MINIMUM_METRIC_COVERAGE,
            minimum_coverage >= policy.minimum_metric_coverage,
            minimum_coverage,
            policy.minimum_metric_coverage,
        ),
        (
            R1PromotionGateCode.ALL_METRIC_COMPARISONS_PASS,
            all(item.passes for item in trial.metric_evidence),
            None,
            None,
        ),
        (
            R1PromotionGateCode.ALL_INVALIDATION_OUTCOMES_PASS,
            all(item.passes for item in trial.invalidation_evidence),
            None,
            None,
        ),
    )
    return tuple(
        R1PromotionPolicyGateOutcome(
            gate_code=gate_code,
            passes=passes,
            reason_code="" if passes else f"{gate_code.value}_not_met",
            observed_coverage=observed,
            required_coverage=required,
        )
        for gate_code, passes, observed, required in values
    )


def r1_forecast_promotion_decision_valid_until(
    *,
    policy: R1ForecastPromotionPolicy,
    result: ForecastBaselineTrialResult,
    as_of: datetime,
) -> datetime:
    """Return the sole canonical upper bound for one decision receipt."""

    _require_aware(as_of, "R1 promotion validity as_of")
    return min(
        result.valid_until,
        policy.active_until,
        as_of + timedelta(seconds=policy.decision_validity_seconds),
    )


def _trial_seal_payload(
    *,
    result_id: str,
    result_version: str,
    result_content_hash: str,
    spec_id: str,
    spec_version: str,
    spec_content_hash: str,
    artifact_id: str,
    artifact_version: str,
    artifact_content_hash: str,
    promotion_scope: R1PromotionScope,
    forecasts: tuple[R1PromotionForecastIdentity, ...],
    research_trial_id: str,
    research_trial_version: str,
    research_trial_content_hash: str,
    split_spec_hash: str,
    parameter_hash: str,
    calendar_schedule_hash: str,
    evaluation_policy_id: str,
    evaluation_policy_version: str,
    evaluation_policy_content_hash: str,
    actual_manifest_id: str,
    actual_manifest_version: str,
    actual_manifest_content_hash: str,
    expected_period_ends: tuple[date, ...],
    metric_codes: tuple[str, ...],
    metric_evidence: tuple[R1PromotionMetricEvidence, ...],
    invalidation_evidence: tuple[R1PromotionInvalidationEvidence, ...],
    trial_state: R1PromotionTrialState,
    evaluated_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "research-r1-forecast-trial-promotion-seal.v1",
        "result": [
            result_id,
            result_version,
            result_content_hash,
        ],
        "spec": [spec_id, spec_version, spec_content_hash],
        "artifact": [
            artifact_id,
            artifact_version,
            artifact_content_hash,
        ],
        "promotion_scope": [promotion_scope.scope_id, promotion_scope.content_hash],
        "forecasts": [
            [
                item.forecast_id,
                item.forecast_version,
                item.content_hash,
                item.subject_code,
                item.industry_code,
                item.candidate_scenario,
                item.horizon_quarters,
                list(item.metric_codes),
                item.target_period_end.isoformat(),
                _utc_text(item.as_of_time),
                _utc_text(item.persisted_at),
            ]
            for item in forecasts
            if isinstance(item, R1PromotionForecastIdentity)
        ],
        "research_authorization": [
            research_trial_id,
            research_trial_version,
            research_trial_content_hash,
            split_spec_hash,
            parameter_hash,
            calendar_schedule_hash,
            evaluation_policy_id,
            evaluation_policy_version,
            evaluation_policy_content_hash,
        ],
        "actual_manifest": [
            actual_manifest_id,
            actual_manifest_version,
            actual_manifest_content_hash,
        ],
        "expected_period_ends": [item.isoformat() for item in expected_period_ends],
        "metric_codes": list(metric_codes),
        "metric_evidence": [
            [
                item.metric_code,
                item.error_metric,
                _decimal_text(item.forecast_error),
                _decimal_text(item.baseline_error),
                _decimal_text(item.improvement),
                item.sample_count,
                _decimal_text(item.coverage),
                item.passes,
                list(item.reason_codes),
            ]
            for item in metric_evidence
        ],
        "invalidation_evidence": [
            [
                item.rule_code,
                item.metric_code,
                item.passes,
                item.triggered_at.isoformat() if item.triggered_at is not None else None,
                list(item.reason_codes),
            ]
            for item in invalidation_evidence
        ],
        "trial_state": trial_state.value,
        "window": [_utc_text(evaluated_at), _utc_text(valid_until)],
    }


def r1_forecast_trial_promotion_seal_hash(seal: R1ForecastTrialPromotionSeal) -> str:
    """Recompute the complete typed Equity result identity seal."""

    return _hash_payload(
        _trial_seal_payload(
            result_id=seal.result_id,
            result_version=seal.result_version,
            result_content_hash=seal.result_content_hash,
            spec_id=seal.spec_id,
            spec_version=seal.spec_version,
            spec_content_hash=seal.spec_content_hash,
            artifact_id=seal.artifact_id,
            artifact_version=seal.artifact_version,
            artifact_content_hash=seal.artifact_content_hash,
            promotion_scope=seal.promotion_scope,
            forecasts=seal.forecasts,
            research_trial_id=seal.research_trial_id,
            research_trial_version=seal.research_trial_version,
            research_trial_content_hash=seal.research_trial_content_hash,
            split_spec_hash=seal.split_spec_hash,
            parameter_hash=seal.parameter_hash,
            calendar_schedule_hash=seal.calendar_schedule_hash,
            evaluation_policy_id=seal.evaluation_policy_id,
            evaluation_policy_version=seal.evaluation_policy_version,
            evaluation_policy_content_hash=seal.evaluation_policy_content_hash,
            actual_manifest_id=seal.actual_manifest_id,
            actual_manifest_version=seal.actual_manifest_version,
            actual_manifest_content_hash=seal.actual_manifest_content_hash,
            expected_period_ends=seal.expected_period_ends,
            metric_codes=seal.metric_codes,
            metric_evidence=seal.metric_evidence,
            invalidation_evidence=seal.invalidation_evidence,
            trial_state=seal.trial_state,
            evaluated_at=seal.evaluated_at,
            valid_until=seal.valid_until,
        )
    )
