"""Focused Decision Rhythm queries consumed by Share snapshots."""

from __future__ import annotations

from django.db.models import Q

from apps.decision_rhythm.infrastructure.models import DecisionRequestModel


def list_share_decisions_for_account_assets(
    *, account_id: int, asset_codes: set[str], limit: int = 12
) -> list[DecisionRequestModel]:
    """Return decision request models relevant to an account and asset set."""

    if not asset_codes:
        return []
    return list(
        DecisionRequestModel._default_manager.filter(asset_code__in=asset_codes)
        .filter(
            Q(unified_recommendation__account_id=str(account_id))
            | Q(unified_recommendation__account_id=account_id)
            | Q(execution_ref__account_id=account_id)
            | Q(execution_ref__account_id=str(account_id))
        )
        .select_related(
            "response",
            "feature_snapshot",
            "unified_recommendation",
            "unified_recommendation__feature_snapshot",
        )
        .order_by("-requested_at")[:limit]
    )


__all__ = ["list_share_decisions_for_account_assets"]
