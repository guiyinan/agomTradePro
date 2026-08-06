"""Deterministic factories for R4 Research promotion unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
)
from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.portfolio.domain.macro_risk_rolling_contracts import R4RollingStudyInput
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    create_r4_promotion_decision,
)
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionMethodSummaryEvidence,
    R4PromotionR3AttestationEvidence,
    R4PromotionWindowEvidence,
    R4PromotionWindowMetricEvidence,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionScope,
    R4PromotionStudyRegistration,
)
from apps.research.domain.r4_promotion_trial import R4PromotionTrialSeal
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)

POLICY_RECORDED_AT = datetime(2025, 12, 15, tzinfo=UTC)
POLICY_ACTIVE_FROM = datetime(2026, 1, 1, tzinfo=UTC)
POLICY_ACTIVE_UNTIL = datetime(2026, 4, 1, tzinfo=UTC)
TRIAL_EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)
RECORD_RECORDED_AT = TRIAL_EVALUATED_AT + timedelta(minutes=1)
RECORD_VALID_UNTIL = datetime(2026, 3, 31, tzinfo=UTC)
DECIDED_AT = TRIAL_EVALUATED_AT + timedelta(minutes=3)
DECISION_RECORDED_AT = TRIAL_EVALUATED_AT + timedelta(minutes=4)


def promotion_scope() -> R4PromotionScope:
    """Return the stable macro-factor-risk-parity promotion scope."""

    return R4PromotionScope.create(
        study_family_id="r4-rolling-study-1",
        universe_policy_id="cn-two-asset-research-universe",
        factor_policy_id="growth-inflation-factor-family",
        split_policy_id="walk-forward-embargo-research",
        cost_semantics_id="gross-return-cost-separate",
    )


def study_registration() -> R4PromotionStudyRegistration:
    """Return exact bindings declared before the study selection cutoffs."""

    return R4PromotionStudyRegistration.create(
        study_family_id="r4-rolling-study-1",
        study_id="r4-rolling-study-1",
        universe_policy_id="cn-two-asset-research-universe",
        asset_codes=("asset-a", "asset-b"),
        factor_policy_id="growth-inflation-factor-family",
        factor_codes=("growth", "inflation"),
        split_policy_id="walk-forward-embargo-research",
        split_policy_version="r4-walk-forward.v1",
        cost_semantics_id="gross-return-cost-separate",
        cost_semantics_version="gross-cost-reported-separately.v1",
    )


def promotion_policy(
    *,
    scope: R4PromotionScope | None = None,
    registration: R4PromotionStudyRegistration | None = None,
    recorded_at: datetime = POLICY_RECORDED_AT,
    active_from: datetime = POLICY_ACTIVE_FROM,
    minimum_fold_count: int = 2,
    minimum_regime_coverage_ratio: Decimal = Decimal("1"),
    minimum_relative_net_return: Decimal = Decimal("0"),
) -> R4PromotionPolicy:
    """Return an explicit, no-default Research gate policy."""

    selected_scope = scope or promotion_scope()
    return R4PromotionPolicy.create(
        policy_id="r4-promotion-policy-main",
        policy_version="policy.v1",
        scope=selected_scope,
        registration=registration or study_registration(),
        required_methods=(
            MacroRiskCandidateKind.ASSET_RISK_PARITY,
            MacroRiskCandidateKind.EQUAL_WEIGHT,
            MacroRiskCandidateKind.MACRO_FACTOR_RISK_PARITY,
        ),
        reference_methods=(
            MacroRiskCandidateKind.ASSET_RISK_PARITY,
            MacroRiskCandidateKind.EQUAL_WEIGHT,
        ),
        minimum_fold_count=minimum_fold_count,
        minimum_regime_coverage_ratio=minimum_regime_coverage_ratio,
        minimum_relative_net_return=minimum_relative_net_return,
        maximum_relative_drawdown_increase=Decimal("1"),
        maximum_relative_volatility_increase=Decimal("1"),
        maximum_relative_cost_increase=Decimal("1"),
        decision_validity_seconds=86400,
        approved_at=datetime(2025, 12, 1, tzinfo=UTC),
        recorded_at=recorded_at,
        active_from=active_from,
        active_until=POLICY_ACTIVE_UNTIL,
    )


def portfolio_record(
    *,
    study: R4RollingStudyInput | None = None,
) -> R4RollingResearchRecord:
    """Return one factory-recomputed Portfolio R4 record."""

    return R4RollingResearchRecord.from_server_clock(
        draft=R4RollingResearchDraft(
            study=study or build_study(),
            promotion_attestation=promotion_attestation(),
            evaluated_at=TRIAL_EVALUATED_AT,
            producer_code_version="git:r4-code-v1",
            dependency_lock_hash="a" * 64,
            valid_until=RECORD_VALID_UNTIL,
        ),
        server_recorded_at=RECORD_RECORDED_AT,
    )


def r3_evidence() -> R4PromotionR3AttestationEvidence:
    """Return the exact authoritative R3 evidence projection."""

    attestation = promotion_attestation()
    return R4PromotionR3AttestationEvidence.create(
        artifact_id=attestation.artifact_id,
        artifact_version=attestation.artifact_version,
        artifact_content_hash=attestation.artifact_content_hash,
        decision_id=attestation.decision_id,
        decision_version=attestation.decision_version,
        decision_content_hash=attestation.decision_content_hash,
        approved_at=attestation.approved_at,
        valid_until=attestation.valid_until,
        retired_at=attestation.retired_at,
        attestation_hash=attestation.content_hash,
    )


def portfolio_record_seal(
    *,
    record: R4RollingResearchRecord | None = None,
) -> R4PromotionPortfolioRecordSeal:
    """Project every promotion-relevant field from a typed Portfolio record."""

    selected = record or portfolio_record()
    owner_record = R4RollingResearchOwnerRecord.create(selected)
    windows = tuple(
        R4PromotionWindowEvidence.create(
            fold_id=item.fold.fold_id,
            window_content_hash=item.content_hash,
            selection_as_of=item.selection_as_of,
            evaluation_as_of=item.evaluation_as_of,
            universe_id=item.asset_covariance.universe_id,
            universe_hash=item.asset_covariance.universe_hash,
            asset_codes=item.asset_covariance.asset_codes,
            factor_codes=item.macro_projection.exposure_version.factor_codes,
            macro_projection_hash=item.macro_projection.content_hash,
            covariance_hash=item.asset_covariance.content_hash,
            return_path_hash=item.return_path.content_hash,
            regime_assignment_hash=item.regime_assignment.content_hash,
        )
        for item in selected.study.windows
    )
    window_metrics = tuple(
        R4PromotionWindowMetricEvidence.create(
            fold_id=item.fold_id,
            method=item.kind,
            period_returns=item.period_returns,
            gross_return=item.gross_return,
            realized_variance=item.realized_variance,
            maximum_drawdown=item.maximum_drawdown,
            turnover=item.turnover,
            expected_cost=item.expected_cost,
            cost_semantics_version=item.cost_semantics_version,
            candidate_report_hash=item.candidate_report_hash,
            source_content_hash=item.content_hash,
        )
        for item in selected.artifact.window_metrics
    )
    method_summaries = tuple(
        R4PromotionMethodSummaryEvidence.create(
            method=item.kind,
            window_count=item.window_count,
            compounded_gross_return=item.compounded_gross_return,
            realized_variance=item.realized_variance,
            maximum_drawdown=item.maximum_drawdown,
            total_turnover=item.total_turnover,
            total_expected_cost=item.total_expected_cost,
            cost_semantics_version=item.cost_semantics_version,
            source_content_hash=item.content_hash,
        )
        for item in selected.artifact.method_summaries
    )
    return R4PromotionPortfolioRecordSeal.create(
        owner_record_key=owner_record.owner_record_key,
        record_id=selected.record_id,
        record_version=selected.record_version,
        record_hash=selected.record_hash,
        study_id=selected.study_id,
        study_version=selected.study_version,
        study_content_hash=selected.study_content_hash,
        artifact_hash=selected.artifact_hash,
        r3_attestation_hash=selected.r3_promotion_attestation_hash,
        split_contract_hash=selected.split_contract_hash,
        split_policy_version=selected.study.temporal_split.policy_version,
        record_subhashes=selected.subhashes,
        evaluated_at=selected.evaluated_at,
        recorded_at=selected.recorded_at,
        valid_until=selected.valid_until,
        producer_code_version=selected.producer_code_version,
        dependency_lock_hash=selected.dependency_lock_hash,
        cost_semantics_version=selected.study.rolling_policy.cost_semantics_version,
        windows=windows,
        window_metrics=window_metrics,
        method_summaries=method_summaries,
        exposure_point_hashes=tuple(
            sorted(item.content_hash for item in selected.artifact.exposure_points)
        ),
        regime_summary_hashes=tuple(
            sorted(item.content_hash for item in selected.artifact.regime_summaries)
        ),
        regime_covered_fold_ids=tuple(
            sorted({item.fold_id for item in selected.artifact.exposure_points})
        ),
        artifact_evidence_complete=selected.artifact.evidence_complete,
        artifact_eligible=selected.artifact.eligible_for_research_comparison,
        artifact_blockers=tuple(
            (item.code.value, item.detail, item.fold_id) for item in selected.artifact.blockers
        ),
        record_r3_attestation=r3_evidence(),
    )


def promotion_trial(
    *,
    policy: R4PromotionPolicy | None = None,
    record_seal: R4PromotionPortfolioRecordSeal | None = None,
    current_r3: R4PromotionR3AttestationEvidence | None = None,
) -> R4PromotionTrialSeal:
    """Return one exact ready-for-policy-evaluation trial seal."""

    return R4PromotionTrialSeal.create(
        trial_id="r4-promotion-trial-main",
        trial_version="trial.v1",
        policy=policy or promotion_policy(),
        portfolio_record=record_seal or portfolio_record_seal(),
        current_r3_attestation=current_r3 or r3_evidence(),
        evaluated_at=TRIAL_EVALUATED_AT + timedelta(minutes=2),
    )


def promotion_decision(
    *,
    decision_id: str = "r4-promotion-decision-main",
    decision_version: str = "decision.v1",
    policy: R4PromotionPolicy | None = None,
    trial: R4PromotionTrialSeal | None = None,
    decided_at: datetime = DECIDED_AT,
    recorded_at: datetime = DECISION_RECORDED_AT,
) -> R4PromotionDecision:
    """Return one automatically derived R4 promotion decision."""

    selected_policy = policy or promotion_policy()
    return create_r4_promotion_decision(
        decision_id=decision_id,
        decision_version=decision_version,
        policy=selected_policy,
        trial=trial or promotion_trial(policy=selected_policy),
        as_of=decided_at,
        recorded_at=recorded_at,
    )


__all__ = [
    "POLICY_ACTIVE_FROM",
    "POLICY_ACTIVE_UNTIL",
    "POLICY_RECORDED_AT",
    "RECORD_RECORDED_AT",
    "RECORD_VALID_UNTIL",
    "TRIAL_EVALUATED_AT",
    "DECIDED_AT",
    "DECISION_RECORDED_AT",
    "portfolio_record",
    "portfolio_record_seal",
    "promotion_decision",
    "promotion_trial",
    "promotion_policy",
    "promotion_scope",
    "r3_evidence",
    "study_registration",
]
