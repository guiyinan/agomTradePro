"""Runtime contract tests for governed capability-readiness attestations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from apps.research.composition import make_evaluate_capability_readiness
from apps.research.domain.capability_readiness import (
    ReadinessDecision,
    ReadinessRequirement,
    ReadinessState,
    ResearchCapability,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
R8_ATTESTATION_TIME = datetime(2026, 8, 9, 12, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _states(
    capability: ResearchCapability,
    *,
    evaluated_at: datetime = NOW,
) -> dict[ReadinessRequirement, ReadinessState]:
    report = make_evaluate_capability_readiness().execute(
        capability=capability,
        evaluated_at=evaluated_at,
    )
    assert report.decision is ReadinessDecision.BLOCKED
    return {item.requirement: item.state for item in report.evidence}


def test_r3_runtime_attests_research_mechanisms_but_not_data_or_model_readiness() -> None:
    states = _states(ResearchCapability.MACRO_FACTOR_NOWCAST)

    assert states[ReadinessRequirement.EXPERIMENT_REGISTRY] is ReadinessState.VERIFIED
    assert states[ReadinessRequirement.MULTIPLE_TEST_FAMILY] is ReadinessState.VERIFIED
    assert states[ReadinessRequirement.PROMOTION_DECISION] is ReadinessState.VERIFIED
    assert states[ReadinessRequirement.SPLIT_AND_EMBARGO_POLICY] is ReadinessState.VERIFIED
    assert states[ReadinessRequirement.TARGET_MACRO_VINTAGES_PIT] is (ReadinessState.UNVERIFIED)
    assert states[ReadinessRequirement.MACRO_FACTOR_BENCHMARK] is ReadinessState.MISSING


def test_r7_runtime_keeps_binding_outcomes_and_samples_blocked() -> None:
    states = _states(ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION)

    assert states[ReadinessRequirement.GOVERNED_SCENARIO_VERSIONS] is (ReadinessState.VERIFIED)
    assert states[ReadinessRequirement.APPEND_ONLY_FORECAST_LEDGER] is (ReadinessState.VERIFIED)
    assert states[ReadinessRequirement.SUBJECTIVE_MODEL_PROBABILITY_SEPARATION] is (
        ReadinessState.VERIFIED
    )
    assert states[ReadinessRequirement.SCENARIO_VERSION_LEDGER_BINDING] is (ReadinessState.VERIFIED)
    assert states[ReadinessRequirement.COMPLETE_SCENARIO_OUTCOME_HISTORY] is (
        ReadinessState.MISSING
    )
    assert states[ReadinessRequirement.CALIBRATION_SAMPLE_POLICY] is (ReadinessState.UNVERIFIED)


def test_r5_runtime_attests_research_only_scope_without_inventing_data() -> None:
    states = _states(ResearchCapability.FIXED_INCOME_RELATIVE_VALUE)

    assert states[ReadinessRequirement.FIXED_INCOME_RESEARCH_ONLY_SCOPE] is (
        ReadinessState.VERIFIED
    )
    assert states[ReadinessRequirement.TWO_RELIABLE_CURVES_PUBLISHED] is ReadinessState.UNVERIFIED
    assert states[ReadinessRequirement.DURATION_CONVEXITY_RECONCILED] is ReadinessState.UNVERIFIED


def test_r8_runtime_attests_optimizer_mechanisms_without_inventing_live_evidence() -> None:
    states = _states(
        ResearchCapability.MULTI_ASSET_OPTIMIZATION,
        evaluated_at=R8_ATTESTATION_TIME,
    )

    assert states[ReadinessRequirement.PORTFOLIO_PLANNING_CONSTRAINTS] is (ReadinessState.VERIFIED)
    assert states[ReadinessRequirement.RISK_CENTER_SCENARIO_INPUT] is (ReadinessState.VERIFIED)
    assert states[ReadinessRequirement.PORTFOLIO_CANONICAL_SNAPSHOT] is (ReadinessState.UNVERIFIED)
    assert states[ReadinessRequirement.R3_PROMOTED_FACTOR_VERSION] is (ReadinessState.UNVERIFIED)
    assert states[ReadinessRequirement.EXECUTION_FEEDBACK_RECONCILED] is (ReadinessState.MISSING)
    assert states[ReadinessRequirement.OPTIMIZER_INPUT_CONTRACT] is ReadinessState.VERIFIED
    assert states[ReadinessRequirement.OPTIMIZER_BASELINE_FAIL_CLOSED_POLICY] is (
        ReadinessState.VERIFIED
    )


def test_runtime_verified_evidence_is_time_bounded_and_auditable() -> None:
    report = make_evaluate_capability_readiness().execute(
        capability=ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION,
        evaluated_at=NOW,
    )
    verified = tuple(item for item in report.evidence if item.state is ReadinessState.VERIFIED)

    assert verified
    assert all(item.evidence_ref and item.evidence_ref.startswith("repo://") for item in verified)
    assert all(item.observed_at <= NOW for item in verified)
    assert all(item.valid_until is not None and item.valid_until > NOW for item in verified)
    for item in verified:
        assert item.evidence_ref is not None
        for reference in item.evidence_ref.split("|"):
            path_with_anchor = reference.split("://", maxsplit=1)[1]
            relative_path = path_with_anchor.split("#", maxsplit=1)[0]
            assert (REPOSITORY_ROOT / relative_path).is_file()


def test_expired_runtime_attestations_turn_stale_instead_of_extending_themselves() -> None:
    report = make_evaluate_capability_readiness().execute(
        capability=ResearchCapability.SCENARIO_PROBABILITY_CALIBRATION,
        evaluated_at=datetime(2026, 11, 6, 12, tzinfo=UTC),
    )
    states = {item.requirement: item.state for item in report.evidence}

    assert states[ReadinessRequirement.GOVERNED_SCENARIO_VERSIONS] is ReadinessState.STALE
    assert states[ReadinessRequirement.APPEND_ONLY_FORECAST_LEDGER] is ReadinessState.STALE
