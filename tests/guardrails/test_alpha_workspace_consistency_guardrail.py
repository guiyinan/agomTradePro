"""Guardrails for Alpha ranking and decision workspace consistency."""

from datetime import UTC, date, datetime

from apps.decision_rhythm.application.consistency_checks import (
    AlphaRankingSnapshot,
    AlphaWorkspaceConsistencyChecker,
    WorkspaceRecommendationSnapshot,
)
from core.health_checks import run_readiness_checks


def test_alpha_workspace_consistency_guardrail_detects_stale_workspace() -> None:
    """A stale workspace must be reported before users see unchanged tickets."""

    result = AlphaWorkspaceConsistencyChecker(allowed_lag_days=1).evaluate(
        alpha=AlphaRankingSnapshot(
            latest_trade_date=date(2026, 6, 4),
            latest_updated_at=datetime(2026, 6, 4, 8, tzinfo=UTC),
            top_codes=("002709.SZ",),
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

    assert "workspace_recommendations_stale" in {
        issue.code for issue in result.issues
    }
    assert "workspace_missing_alpha_rank_origin" in {
        issue.code for issue in result.issues
    }


def test_readiness_includes_alpha_workspace_consistency(monkeypatch) -> None:
    """Readiness must expose the consistency signal for operational monitoring."""

    monkeypatch.setattr("core.health_checks.check_database", lambda: {"status": "ok"})
    monkeypatch.setattr("core.health_checks.check_redis", lambda: {"status": "skipped"})
    monkeypatch.setattr("core.health_checks.check_celery", lambda: {"status": "skipped"})
    monkeypatch.setattr("core.health_checks.check_critical_data", lambda: {"status": "ok"})
    monkeypatch.setattr(
        "core.health_checks.check_alpha_workspace_consistency",
        lambda: {"status": "warning", "issues": [{"code": "workspace_recommendations_stale"}]},
    )

    checks = run_readiness_checks()

    assert checks["alpha_workspace_consistency"]["status"] == "warning"
    assert checks["alpha_workspace_consistency"]["issues"][0]["code"] == (
        "workspace_recommendations_stale"
    )
