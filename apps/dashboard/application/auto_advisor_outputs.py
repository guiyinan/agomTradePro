"""Persistence and output helpers for auto-advisor weekly reports."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.audit.application.interface_services import log_operation_payload

from .repository_provider import get_auto_advisor_report_repository


def persist_auto_advisor_weekly_report_outputs(
    *,
    user: Any,
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist report, investment diary, dashboard notification, and audit trail."""

    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        raise ValueError("valid user is required")

    account = dict(report_payload.get("account") or {})
    week = dict(report_payload.get("week") or {})
    account_id = int(account.get("account_id") or account.get("id") or 0)
    if account_id <= 0:
        raise ValueError("valid account_id is required")

    report_date = date.fromisoformat(str(week["as_of"]))
    week_start = date.fromisoformat(str(week["start"]))
    week_end = date.fromisoformat(str(week["end"]))
    account_name = str(account.get("account_name") or account.get("name") or "")
    investment_diary = dict(report_payload.get("investment_diary") or {})
    repo = get_auto_advisor_report_repository()
    report = repo.upsert_weekly_report(
        user_id=user_id,
        account_id=account_id,
        account_name=account_name,
        report_date=report_date,
        week_start=week_start,
        week_end=week_end,
        payload=report_payload,
        investment_diary=investment_diary,
    )
    notification = repo.create_notification(
        user_id=user_id,
        account_id=account_id,
        report_id=int(report["id"]),
        title=f"自动投顾周报已生成: {account_name or account_id}",
        message=_weekly_report_notification_message(report_payload),
        payload={
            "report_id": report["id"],
            "report_date": report["report_date"],
            "today_conclusion": (report_payload.get("evidence") or {}).get("today_conclusion"),
            "investment_diary_status": investment_diary.get("status"),
        },
    )
    audit = _write_auto_advisor_report_audit_log(
        user=user,
        account_id=account_id,
        report_id=int(report["id"]),
        report_payload=report_payload,
    )
    if audit.get("success") and audit.get("log_id"):
        updated_report = repo.update_report_audit_log(
            report_id=int(report["id"]),
            audit_log_id=str(audit["log_id"]),
        )
        if updated_report is not None:
            report = updated_report

    return {
        "report": report,
        "notification": notification,
        "audit": audit,
    }


def _weekly_report_notification_message(report_payload: dict[str, Any]) -> str:
    portfolio_change = dict(report_payload.get("portfolio_change") or {})
    system_vs_actual = dict(report_payload.get("system_vs_actual") or {})
    return (
        f"组合变化 {portfolio_change.get('status') or '-'}，"
        f"系统建议 {system_vs_actual.get('decision_count', 0)} 条。"
    )


def _write_auto_advisor_report_audit_log(
    *,
    user: Any,
    account_id: int,
    report_id: int,
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    return log_operation_payload(
        request_id=f"auto-advisor-weekly-report-{report_id}",
        user_id=int(getattr(user, "id", 0) or 0),
        username=str(getattr(user, "username", "") or getattr(user, "email", "") or "system"),
        source="API",
        operation_type="DATA_MODIFY",
        module="dashboard",
        action="CREATE",
        mcp_tool_name="dashboard.generate_auto_advisor_weekly_reports",
        request_params={
            "account_id": account_id,
            "report_id": report_id,
        },
        response_payload={
            "week": report_payload.get("week"),
            "portfolio_change": report_payload.get("portfolio_change"),
            "investment_diary": report_payload.get("investment_diary"),
        },
        response_status=200,
        response_message="auto advisor weekly report persisted",
        resource_type="auto_advisor_weekly_report",
        resource_id=str(report_id),
        request_method="CELERY",
        request_path="dashboard.generate_auto_advisor_weekly_reports",
    )
