"""Meaningful boundary coverage for the Research-owned R1 decision contracts."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.research.domain.r1_forecast_promotion_decision import (
    R1ForecastTrialPromotionSeal,
    R1PromotionGateCode,
    R1PromotionPolicyGateOutcome,
    R1PromotionPolicyIdentity,
    R1PromotionScope,
    R1PromotionTrialState,
    _decimal_text,
    _hash_payload,
    _promotion_scope_payload,
    create_r1_forecast_promotion_decision,
)
from tests.unit.research.test_r1_forecast_promotion import (
    _decision,
    _eligible_result,
    _ineligible_result,
    _policy,
    _rehash_decision,
)


def _scope_with(scope: R1PromotionScope, **changes: object) -> R1PromotionScope:
    """Build a canonical scope variant through its public dataclass constructor."""

    values = {field.name: getattr(scope, field.name) for field in fields(scope)}
    values.update(changes)
    digest = _hash_payload(
        _promotion_scope_payload(
            owner=values["owner"],
            capability=values["capability"],
            purpose=values["purpose"],
            subject_code=values["subject_code"],
            industry_code=values["industry_code"],
            candidate_scenario=values["candidate_scenario"],
            horizon_quarters=values["horizon_quarters"],
            calendar_schedule_hash=values["calendar_schedule_hash"],
            metric_codes=values["metric_codes"],
        )
    )
    values["scope_id"] = f"r1v:{digest}"
    values["content_hash"] = digest
    return R1PromotionScope(**values)


def test_scope_rejects_invalid_token_hash_horizon_metrics_and_authority() -> None:
    scope = _decision().promotion_scope

    with pytest.raises(ValueError, match="scope subject_code must be a bounded token"):
        replace(scope, subject_code="")
    with pytest.raises(ValueError, match="calendar_schedule_hash must be a lowercase"):
        replace(scope, calendar_schedule_hash="invalid")
    with pytest.raises(ValueError, match="horizon_quarters must be positive"):
        replace(scope, horizon_quarters=0)
    with pytest.raises(ValueError, match="metric_codes must be unique and ordered"):
        replace(scope, metric_codes=(scope.metric_codes[0], scope.metric_codes[0]))
    with pytest.raises(ValueError, match="scope authority is invalid"):
        replace(scope, owner="equity")
    with pytest.raises(ValueError, match="identity or content hash mismatch"):
        replace(scope, content_hash="0" * 64)


def test_decimal_and_policy_boundaries_remain_fail_closed() -> None:
    policy = _policy()

    with pytest.raises(ValueError, match="canonical decimal must be finite"):
        _decimal_text(Decimal("NaN"))
    with pytest.raises(ValueError, match="must be timezone-aware"):
        replace(policy, active_from=datetime(2025, 1, 1))
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        replace(policy, minimum_metric_coverage=Decimal("1.1"))
    with pytest.raises(ValueError, match="must be active"):
        replace(policy, status="paused")
    with pytest.raises(ValueError, match="gates must be booleans"):
        replace(policy, require_all_metric_comparisons_pass=1)
    with pytest.raises(ValueError, match="decision_validity_seconds must be within one year"):
        replace(policy, decision_validity_seconds=0)
    with pytest.raises(ValueError, match="must remain research-only"):
        replace(policy, research_only=False)


def test_policy_identity_and_gate_outcomes_validate_state_and_coverage() -> None:
    valid_identity = R1PromotionPolicyIdentity(
        policy_id="policy:r1",
        policy_version="v1",
        content_hash="0" * 64,
        owner="research",
        capability="r1",
        purpose="valuation",
    )
    assert valid_identity.owner == "research"
    with pytest.raises(ValueError, match="decision policy authority is invalid"):
        R1PromotionPolicyIdentity(
            policy_id="policy:r1",
            policy_version="v1",
            content_hash="0" * 64,
            owner="equity",
            capability="r1",
            purpose="valuation",
        )

    with pytest.raises(ValueError, match="passes must be boolean"):
        R1PromotionPolicyGateOutcome(
            R1PromotionGateCode.REQUIRED_TRIAL_STATE,
            passes=1,
            reason_code="",
        )
    with pytest.raises(ValueError, match="reason does not match"):
        R1PromotionPolicyGateOutcome(
            R1PromotionGateCode.REQUIRED_TRIAL_STATE,
            passes=False,
            reason_code="wrong_reason",
        )
    with pytest.raises(ValueError, match="coverage gate requires"):
        R1PromotionPolicyGateOutcome(
            R1PromotionGateCode.MINIMUM_METRIC_COVERAGE,
            passes=False,
            reason_code="minimum_metric_coverage_not_met",
        )
    with pytest.raises(ValueError, match="coverage gate state is inconsistent"):
        R1PromotionPolicyGateOutcome(
            R1PromotionGateCode.MINIMUM_METRIC_COVERAGE,
            passes=True,
            reason_code="",
            observed_coverage=Decimal("0.5"),
            required_coverage=Decimal("1"),
        )
    with pytest.raises(ValueError, match="non-coverage gate cannot carry"):
        R1PromotionPolicyGateOutcome(
            R1PromotionGateCode.REQUIRED_TRIAL_STATE,
            passes=True,
            reason_code="",
            observed_coverage=Decimal("1"),
            required_coverage=Decimal("1"),
        )


def test_forecast_identity_rejects_version_horizon_metrics_and_knowledge_order() -> None:
    forecast = _decision().trial.forecasts[0]

    with pytest.raises(ValueError, match="forecast_version must be positive"):
        replace(forecast, forecast_version=0)
    with pytest.raises(ValueError, match="horizon_quarters must be positive"):
        replace(forecast, horizon_quarters=0)
    with pytest.raises(ValueError, match="metric_codes must be unique and ordered"):
        replace(forecast, metric_codes=(forecast.metric_codes[0], forecast.metric_codes[0]))
    with pytest.raises(ValueError, match="persistence predates"):
        replace(forecast, persisted_at=forecast.as_of_time - timedelta(seconds=1))


def test_metric_and_invalidation_evidence_reject_noncanonical_values() -> None:
    metric = _decision().trial.metric_evidence[0]
    with pytest.raises(ValueError, match="forecast_error must be a finite Decimal"):
        replace(metric, forecast_error=Decimal("Infinity"))
    with pytest.raises(ValueError, match="sample_count must be non-negative"):
        replace(metric, sample_count=-1)
    with pytest.raises(ValueError, match="metric passes must be boolean"):
        replace(metric, passes=1)
    with pytest.raises(ValueError, match="reason_codes must be unique and ordered"):
        replace(metric, reason_codes=("z", "a"))

    invalidation = R1ForecastTrialPromotionSeal.from_result(
        _ineligible_result()
    ).invalidation_evidence[0]
    with pytest.raises(ValueError, match="invalidation state is inconsistent"):
        replace(invalidation, passes=False)
    with pytest.raises(ValueError, match="reason_codes must be unique and ordered"):
        replace(invalidation, reason_codes=("z", "a"))


def test_trial_seal_rejects_window_scope_period_metric_and_state_substitution() -> None:
    trial = _decision().trial
    alternate_scope = _scope_with(trial.promotion_scope, subject_code="000001.SZ")

    with pytest.raises(ValueError, match="validity must follow evaluation"):
        replace(trial, valid_until=trial.evaluated_at)
    with pytest.raises(ValueError, match="promotion scope does not match"):
        replace(trial, promotion_scope=alternate_scope)
    with pytest.raises(ValueError, match="exact expected periods"):
        replace(trial, expected_period_ends=())
    with pytest.raises(ValueError, match="exact evaluation order"):
        replace(trial, metric_evidence=())
    with pytest.raises(ValueError, match="state does not match"):
        replace(trial, trial_state=R1PromotionTrialState.NOT_ELIGIBLE)


def test_decision_rejects_authority_scope_reason_policy_window_and_research_flags() -> None:
    decision = _decision()
    alternate_scope = _scope_with(decision.promotion_scope, subject_code="000001.SZ")

    with pytest.raises(ValueError, match="decision authority is invalid"):
        replace(decision, owner="equity")
    with pytest.raises(ValueError, match="policy authority was substituted"):
        replace(decision, promotion_scope=alternate_scope)
    with pytest.raises(ValueError, match="reason_codes must be unique and ordered"):
        replace(decision, reason_codes=("promotion_policy_satisfied", "promotion_policy_satisfied"))

    result = _eligible_result()
    short_policy = _policy(active_until=result.valid_until - timedelta(days=2), result=result)
    valid = create_r1_forecast_promotion_decision(
        decision_id="research-r1-promotion:window",
        decision_version="decision.v1",
        policy=short_policy,
        result=result,
        as_of=result.evaluated_at + timedelta(hours=1),
        recorded_at=result.evaluated_at + timedelta(hours=1, minutes=1),
    )
    with pytest.raises(ValueError, match="outside the sealed policy window"):
        _rehash_decision(valid, valid_until=short_policy.active_until + timedelta(seconds=1))
    with pytest.raises(ValueError, match="must remain research-only"):
        _rehash_decision(valid, research_only=False)
