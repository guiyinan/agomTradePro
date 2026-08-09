"""Content hashing for the R4 rolling macro-risk artifact."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4MethodBacktestSummary,
    R4MethodWindowMetrics,
    R4RegimeExposureSummary,
    R4RollingBlocker,
    R4RollingExposurePoint,
    _hash_parts,
    _utc_text,
)


def build_r4_rolling_artifact_hash(
    *,
    study_id: str,
    study_version: str,
    input_hash: str,
    r3_promotion_attestation_hash: str,
    expected_window_count: int,
    expected_fold_ids: tuple[str, ...],
    evidence_complete: bool,
    eligible_for_research_comparison: bool,
    window_metrics: tuple[R4MethodWindowMetrics, ...],
    exposure_points: tuple[R4RollingExposurePoint, ...],
    regime_summaries: tuple[R4RegimeExposureSummary, ...],
    method_summaries: tuple[R4MethodBacktestSummary, ...],
    blockers: tuple[R4RollingBlocker, ...],
    evaluated_at: datetime,
    policy_version: str,
) -> str:
    """Seal every rolling R4 output and its authoritative R3 attestation."""

    return _hash_parts(
        "r4-rolling-artifact.v2",
        study_id,
        study_version,
        input_hash.lower(),
        r3_promotion_attestation_hash.lower(),
        str(expected_window_count),
        *expected_fold_ids,
        str(evidence_complete),
        str(eligible_for_research_comparison),
        _utc_text(evaluated_at),
        policy_version,
        *(
            item.content_hash.lower()
            for item in sorted(window_metrics, key=lambda x: (x.fold_id, x.kind.value))
        ),
        *(
            item.content_hash.lower()
            for item in sorted(
                exposure_points, key=lambda x: (x.fold_id, x.asset_code, x.factor_code)
            )
        ),
        *(
            item.content_hash.lower()
            for item in sorted(
                regime_summaries, key=lambda x: (x.regime_code, x.asset_code, x.factor_code)
            )
        ),
        *(
            item.content_hash.lower()
            for item in sorted(method_summaries, key=lambda x: x.kind.value)
        ),
        *(
            f"{item.code.value}|{item.fold_id or ''}|{item.detail}"
            for item in sorted(
                blockers,
                key=lambda x: (x.code.value, x.fold_id or "", x.detail),
            )
        ),
        "research_only",
        "True",
        "True",
    )


__all__ = ["build_r4_rolling_artifact_hash"]
