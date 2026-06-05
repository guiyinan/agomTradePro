"""ORM-backed snapshots for Alpha/workspace consistency checks."""

from __future__ import annotations

import logging
from typing import Any

from apps.decision_rhythm.application.consistency_checks import (
    AlphaRankingSnapshot,
    AlphaWorkspaceConsistencyChecker,
    AlphaWorkspaceConsistencyResult,
    WorkspaceRecommendationSnapshot,
)

logger = logging.getLogger(__name__)


def _extract_score_code(score: Any) -> str:
    """Extract a stock code from a cache score row."""

    if isinstance(score, dict):
        return str(score.get("code") or score.get("security_code") or "").strip()
    return str(getattr(score, "code", "") or "").strip()


def get_latest_alpha_ranking_snapshot(*, top_n: int = 30) -> AlphaRankingSnapshot:
    """Return the latest persisted Alpha ranking snapshot."""

    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    runtime_provider_status = get_alpha_runtime_provider_status()
    cache = (
        AlphaScoreCacheModel._default_manager.exclude(scores=[])
        .order_by("-intended_trade_date", "-created_at")
        .first()
    )
    if cache is None:
        return AlphaRankingSnapshot(
            latest_trade_date=None,
            latest_updated_at=None,
            top_codes=(),
            runtime_provider_status=runtime_provider_status,
        )

    top_codes = tuple(
        code
        for code in (_extract_score_code(score) for score in (cache.scores or [])[:top_n])
        if code
    )
    return AlphaRankingSnapshot(
        latest_trade_date=cache.intended_trade_date,
        latest_updated_at=getattr(cache, "updated_at", None) or getattr(cache, "created_at", None),
        top_codes=top_codes,
        provider_source=str(cache.provider_source or ""),
        status=str(cache.status or ""),
        runtime_provider_status=runtime_provider_status,
    )


def get_alpha_runtime_provider_status() -> dict[str, Any]:
    """Return AlphaService provider health without failing the consistency check."""

    try:
        from apps.alpha.application.services import AlphaService

        return AlphaService().get_provider_status()
    except Exception as exc:
        logger.warning("Failed to get Alpha runtime provider status: %s", exc)
        return {"__error__": {"status": "error", "error": str(exc)}}


def resolve_workspace_consistency_account_id(account_id: str | None = None) -> str:
    """Resolve the account id to inspect for workspace consistency."""

    if account_id:
        return account_id

    from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel

    latest_account = (
        UnifiedRecommendationModel.objects.order_by("-updated_at", "-created_at")
        .values_list("account_id", flat=True)
        .first()
    )
    return str(latest_account or "default")


def get_workspace_recommendation_snapshot(
    *,
    account_id: str | None = None,
    limit: int = 30,
) -> WorkspaceRecommendationSnapshot:
    """Return latest workspace recommendation state for one account."""

    from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel

    resolved_account_id = resolve_workspace_consistency_account_id(account_id)
    queryset = UnifiedRecommendationModel.objects.filter(account_id=resolved_account_id).order_by(
        "-updated_at", "-created_at"
    )
    rows = list(
        queryset.values(
            "security_code",
            "source_candidate_ids",
            "updated_at",
            "created_at",
        )[:limit]
    )
    latest_row = rows[0] if rows else None
    source_candidate_ids: list[str] = []
    for row in rows:
        for source_id in row.get("source_candidate_ids") or []:
            source_text = str(source_id or "").strip()
            if source_text:
                source_candidate_ids.append(source_text)

    return WorkspaceRecommendationSnapshot(
        account_id=resolved_account_id,
        latest_updated_at=(
            (latest_row.get("updated_at") or latest_row.get("created_at"))
            if latest_row
            else None
        ),
        recommendation_codes=tuple(
            str(row.get("security_code") or "").strip()
            for row in rows
            if str(row.get("security_code") or "").strip()
        ),
        source_candidate_ids=tuple(dict.fromkeys(source_candidate_ids)),
        total_count=queryset.count(),
    )


def run_alpha_workspace_consistency_check(
    *,
    account_id: str | None = None,
    top_n: int = 30,
    allowed_lag_days: int = 1,
) -> AlphaWorkspaceConsistencyResult:
    """Run the persisted Alpha/workspace consistency check."""

    alpha = get_latest_alpha_ranking_snapshot(top_n=top_n)
    workspace = get_workspace_recommendation_snapshot(account_id=account_id, limit=top_n)
    return AlphaWorkspaceConsistencyChecker(
        allowed_lag_days=allowed_lag_days,
        min_top_overlap=1,
        require_alpha_rank_origin=True,
    ).evaluate(alpha=alpha, workspace=workspace)


def check_alpha_workspace_consistency_health() -> dict[str, Any]:
    """Return readiness-compatible Alpha/workspace consistency health payload."""

    try:
        result = run_alpha_workspace_consistency_check()
        payload = result.to_dict()
        payload["status"] = result.status
        return payload
    except Exception as exc:
        logger.warning("Alpha/workspace consistency check failed: %s", exc)
        return {"status": "error", "error": str(exc)}
