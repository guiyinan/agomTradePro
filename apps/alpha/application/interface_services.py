"""Application-facing helpers for alpha interface views."""

from __future__ import annotations

from typing import Any

from apps.account.application.interface_services import find_user_by_id
from apps.alpha.application.repository_provider import get_alpha_score_cache_repository


def resolve_requested_alpha_user(*, actor, requested_user_id: int | None):
    """Resolve the user whose alpha scores should be queried."""

    if requested_user_id is None:
        return actor
    return find_user_by_id(requested_user_id)


def upload_alpha_scores(
    *,
    write_user,
    universe_id: str,
    asof_date,
    intended_trade_date,
    model_id: str,
    model_artifact_hash: str,
    scores: list[dict[str, Any]],
) -> tuple[Any, bool]:
    """Upsert uploaded alpha scores into the cache store."""

    return get_alpha_score_cache_repository().upsert_qlib_cache(
        user=write_user,
        universe_id=universe_id,
        asof_date=asof_date,
        intended_trade_date=intended_trade_date,
        model_id=model_id,
        model_artifact_hash=model_artifact_hash,
        scores=scores,
    )
