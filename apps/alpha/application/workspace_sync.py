"""Decision workspace synchronization hooks for Alpha outputs."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from apps.alpha.application.trade_dates import resolve_recent_closed_trade_date

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_ALPHA_UNIVERSE_ID = "csi300"
_resolve_recent_closed_trade_date = resolve_recent_closed_trade_date


def sync_default_workspace_after_alpha_update(
    universe_id: str,
    trade_date: date,
    pool_scope: Any | None,
) -> dict[str, Any]:
    """Refresh default workspace recommendations after the current Alpha cache updates."""
    if pool_scope is not None:
        return {
            "workspace_recommendations_status": "skipped",
            "workspace_recommendations_reason": "scoped_alpha_pool",
        }

    if universe_id != DEFAULT_WORKSPACE_ALPHA_UNIVERSE_ID:
        return {
            "workspace_recommendations_status": "skipped",
            "workspace_recommendations_reason": "non_default_alpha_universe",
        }

    current_trade_date = _resolve_recent_closed_trade_date()
    if trade_date != current_trade_date:
        return {
            "workspace_recommendations_status": "skipped",
            "workspace_recommendations_reason": "not_current_trade_date",
            "workspace_recommendations_current_trade_date": current_trade_date.isoformat(),
        }

    try:
        from apps.decision_rhythm.application.dtos import RefreshRecommendationsRequestDTO
        from apps.decision_rhythm.application.workspace_services import (
            refresh_workspace_recommendations,
        )

        response = refresh_workspace_recommendations(
            RefreshRecommendationsRequestDTO(
                account_id="default",
                security_codes=None,
                force=True,
                async_mode=False,
            )
        )
    except Exception as exc:
        logger.warning(
            "Failed to refresh default workspace recommendations after Alpha cache update: %s",
            exc,
            exc_info=True,
        )
        return {
            "workspace_recommendations_status": "failed",
            "workspace_recommendations_error": str(exc),
        }

    return {
        "workspace_recommendations_status": "refreshed"
        if response.status == "COMPLETED"
        else "failed",
        "workspace_recommendations_task_id": response.task_id,
        "workspace_recommendations_count": response.recommendations_count,
        "workspace_recommendations_conflicts_count": response.conflicts_count,
        "workspace_recommendations_message": response.message,
    }
