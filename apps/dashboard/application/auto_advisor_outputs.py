"""Persistence and output helpers for auto-advisor weekly reports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol

from apps.audit.application.interface_services import (
    log_operation_payload as _log_operation_payload,
)

from .repository_provider import get_auto_advisor_report_repository


class ReportUserProtocol(Protocol):
    """User identity fields required for report persistence and audit."""

    @property
    def id(self) -> int | None: ...

    @property
    def username(self) -> str: ...

    @property
    def email(self) -> str: ...


def log_operation_payload(**kwargs: Any) -> dict[str, Any]:
    """Write one audit row through the owning application boundary."""

    result = _log_operation_payload(**kwargs)
    return {str(key): value for key, value in result.items()}


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    """Detach one string-key mapping from a generated report payload."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _bounded_text(value: object, *, field_name: str, maximum: int) -> str:
    """Return bounded single-line report metadata."""

    normalized = str(value or "").strip()
    if len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def persist_auto_advisor_weekly_report_outputs(
    *,
    user: ReportUserProtocol,
    report_payload: dict[str, Any],
    audit_source: str = "API",
    audit_tool_name: str = "dashboard.generate_auto_advisor_weekly_reports",
    audit_request_method: str = "CELERY",
    audit_request_path: str = "dashboard.generate_auto_advisor_weekly_reports",
) -> dict[str, Any]:
    """Persist report, investment diary, dashboard notification, and audit trail."""

    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        raise ValueError("valid user is required")

    account = _mapping(report_payload.get("account"), "account")
    week = _mapping(report_payload.get("week"), "week")
    account_id = int(account.get("account_id") or account.get("id") or 0)
    if account_id <= 0:
        raise ValueError("valid account_id is required")

    report_date = date.fromisoformat(str(week["as_of"]))
    week_start = date.fromisoformat(str(week["start"]))
    week_end = date.fromisoformat(str(week["end"]))
    if not week_start <= report_date <= week_end:
        raise ValueError("weekly report dates are inconsistent")
    account_name = _bounded_text(
        account.get("account_name") or account.get("name") or "",
        field_name="account_name",
        maximum=200,
    )
    investment_diary = _mapping(
        report_payload.get("investment_diary") or {},
        "investment_diary",
    )
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
            "today_conclusion": _mapping(
                report_payload.get("evidence") or {},
                "evidence",
            ).get("today_conclusion"),
            "investment_diary_status": investment_diary.get("status"),
        },
    )
    audit = _write_auto_advisor_report_audit_log(
        user=user,
        account_id=account_id,
        report_id=int(report["id"]),
        report_payload=report_payload,
        audit_source=audit_source,
        audit_tool_name=audit_tool_name,
        audit_request_method=audit_request_method,
        audit_request_path=audit_request_path,
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
    portfolio_change = _mapping(
        report_payload.get("portfolio_change") or {},
        "portfolio_change",
    )
    system_vs_actual = _mapping(
        report_payload.get("system_vs_actual") or {},
        "system_vs_actual",
    )
    status = _bounded_text(
        portfolio_change.get("status") or "-",
        field_name="portfolio_change.status",
        maximum=64,
    )
    decision_count = system_vs_actual.get("decision_count", 0)
    if isinstance(decision_count, bool) or not isinstance(decision_count, int):
        decision_count = 0
    return f"组合变化 {status}，" f"系统建议 {decision_count} 条。"


def _write_auto_advisor_report_audit_log(
    *,
    user: ReportUserProtocol,
    account_id: int,
    report_id: int,
    report_payload: dict[str, Any],
    audit_source: str,
    audit_tool_name: str,
    audit_request_method: str,
    audit_request_path: str,
) -> dict[str, Any]:
    audit_source = _bounded_text(audit_source, field_name="audit_source", maximum=32)
    audit_tool_name = _bounded_text(audit_tool_name, field_name="audit_tool_name", maximum=128)
    audit_request_method = _bounded_text(
        audit_request_method,
        field_name="audit_request_method",
        maximum=16,
    )
    audit_request_path = _bounded_text(
        audit_request_path,
        field_name="audit_request_path",
        maximum=256,
    )
    return log_operation_payload(
        request_id=f"auto-advisor-weekly-report-{report_id}",
        user_id=int(getattr(user, "id", 0) or 0),
        username=str(getattr(user, "username", "") or getattr(user, "email", "") or "system"),
        source=audit_source,
        operation_type="DATA_MODIFY",
        module="dashboard",
        action="CREATE",
        mcp_tool_name=audit_tool_name,
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
        request_method=audit_request_method,
        request_path=audit_request_path,
    )
