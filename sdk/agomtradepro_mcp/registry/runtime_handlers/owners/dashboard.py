"""dashboard runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _unwrap_canonical_success_data


def _fallback_dashboard_read_auto_advisor_console(
    account_id: int | str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.dashboard.auto_advisor_console(account_id=account_id)
    return _unwrap_canonical_success_data(
        response,
        operation="dashboard.read.auto_advisor_console",
    )


def _fallback_dashboard_query_auto_advisor(
    account_id: int | str,
    question: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.dashboard.auto_advisor_query(
        account_id=account_id,
        question=question,
    )
    return _unwrap_canonical_success_data(
        response,
        operation="dashboard.query.auto_advisor",
    )


def _fallback_dashboard_read_auto_advisor_weekly_report(
    account_id: int | str,
    as_of: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.dashboard.auto_advisor_weekly_report(
        account_id=account_id,
        as_of=as_of,
    )
    return _unwrap_canonical_success_data(
        response,
        operation="dashboard.read.auto_advisor_weekly_report",
    )


def _fallback_dashboard_read_auto_advisor_weekly_report_history(
    account_id: int | str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.dashboard.auto_advisor_weekly_report_history(
        account_id=account_id,
        limit=limit,
    )
    data = _unwrap_canonical_success_data(
        result,
        operation="dashboard.read.auto_advisor_weekly_report_history",
    )
    reports = data.get("reports", [])
    return {
        "status": data.get("status", "ok"),
        "reports": reports,
        "total_count": int(data.get("count", len(reports))),
        "query": {
            "account_id": str(account_id) if account_id is not None else None,
            "limit": limit,
        },
    }


def _fallback_dashboard_read_auto_advisor_notifications(
    account_id: int | str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.dashboard.auto_advisor_notifications(
        account_id=account_id,
        limit=limit,
    )
    data = _unwrap_canonical_success_data(
        result,
        operation="dashboard.read.auto_advisor_notifications",
    )
    notifications = data.get("notifications", [])
    return {
        "status": data.get("status", "ok"),
        "notifications": notifications,
        "total_count": int(data.get("count", len(notifications))),
        "query": {
            "account_id": str(account_id) if account_id is not None else None,
            "limit": limit,
        },
    }


def _fallback_dashboard_read_alpha_history(
    portfolio_id: int | None = None,
    trade_date: str | None = None,
    stock_code: str | None = None,
    stage: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.dashboard.alpha_history_payload(
        portfolio_id=portfolio_id,
        trade_date=trade_date,
        stock_code=stock_code,
        stage=stage,
        source=source,
    )


def _fallback_dashboard_read_alpha_history_detail(
    run_id: int,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.dashboard.alpha_history_detail_payload(run_id)


def _fallback_dashboard_read_equity_curve() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.dashboard.equity_curve_v1()
    if not isinstance(result, dict):
        raise ValueError("dashboard.read.equity_curve returned an invalid payload")
    series = result.get("series")
    if not isinstance(series, list):
        raise ValueError("dashboard.read.equity_curve must contain a series array")
    return {
        "range": str(result.get("range") or "ALL"),
        "has_history": bool(result.get("has_history", False)),
        "series": [dict(item) for item in series if isinstance(item, dict)],
    }


def _fallback_dashboard_read_asset_allocation() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.dashboard.allocation()
    data = _unwrap_canonical_success_data(
        response,
        operation="dashboard.read.asset_allocation",
    )
    allocation = {
        str(asset_class): float(value)
        for asset_class, value in data.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "allocation": allocation,
        "total_market_value": sum(allocation.values()),
    }


def _fallback_dashboard_read_position_catalog() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    response = client.dashboard.positions()
    data = _unwrap_canonical_success_data(
        response,
        operation="dashboard.read.position_catalog",
    )
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise ValueError("dashboard.read.position_catalog must contain a positions array")
    normalized = [dict(position) for position in positions if isinstance(position, dict)]
    return {
        "positions": normalized,
        "total_count": len(normalized),
    }


def _internal_handler_dashboard_create_auto_advisor_weekly_report(
    account_id: int | str,
    as_of: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    if isinstance(account_id, bool):
        raise ValueError("account_id must be a positive integer or non-empty string")
    normalized_account_id = str(account_id).strip()
    if not normalized_account_id:
        raise ValueError("account_id must be a positive integer or non-empty string")
    if isinstance(account_id, int) and account_id <= 0:
        raise ValueError("account_id must be a positive integer or non-empty string")
    if not isinstance(as_of, str) or not as_of.strip():
        raise ValueError("as_of must be an ISO 8601 date")
    try:
        canonical_as_of = date.fromisoformat(as_of.strip()).isoformat()
    except ValueError as exc:
        raise ValueError("as_of must be an ISO 8601 date") from exc

    client = AgomTradeProClient()
    if preview_only:
        report_response = client.dashboard.auto_advisor_weekly_report(
            account_id=normalized_account_id,
            as_of=canonical_as_of,
        )
        report = _unwrap_canonical_success_data(
            report_response,
            operation="dashboard.create.auto_advisor_weekly_report.preview",
        )
        history_response = client.dashboard.auto_advisor_weekly_report_history(
            account_id=normalized_account_id,
            limit=20,
        )
        history = _unwrap_canonical_success_data(
            history_response,
            operation="dashboard.create.auto_advisor_weekly_report.history",
        )
        reports = history.get("reports", [])
        if not isinstance(reports, list):
            raise ValueError("auto advisor weekly report history must contain a reports array")
        existing = next(
            (
                item
                for item in reports
                if isinstance(item, dict) and str(item.get("report_date")) == canonical_as_of
            ),
            None,
        )
        week = report.get("week") if isinstance(report.get("week"), dict) else {}
        account = report.get("account") if isinstance(report.get("account"), dict) else {}
        operation = "create" if existing is None else "overwrite"
        return {
            "success": True,
            "preview_only": True,
            "operation": operation,
            "account_id": normalized_account_id,
            "as_of": canonical_as_of,
            "report_preview": report,
            "existing_report": existing,
            "summary": {
                "account_id": normalized_account_id,
                "account_name": account.get("account_name") or account.get("name"),
                "as_of": canonical_as_of,
                "week_start": week.get("start"),
                "week_end": week.get("end"),
                "operation": operation,
                "existing_report_id": existing.get("id") if existing else None,
                "will_upsert_report_snapshot": True,
                "will_create_notification": True,
                "will_write_audit_log": True,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to persist the weekly report snapshot, investment "
                "diary snapshot, dashboard notification and audit log."
            ),
        }

    response = client.dashboard.create_auto_advisor_weekly_report(
        account_id=normalized_account_id,
        as_of=canonical_as_of,
    )
    return _unwrap_canonical_success_data(
        response,
        operation="dashboard.create.auto_advisor_weekly_report",
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "dashboard_read_auto_advisor_console": _fallback_dashboard_read_auto_advisor_console,
    "dashboard_query_auto_advisor": _fallback_dashboard_query_auto_advisor,
    "dashboard_read_auto_advisor_weekly_report": _fallback_dashboard_read_auto_advisor_weekly_report,
    "dashboard_read_auto_advisor_weekly_report_history": _fallback_dashboard_read_auto_advisor_weekly_report_history,
    "dashboard_read_auto_advisor_notifications": _fallback_dashboard_read_auto_advisor_notifications,
    "dashboard_read_alpha_history": _fallback_dashboard_read_alpha_history,
    "dashboard_read_alpha_history_detail": _fallback_dashboard_read_alpha_history_detail,
    "dashboard_read_equity_curve": _fallback_dashboard_read_equity_curve,
    "dashboard_read_asset_allocation": _fallback_dashboard_read_asset_allocation,
    "dashboard_read_position_catalog": _fallback_dashboard_read_position_catalog,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "dashboard_create_auto_advisor_weekly_report": _internal_handler_dashboard_create_auto_advisor_weekly_report,
}
