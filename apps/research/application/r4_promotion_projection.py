"""Application projections from exact Portfolio/R3 owner records into Research."""

from __future__ import annotations

from apps.portfolio.application.r4_rolling_research_query import (
    R4RollingResearchOwnerRecord,
)
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionMethodSummaryEvidence,
    R4PromotionR3AttestationEvidence,
    R4PromotionWindowEvidence,
    R4PromotionWindowMetricEvidence,
)
from apps.research.domain.r4_promotion_record_seal import (
    R4PromotionPortfolioRecordSeal,
)


def project_r4_promotion_r3_attestation(
    attestation: ExactR3PromotionAttestation,
) -> R4PromotionR3AttestationEvidence:
    """Project one exact authoritative R3 attestation without weakening identity."""

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


def project_r4_portfolio_owner_record(
    owner_record: R4RollingResearchOwnerRecord,
) -> R4PromotionPortfolioRecordSeal:
    """Project every promotion-relevant field from a typed Portfolio owner row."""

    record = owner_record.record
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
        for item in record.study.windows
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
        for item in record.artifact.window_metrics
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
        for item in record.artifact.method_summaries
    )
    return R4PromotionPortfolioRecordSeal.create(
        owner_record_key=owner_record.owner_record_key,
        record_id=record.record_id,
        record_version=record.record_version,
        record_hash=record.record_hash,
        study_id=record.study_id,
        study_version=record.study_version,
        study_content_hash=record.study_content_hash,
        artifact_hash=record.artifact_hash,
        r3_attestation_hash=record.r3_promotion_attestation_hash,
        split_contract_hash=record.split_contract_hash,
        split_policy_version=record.study.temporal_split.policy_version,
        record_subhashes=record.subhashes,
        evaluated_at=record.evaluated_at,
        recorded_at=record.recorded_at,
        valid_until=record.valid_until,
        producer_code_version=record.producer_code_version,
        dependency_lock_hash=record.dependency_lock_hash,
        cost_semantics_version=record.study.rolling_policy.cost_semantics_version,
        windows=windows,
        window_metrics=window_metrics,
        method_summaries=method_summaries,
        exposure_point_hashes=tuple(
            sorted(item.content_hash for item in record.artifact.exposure_points)
        ),
        regime_summary_hashes=tuple(
            sorted(item.content_hash for item in record.artifact.regime_summaries)
        ),
        regime_covered_fold_ids=tuple(
            sorted({item.fold_id for item in record.artifact.exposure_points})
        ),
        artifact_evidence_complete=record.artifact.evidence_complete,
        artifact_eligible=record.artifact.eligible_for_research_comparison,
        artifact_blockers=tuple(
            (item.code.value, item.detail, item.fold_id) for item in record.artifact.blockers
        ),
        record_r3_attestation=project_r4_promotion_r3_attestation(record.promotion_attestation),
    )


__all__ = [
    "project_r4_portfolio_owner_record",
    "project_r4_promotion_r3_attestation",
]
