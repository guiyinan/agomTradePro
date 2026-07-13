"""audit runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_audit_summary(
    backtest_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date, timedelta

    from agomtradepro import AgomTradeProClient

    if backtest_id is not None and (start_date is not None or end_date is not None):
        return {
            "success": False,
            "reports": [],
            "total_count": 0,
            "query": {},
            "error": "backtest_id cannot be combined with start_date or end_date",
        }
    if (start_date is None) != (end_date is None):
        return {
            "success": False,
            "reports": [],
            "total_count": 0,
            "query": {},
            "error": "start_date and end_date must be provided together",
        }

    client = AgomTradeProClient()
    if backtest_id is not None:
        reports = client.audit.get_summary(backtest_id=backtest_id)
        query = {"mode": "backtest", "backtest_id": backtest_id}
    else:
        if start_date is None or end_date is None:
            resolved_end = date.today()
            resolved_start = resolved_end - timedelta(days=30)
            start_date = resolved_start.isoformat()
            end_date = resolved_end.isoformat()
            mode = "rolling_30_days"
        else:
            mode = "date_range"
        reports = client.audit.get_summary(
            start_date=start_date,
            end_date=end_date,
        )
        query = {
            "mode": mode,
            "start_date": start_date,
            "end_date": end_date,
        }

    return {
        "success": True,
        "reports": reports,
        "total_count": len(reports),
        "query": query,
        "error": None,
    }


def _fallback_list_audit_execution_links(
    account_id: str | int | None = None,
    recommendation_id: str | None = None,
    transaction_source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.audit.list_execution_links(
        account_id=account_id,
        recommendation_id=recommendation_id,
        transaction_source=transaction_source,
        limit=limit,
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_audit_summary": _fallback_get_audit_summary,
    "list_audit_execution_links": _fallback_list_audit_execution_links,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
