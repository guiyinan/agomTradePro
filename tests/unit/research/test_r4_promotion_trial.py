"""Unit coverage for exact R4 Portfolio/R3 trial sealing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.research.domain.r4_promotion_evidence import (
    R4PromotionR3AttestationEvidence,
)
from apps.research.domain.r4_promotion_trial import R4PromotionTrialSeal, R4PromotionTrialState
from tests.unit.portfolio.macro_risk_rolling_factories import build_study
from tests.unit.research.r4_promotion_factories import (
    portfolio_record,
    portfolio_record_seal,
    promotion_policy,
    promotion_trial,
    r3_evidence,
    study_registration,
)


def test_trial_binds_exact_owner_record_all_subhashes_and_current_r3() -> None:
    policy = promotion_policy()
    record = portfolio_record_seal()

    trial = promotion_trial(policy=policy, record_seal=record)

    assert trial.state is R4PromotionTrialState.READY_FOR_POLICY_EVALUATION
    assert trial.blocker_codes == ()
    assert trial.scope == policy.scope
    assert trial.policy_content_hash == policy.content_hash
    assert trial.portfolio_record == record
    assert trial.current_r3_attestation == record.record_r3_attestation
    assert trial.observed_fold_count == 2
    assert str(trial.regime_coverage_ratio) == "1"
    assert len(trial.portfolio_record.record_subhashes) > 20
    assert len(trial.portfolio_record.window_metrics) == 6
    assert len(trial.portfolio_record.method_summaries) == 3
    assert trial.portfolio_record.producer_code_version == "git:r4-code-v1"
    assert trial.portfolio_record.dependency_lock_hash == "a" * 64
    assert trial.valid_until == min(
        record.valid_until,
        trial.current_r3_attestation.effective_valid_until,
    )


def test_policy_must_be_recorded_and_active_before_first_selection_cutoff() -> None:
    late = datetime(2026, 2, 11, 13, tzinfo=UTC)
    policy = promotion_policy(recorded_at=late, active_from=late)

    with pytest.raises(ValueError, match="not preregistered before selection"):
        promotion_trial(policy=policy)


def test_exact_study_split_cost_universe_and_factor_registration_is_enforced() -> None:
    registration = study_registration()
    changed = type(registration).create(
        study_family_id=registration.study_family_id,
        study_id=registration.study_id,
        universe_policy_id=registration.universe_policy_id,
        asset_codes=registration.asset_codes,
        factor_policy_id=registration.factor_policy_id,
        factor_codes=registration.factor_codes,
        split_policy_id=registration.split_policy_id,
        split_policy_version="different-split.v1",
        cost_semantics_id=registration.cost_semantics_id,
        cost_semantics_version=registration.cost_semantics_version,
    )

    with pytest.raises(ValueError, match="split policy differs"):
        promotion_trial(policy=promotion_policy(registration=changed))


def test_current_r3_must_be_exact_equal_and_active_at_trial_time() -> None:
    current = r3_evidence()
    substituted = R4PromotionR3AttestationEvidence.create(
        artifact_id=current.artifact_id,
        artifact_version=current.artifact_version,
        artifact_content_hash=current.artifact_content_hash,
        decision_id=current.decision_id,
        decision_version=current.decision_version,
        decision_content_hash="b" * 64,
        approved_at=current.approved_at,
        valid_until=current.valid_until,
        retired_at=current.retired_at,
        attestation_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="differs from the record"):
        promotion_trial(current_r3=substituted)

    with pytest.raises(ValueError, match="inactive"):
        R4PromotionTrialSeal.create(
            trial_id="retired-trial",
            trial_version="trial.v1",
            policy=promotion_policy(),
            portfolio_record=portfolio_record_seal(),
            current_r3_attestation=current,
            evaluated_at=current.valid_until,
        )


def test_blocked_portfolio_artifact_produces_auditable_blocked_trial() -> None:
    blocked_record = portfolio_record(
        study=build_study(minimum_regime_windows=3),
    )

    trial = promotion_trial(record_seal=portfolio_record_seal(record=blocked_record))

    assert trial.state is R4PromotionTrialState.BLOCKED
    assert "portfolio_artifact_ineligible" in trial.blocker_codes
    assert trial.content_hash
