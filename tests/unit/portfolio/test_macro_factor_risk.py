"""Tests for the R4 macro-factor risk research contract."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.portfolio.application.macro_factor_risk import EvaluateMacroRiskCandidate
from apps.portfolio.domain.macro_factor_risk import (
    AssetAllocation,
    AssetMacroExposure,
    FactorCovarianceVersion,
    MacroExposureVersion,
    MacroFactorBeta,
    MacroRiskBlockerCode,
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskValidationPolicy,
    build_macro_risk_input_hash,
    evaluate_macro_risk_candidate,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _policy() -> MacroRiskValidationPolicy:
    return MacroRiskValidationPolicy(
        version="r4-policy-v1",
        weight_sum_tolerance=Decimal("0.000001"),
        covariance_symmetry_tolerance=Decimal("0.000001"),
        covariance_psd_tolerance=Decimal("0.000001"),
        contribution_identity_tolerance=Decimal("0.000001"),
        minimum_r_squared=Decimal("0.20"),
        minimum_stability_score=Decimal("0.60"),
        maximum_turnover=Decimal("0.80"),
        maximum_expected_cost=Decimal("0.01"),
        macro_risk_parity_tolerance=Decimal("0.02"),
    )


def _exposure() -> MacroExposureVersion:
    return MacroExposureVersion(
        version_id="exposure-v1",
        promoted_factor_version="macro-factor-v7",
        promotion_decision_id="promotion-r3-approved-7",
        pit_manifest_id="manifest-2026q2",
        code_version="git:abc123",
        parameter_version="exposure-policy-v3",
        observed_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=7),
        exposures=(
            AssetMacroExposure(
                asset_code="asset-a",
                betas=(
                    MacroFactorBeta("growth", Decimal("1"), Decimal("0.8"), Decimal("1.2")),
                    MacroFactorBeta("inflation", Decimal("0"), Decimal("-0.1"), Decimal("0.1")),
                ),
                residual_variance=Decimal("0.01"),
                r_squared=Decimal("0.7"),
                stability_score=Decimal("0.8"),
            ),
            AssetMacroExposure(
                asset_code="asset-b",
                betas=(
                    MacroFactorBeta("growth", Decimal("0"), Decimal("-0.1"), Decimal("0.1")),
                    MacroFactorBeta("inflation", Decimal("1"), Decimal("0.8"), Decimal("1.2")),
                ),
                residual_variance=Decimal("0.01"),
                r_squared=Decimal("0.7"),
                stability_score=Decimal("0.8"),
            ),
        ),
    )


def _covariance(values: tuple[tuple[Decimal, ...], ...] | None = None) -> FactorCovarianceVersion:
    return FactorCovarianceVersion(
        version_id="factor-cov-v1",
        factor_codes=("growth", "inflation"),
        values=values
        or (
            (Decimal("0.04"), Decimal("0")),
            (Decimal("0"), Decimal("0.04")),
        ),
        pit_manifest_id="manifest-2026q2",
        estimator_version="sample-cov-v2",
        observed_at=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=7),
    )


def _allocations() -> tuple[AssetAllocation, ...]:
    return (
        AssetAllocation(
            asset_code="asset-a",
            current_weight=Decimal("0.5"),
            candidate_weight=Decimal("0.5"),
            minimum_weight=Decimal("0"),
            maximum_weight=Decimal("1"),
            maximum_trade_weight=Decimal("0.5"),
        ),
        AssetAllocation(
            asset_code="asset-b",
            current_weight=Decimal("0.5"),
            candidate_weight=Decimal("0.5"),
            minimum_weight=Decimal("0"),
            maximum_weight=Decimal("1"),
            maximum_trade_weight=Decimal("0.5"),
        ),
    )


def _candidate(
    *,
    covariance: FactorCovarianceVersion | None = None,
    allocations: tuple[AssetAllocation, ...] | None = None,
) -> MacroRiskCandidateInput:
    exposure = _exposure()
    selected_covariance = covariance or _covariance()
    selected_allocations = allocations or _allocations()
    digest = build_macro_risk_input_hash(
        candidate_id="candidate-r4-1",
        kind=MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
        canonical_portfolio_snapshot_id="portfolio-snapshot-4",
        exposure_version=exposure,
        covariance_version=selected_covariance,
        cost_model_version="cost-model-v2",
        constraint_version="constraint-v9",
        allocations=selected_allocations,
        expected_cost=Decimal("0.001"),
        created_at=NOW,
    )
    return MacroRiskCandidateInput(
        candidate_id="candidate-r4-1",
        kind=MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
        canonical_portfolio_snapshot_id="portfolio-snapshot-4",
        exposure_version=exposure,
        covariance_version=selected_covariance,
        cost_model_version="cost-model-v2",
        constraint_version="constraint-v9",
        allocations=selected_allocations,
        expected_cost=Decimal("0.001"),
        created_at=NOW,
        input_hash=digest,
    )


def test_balanced_candidate_preserves_risk_identity_and_stays_research_only() -> None:
    report = evaluate_macro_risk_candidate(_candidate(), policy=_policy(), evaluated_at=NOW)

    assert report.eligible_for_research_comparison is True
    assert report.factor_variance == Decimal("0.0200")
    assert report.residual_variance == Decimal("0.0050")
    assert sum(item.variance_contribution for item in report.contributions) == (
        report.factor_variance
    )
    assert tuple(item.contribution_share for item in report.contributions) == (
        Decimal("0.5"),
        Decimal("0.5"),
    )
    assert report.usage_scope == "research_only"
    assert report.must_not_use_for_decision is True
    assert report.must_not_execute is True
    assert len(report.evidence_hash) == 64


def test_non_psd_covariance_fails_closed() -> None:
    covariance = _covariance(
        (
            (Decimal("0.01"), Decimal("0.02")),
            (Decimal("0.02"), Decimal("0.01")),
        )
    )
    report = evaluate_macro_risk_candidate(
        _candidate(covariance=covariance),
        policy=_policy(),
        evaluated_at=NOW,
    )

    assert report.eligible_for_research_comparison is False
    assert MacroRiskBlockerCode.COVARIANCE_NOT_PSD in {blocker.code for blocker in report.blockers}


def test_constraints_and_expired_evidence_fail_closed() -> None:
    allocations = (
        replace(_allocations()[0], candidate_weight=Decimal("1.01"), maximum_weight=Decimal("0.7")),
        replace(_allocations()[1], candidate_weight=Decimal("-0.01")),
    )
    report = evaluate_macro_risk_candidate(
        _candidate(allocations=allocations),
        policy=_policy(),
        evaluated_at=NOW + timedelta(days=8),
    )
    codes = {blocker.code for blocker in report.blockers}

    assert MacroRiskBlockerCode.EVIDENCE_EXPIRED in codes
    assert MacroRiskBlockerCode.WEIGHT_BOUND_BREACHED in codes
    assert MacroRiskBlockerCode.LIQUIDITY_BREACHED in codes


def test_tampered_input_hash_is_rejected() -> None:
    with pytest.raises(ValueError, match="input_hash"):
        evaluate_macro_risk_candidate(
            replace(_candidate(), input_hash="0" * 64),
            policy=_policy(),
            evaluated_at=NOW,
        )


def test_future_evaluation_cannot_see_candidate_or_inputs() -> None:
    report = evaluate_macro_risk_candidate(
        _candidate(),
        policy=_policy(),
        evaluated_at=NOW - timedelta(days=2),
    )

    assert MacroRiskBlockerCode.EVIDENCE_NOT_YET_OBSERVED in {
        blocker.code for blocker in report.blockers
    }


def test_versioned_cost_budget_fails_closed() -> None:
    report = evaluate_macro_risk_candidate(
        _candidate(),
        policy=replace(_policy(), maximum_expected_cost=Decimal("0.0001")),
        evaluated_at=NOW,
    )

    assert MacroRiskBlockerCode.COST_BUDGET_BREACHED in {
        blocker.code for blocker in report.blockers
    }


class _Provider:
    def __init__(self, candidate: MacroRiskCandidateInput | None) -> None:
        self._candidate = candidate

    def get_candidate(self, candidate_id: str) -> MacroRiskCandidateInput | None:
        assert candidate_id == "candidate-r4-1"
        return self._candidate


def test_application_requires_canonical_candidate_evidence() -> None:
    with pytest.raises(LookupError, match="unavailable"):
        EvaluateMacroRiskCandidate(_Provider(None), _policy()).execute(
            candidate_id="candidate-r4-1",
            evaluated_at=NOW,
        )

    report = EvaluateMacroRiskCandidate(_Provider(_candidate()), _policy()).execute(
        candidate_id="candidate-r4-1",
        evaluated_at=NOW,
    )
    assert report.eligible_for_research_comparison is True
