"""Bridge helpers for manual trade sync reads."""

from __future__ import annotations

from typing import Any


def get_manual_trade_sync_repository():
    """Return the account manual-trade repository through the integration layer."""

    from apps.account.application.repository_provider import (
        get_manual_trade_sync_repository as _get_manual_trade_sync_repository,
    )

    return _get_manual_trade_sync_repository()


def build_manual_trade_review_context(user_id: int) -> dict[str, Any]:
    """Build manual trade review context without coupling audit to account."""

    from apps.account.application.manual_trade_sync import ManualTradeReviewSummaryUseCase

    return ManualTradeReviewSummaryUseCase().execute(user_id=user_id)
