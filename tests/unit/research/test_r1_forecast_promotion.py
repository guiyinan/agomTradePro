"""Domain contracts for exact Research-owned R1 forecast promotion."""

from __future__ import annotations

import inspect
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.equity.domain.forecast_baseline import (
    ForecastBaselineTrialResult,
    MapeZeroActualRule,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1PromotionDecisionOutcome,
    R1PromotionPolicyStatus,
    R1PromotionScope,
    R1PromotionTrialState,
    create_r1_forecast_promotion_decision,
)
from apps.research.domain.r1_forecast_promotion_decision import (
    _hash_payload,
    _promotion_decision_payload,
)
from tests.unit.equity.test_forecast_baseline import (
    _artifact,
    _paired_rows,
    _result,
    _spec,
)
from tests.unit.equity.test_forecast_baseline_application import _evaluate_trial


def _eligible_result():
    return _evaluate_trial()[2]


def _ineligible_result():
    spec = _spec(minimum_coverage=Decimal("1"), minimum_sample_count=2)
    return _result(spec, _artifact(spec, tie=True), _paired_rows(tie=True))


def _policy(
    *,
    minimum_metric_coverage: Decimal = Decimal("1"),
    offset: timezone = UTC,
    active_until: datetime | None = None,
    result: ForecastBaselineTrialResult | None = None,
) -> R1ForecastPromotionPolicy:
    trial = result or _eligible_result()
    evaluated = trial.evaluated_at.astimezone(offset)
    return R1ForecastPromotionPolicy.create(
        policy_id="research-r1-forecast-promotion",
        policy_version="policy.v1",
        owner="research",
        capability="r1",
        purpose="valuation",
        promotion_scope=R1PromotionScope.from_result(trial),
        status=R1PromotionPolicyStatus.ACTIVE,
        required_trial_state=R1PromotionTrialState.ELIGIBLE_FOR_PROMOTION,
        minimum_metric_coverage=minimum_metric_coverage,
        require_all_metric_comparisons_pass=True,
        require_all_invalidation_outcomes_pass=True,
        decision_validity_seconds=86_400,
        approved_at=evaluated - timedelta(days=3),
        recorded_at=evaluated - timedelta(days=2),
        active_from=evaluated - timedelta(days=1),
        active_until=(active_until or trial.valid_until).astimezone(offset),
    )


def _decision():
    result = _eligible_result()
    return create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:consumer:v1",
        decision_version="decision.v1",
        policy=_policy(),
        result=result,
        as_of=result.evaluated_at + timedelta(hours=1),
        recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
    )


def _rehash_decision(
    decision: R1ForecastPromotionDecision,
    **changes: object,
) -> R1ForecastPromotionDecision:
    values = {field.name: getattr(decision, field.name) for field in fields(decision)}
    values.update(changes)
    payload_values = {
        name: values[name] for name in inspect.signature(_promotion_decision_payload).parameters
    }
    values["content_hash"] = _hash_payload(_promotion_decision_payload(**payload_values))
    return R1ForecastPromotionDecision(**values)


def test_policy_hash_is_decimal_scale_and_timezone_independent() -> None:
    canonical = _policy()
    scaled = _policy(
        minimum_metric_coverage=Decimal("1.000"),
        offset=timezone(timedelta(hours=8)),
    )

    assert canonical.content_hash == scaled.content_hash
    with pytest.raises(ValueError, match="content hash mismatch"):
        replace(canonical, minimum_metric_coverage=Decimal("0.5"))
    with pytest.raises(ValueError, match="authority is invalid"):
        R1ForecastPromotionPolicy.create(
            **{
                name: getattr(canonical, name)
                for name in inspect.signature(R1ForecastPromotionPolicy.create).parameters
                if name != "owner"
            },
            owner="equity",
        )


def test_policy_rejects_post_hoc_receipt_and_implicit_trial_state() -> None:
    policy = _policy()
    with pytest.raises(ValueError, match="receipt/active window"):
        R1ForecastPromotionPolicy.create(
            **{
                name: (
                    policy.active_from + timedelta(seconds=1)
                    if name == "recorded_at"
                    else getattr(policy, name)
                )
                for name in inspect.signature(R1ForecastPromotionPolicy.create).parameters
            }
        )
    with pytest.raises(ValueError, match="require an eligible trial"):
        R1ForecastPromotionPolicy.create(
            **{
                name: (
                    R1PromotionTrialState.NOT_ELIGIBLE
                    if name == "required_trial_state"
                    else getattr(policy, name)
                )
                for name in inspect.signature(R1ForecastPromotionPolicy.create).parameters
            }
        )
    for field_name in (
        "require_all_metric_comparisons_pass",
        "require_all_invalidation_outcomes_pass",
    ):
        with pytest.raises(ValueError, match="cannot weaken"):
            R1ForecastPromotionPolicy.create(
                **{
                    name: False if name == field_name else getattr(policy, name)
                    for name in inspect.signature(R1ForecastPromotionPolicy.create).parameters
                }
            )


def test_decision_is_automatic_id_only_input_and_seals_full_trial_identity() -> None:
    result = _eligible_result()
    decision = _decision()

    assert tuple(inspect.signature(create_r1_forecast_promotion_decision).parameters) == (
        "decision_id",
        "decision_version",
        "policy",
        "result",
        "as_of",
        "recorded_at",
    )
    assert decision.outcome is R1PromotionDecisionOutcome.APPROVED
    assert decision.promotion_scope == decision.policy.promotion_scope
    assert decision.promotion_scope == decision.trial.promotion_scope
    assert decision.reason_codes == ("promotion_policy_satisfied",)
    assert decision.trial.result_content_hash == result.content_hash
    assert (
        decision.trial.spec_id,
        decision.trial.spec_version,
        decision.trial.spec_content_hash,
    ) == (result.spec_id, result.spec_version, result.spec_content_hash)
    assert (
        decision.trial.artifact_id,
        decision.trial.artifact_version,
        decision.trial.artifact_content_hash,
    ) == (
        result.baseline_artifact_id,
        result.baseline_artifact_version,
        result.baseline_artifact_content_hash,
    )
    assert tuple(item.content_hash for item in decision.trial.forecasts) == tuple(
        item.forecast_content_hash for item in result.forecasts
    )
    assert decision.trial.research_trial_content_hash == result.research_trial.trial_content_hash
    assert decision.trial.split_spec_hash == result.research_trial.split_spec_hash
    assert decision.trial.parameter_hash == result.research_trial.parameter_hash
    assert (
        decision.trial.actual_manifest_content_hash == result.actual_manifest.manifest_content_hash
    )
    assert decision.policy.content_hash == _policy().content_hash
    assert decision.valid_until == decision.decided_at + timedelta(days=1)
    assert decision.decided_at < decision.recorded_at < decision.valid_until
    assert (
        decision.research_only and decision.must_not_use_for_decision and decision.must_not_execute
    )


def test_ineligible_complete_trial_is_rejected_without_caller_outcome() -> None:
    result = _ineligible_result()
    policy = _policy(result=result)
    decision = create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:rejected:v1",
        decision_version="decision.v1",
        policy=policy,
        result=result,
        as_of=result.evaluated_at + timedelta(hours=1),
        recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
    )

    assert result.eligible_for_promotion is False
    assert decision.outcome is R1PromotionDecisionOutcome.REJECTED
    assert "required_trial_state_not_met" in decision.reason_codes
    assert "all_metric_comparisons_pass_not_met" in decision.reason_codes
    assert "promotion_policy_satisfied" not in decision.reason_codes


def test_stricter_research_coverage_gate_creates_auditable_rejection() -> None:
    spec = _spec(
        zero_rule=MapeZeroActualRule.EXCLUDE_WITH_COVERAGE_PENALTY,
        minimum_coverage=Decimal("0.5"),
        minimum_sample_count=1,
    )
    result = _result(
        spec,
        _artifact(spec),
        _paired_rows(second_margin_actual="0"),
    )
    policy = _policy(minimum_metric_coverage=Decimal("0.9"), result=result)

    assert result.eligible_for_promotion is True
    decision = create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:coverage-rejected",
        decision_version="decision.v1",
        policy=policy,
        result=result,
        as_of=result.evaluated_at + timedelta(hours=1),
        recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
    )

    assert decision.outcome is R1PromotionDecisionOutcome.REJECTED
    assert decision.reason_codes == ("minimum_metric_coverage_not_met",)
    coverage_gate = next(
        item
        for item in decision.policy_gate_outcomes
        if item.gate_code.value == "minimum_metric_coverage"
    )
    assert coverage_gate.observed_coverage == Decimal("0.5")
    assert coverage_gate.required_coverage == Decimal("0.9")


def test_decision_rejects_inactive_policy_or_trial_at_exact_expiry() -> None:
    result = _eligible_result()
    policy = _policy()
    with pytest.raises(ValueError, match="policy is unavailable or inactive"):
        create_r1_forecast_promotion_decision(
            decision_id="research-r1-promotion:late-policy",
            decision_version="decision.v1",
            policy=policy,
            result=result,
            as_of=policy.active_until,
            recorded_at=policy.active_until,
        )
    with pytest.raises(ValueError, match="trial result is inactive"):
        create_r1_forecast_promotion_decision(
            decision_id="research-r1-promotion:late-trial",
            decision_version="decision.v1",
            policy=_policy(active_until=result.valid_until + timedelta(days=1)),
            result=result,
            as_of=result.valid_until,
            recorded_at=result.valid_until,
        )


def test_trial_and_decision_hashes_reject_identity_or_outcome_tamper() -> None:
    decision = _decision()
    with pytest.raises(ValueError, match="trial promotion seal content hash mismatch"):
        replace(
            decision.trial,
            result_content_hash="0" * 64,
            content_hash=decision.trial.content_hash,
        )
    with pytest.raises(ValueError, match="decision content hash mismatch"):
        replace(decision, decision_version="decision.v2")
    with pytest.raises(ValueError, match="rejected R1 promotion"):
        replace(
            decision,
            outcome=R1PromotionDecisionOutcome.REJECTED,
            reason_codes=("caller_supplied_rejection",),
        )


def test_rehashed_outcome_gate_and_recorded_time_tampering_still_fail() -> None:
    approved = _decision()
    rejected_result = _ineligible_result()
    rejected = create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:rehashed-rejected",
        decision_version="decision.v1",
        policy=_policy(result=rejected_result),
        result=rejected_result,
        as_of=rejected_result.evaluated_at + timedelta(hours=1),
        recorded_at=rejected_result.evaluated_at + timedelta(hours=1, minutes=1),
    )
    with pytest.raises(ValueError, match="approved R1 promotion"):
        _rehash_decision(
            rejected,
            outcome=R1PromotionDecisionOutcome.APPROVED,
            reason_codes=("promotion_policy_satisfied",),
        )
    coverage_gate = approved.policy_gate_outcomes[1]
    with pytest.raises(ValueError, match="gate outcomes were substituted"):
        _rehash_decision(
            approved,
            policy_gate_outcomes=(
                approved.policy_gate_outcomes[0],
                replace(
                    coverage_gate,
                    observed_coverage=Decimal("0.5"),
                    passes=False,
                    reason_code="minimum_metric_coverage_not_met",
                ),
                *approved.policy_gate_outcomes[2:],
            ),
        )
    with pytest.raises(ValueError, match="gate outcomes were substituted"):
        _rehash_decision(
            approved,
            policy_gate_outcomes=tuple(reversed(approved.policy_gate_outcomes)),
        )
    with pytest.raises(ValueError, match="outside the trial window"):
        _rehash_decision(
            approved,
            recorded_at=approved.decided_at - timedelta(seconds=1),
        )


def test_decision_refuses_non_research_trial_flags() -> None:
    result = _eligible_result()
    with pytest.raises(ValueError, match="must remain research-only"):
        create_r1_forecast_promotion_decision(
            decision_id="research-r1-promotion:unsafe",
            decision_version="decision.v1",
            policy=_policy(),
            result=replace(result, must_not_execute=False, content_hash=result.content_hash),
            as_of=result.evaluated_at + timedelta(hours=1),
            recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
        )
