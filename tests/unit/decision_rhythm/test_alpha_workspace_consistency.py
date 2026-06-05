"""Tests for Alpha/workspace recommendation consistency rules."""

from datetime import UTC, date, datetime

from apps.decision_rhythm.application.consistency_checks import (
    AlphaRankingSnapshot,
    AlphaWorkspaceConsistencyChecker,
    WorkspaceRecommendationSnapshot,
)


def test_consistency_checker_flags_stale_workspace_recommendations() -> None:
    """Workspace recommendations must not lag far behind Alpha rankings."""

    result = AlphaWorkspaceConsistencyChecker(allowed_lag_days=1).evaluate(
        alpha=AlphaRankingSnapshot(
            latest_trade_date=date(2026, 6, 4),
            latest_updated_at=datetime(2026, 6, 4, 8, tzinfo=UTC),
            top_codes=("002709.SZ", "300274.SZ"),
            provider_source="qlib",
            status="available",
        ),
        workspace=WorkspaceRecommendationSnapshot(
            account_id="510",
            latest_updated_at=datetime(2026, 5, 20, 1, tzinfo=UTC),
            recommendation_codes=("601169.SH",),
            source_candidate_ids=(),
            total_count=1,
        ),
    )

    issue_codes = {issue.code for issue in result.issues}
    assert result.status == "warning"
    assert "workspace_recommendations_stale" in issue_codes
    assert "workspace_alpha_overlap_low" in issue_codes
    assert "workspace_missing_alpha_rank_origin" in issue_codes


def test_consistency_checker_accepts_fresh_alpha_rank_origin() -> None:
    """Fresh workspace recommendations with Alpha rank origin pass."""

    result = AlphaWorkspaceConsistencyChecker(allowed_lag_days=1).evaluate(
        alpha=AlphaRankingSnapshot(
            latest_trade_date=date(2026, 6, 4),
            latest_updated_at=datetime(2026, 6, 4, 8, tzinfo=UTC),
            top_codes=("002709.SZ", "300274.SZ"),
            provider_source="qlib",
            status="available",
        ),
        workspace=WorkspaceRecommendationSnapshot(
            account_id="510",
            latest_updated_at=datetime(2026, 6, 5, 6, tzinfo=UTC),
            recommendation_codes=("002709.SZ", "300274.SZ"),
            source_candidate_ids=("alpha_rank:002709.SZ:2026-06-04",),
            total_count=2,
        ),
    )

    assert result.status == "ok"
    assert result.issues == ()


def test_consistency_checker_flags_qlib_provider_degraded() -> None:
    """Qlib runtime degradation must be visible in consistency output."""

    result = AlphaWorkspaceConsistencyChecker(allowed_lag_days=1).evaluate(
        alpha=AlphaRankingSnapshot(
            latest_trade_date=date(2026, 6, 4),
            latest_updated_at=datetime(2026, 6, 4, 8, tzinfo=UTC),
            top_codes=("002709.SZ",),
            provider_source="qlib",
            status="available",
            runtime_provider_status={
                "qlib": {
                    "priority": 1,
                    "status": "degraded",
                    "message": "模型文件不存在",
                }
            },
        ),
        workspace=WorkspaceRecommendationSnapshot(
            account_id="510",
            latest_updated_at=datetime(2026, 6, 5, 6, tzinfo=UTC),
            recommendation_codes=("002709.SZ",),
            source_candidate_ids=("alpha_rank:002709.SZ:2026-06-04",),
            total_count=1,
        ),
    )

    assert "alpha_qlib_provider_degraded" in {issue.code for issue in result.issues}


def test_consistency_checker_flags_empty_inputs() -> None:
    """Missing rankings or recommendations are warning conditions."""

    result = AlphaWorkspaceConsistencyChecker().evaluate(
        alpha=AlphaRankingSnapshot(
            latest_trade_date=None,
            latest_updated_at=None,
            top_codes=(),
        ),
        workspace=WorkspaceRecommendationSnapshot(
            account_id="default",
            latest_updated_at=None,
            recommendation_codes=(),
            total_count=0,
        ),
    )

    issue_codes = {issue.code for issue in result.issues}
    assert result.status == "warning"
    assert issue_codes == {
        "alpha_ranking_empty",
        "workspace_recommendations_empty",
    }
