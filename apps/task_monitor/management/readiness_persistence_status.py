"""Current DB persistence proof for personal readiness evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.dashboard.application.repository_provider import get_auto_advisor_report_repository
from apps.risk_center.application.repository_provider import get_risk_daily_report_repository
from apps.task_monitor.management.auto_advisor_weekly_scheduler_status import (
    build_auto_advisor_weekly_due_status,
)


def collect_post_evidence_persistence(*, output_dir: Path) -> dict[str, Any]:
    """Read current DB persistence proof for the latest formal evidence targets."""

    latest_formal_payload = _load_latest_evidence_payload(
        output_dir=output_dir,
        formal_candidate_only=True,
    )
    if latest_formal_payload is None:
        return {
            "status": "not_applicable",
            "reason": "latest_formal_evidence_missing",
            "acceptance_gate_impact": "none",
        }

    try:
        target_date = date.fromisoformat(str(latest_formal_payload["target_date"]))
    except (KeyError, TypeError, ValueError):
        return {
            "status": "warning",
            "reason": "latest_formal_evidence_target_date_invalid",
            "acceptance_gate_impact": "none",
        }

    accounts = _extract_evidence_accounts(latest_formal_payload=latest_formal_payload)
    if not accounts:
        return {
            "status": "not_applicable",
            "reason": "latest_formal_evidence_has_no_accounts",
            "target_date": target_date.isoformat(),
            "acceptance_gate_impact": "none",
        }

    risk_requested = any(bool(account.get("risk_requested")) for account in accounts)
    weekly_requested = any(bool(account.get("weekly_requested")) for account in accounts)
    risk = (
        _collect_current_risk_report_persistence(target_date=target_date, accounts=accounts)
        if risk_requested
        else {
            "status": "not_applicable",
            "reason": "risk_center_daily_report_not_present_in_latest_formal_evidence",
        }
    )
    weekly = (
        _collect_current_weekly_report_persistence(target_date=target_date, accounts=accounts)
        if weekly_requested
        else {
            "status": "not_applicable",
            "reason": "weekly_report_not_present_in_latest_formal_evidence",
        }
    )
    statuses = [str(risk.get("status") or ""), str(weekly.get("status") or "")]
    if any(status == "error" for status in statuses):
        status = "error"
    elif any(status == "warning" for status in statuses):
        status = "warning"
    elif any(status == "ok" for status in statuses):
        status = "ok"
    else:
        status = "not_applicable"
    return {
        "status": status,
        "target_date": target_date.isoformat(),
        "account_count": len(accounts),
        "risk_center_daily_report": risk,
        "auto_advisor_weekly_report": weekly,
        "acceptance_gate_impact": "none",
    }


def apply_risk_advisory_persistence_status(
    *,
    action: dict[str, Any],
    post_evidence_persistence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Clarify pending risk persistence advice with current DB proof when available."""

    post_evidence = dict(post_evidence_persistence or {})
    risk = dict(post_evidence.get("risk_center_daily_report") or {})
    if risk.get("status") != "ok":
        return action
    records = [
        {
            "account_id": record.get("account_id"),
            "report_id": record.get("report_id"),
            "report_date": record.get("report_date"),
        }
        for record in risk.get("records") or []
        if isinstance(record, dict)
    ]
    clarified = dict(action)
    clarified.update(
        {
            "action": "wait_for_scheduled_risk_report_evidence",
            "reason": "post_evidence_risk_reports_persisted_waiting_for_scheduler_evidence",
            "current_database_status": "ok",
            "current_database_ok_account_count": risk.get("ok_account_count"),
            "current_database_report_count": len(records),
            "current_database_reports": records,
            "acceptance_gate_impact": post_evidence.get("acceptance_gate_impact") or "none",
        }
    )
    return clarified


def build_post_evidence_monitor_gate(
    post_evidence_persistence: dict[str, Any] | None,
    due_status: str | None,
    strict_monitor_command: str,
) -> dict[str, Any] | None:
    """Return a strict-monitor gate for pending or degraded post-evidence proof."""

    post_evidence = dict(post_evidence_persistence or {})
    post_evidence_status = str(post_evidence.get("status") or "")
    risk = dict(post_evidence.get("risk_center_daily_report") or {})
    weekly = dict(post_evidence.get("auto_advisor_weekly_report") or {})
    if (
        post_evidence_status == "ok"
        and weekly.get("status") == "not_due"
        and weekly.get("reason") == "weekly_report_schedule_not_due_yet"
        and weekly.get("scheduled_for")
    ):
        return {
            "ok": True,
            "state": "wait_for_post_evidence_persistence",
            "reason": "weekly_report_schedule_not_due_yet",
            "next_action": "wait_for_post_evidence_persistence",
            "target_date": post_evidence.get("target_date"),
            "next_check_after": weekly.get("scheduled_for"),
            "risk_status": risk.get("status"),
            "weekly_status": weekly.get("status"),
            "due_status": due_status or None,
        }
    if post_evidence_status not in {"warning", "error"}:
        return None
    return {
        "ok": False,
        "state": "post_evidence_persistence_not_ok",
        "reason": post_evidence.get("reason") or f"post_evidence_{post_evidence_status}",
        "next_action": "inspect_post_evidence_persistence",
        "target_date": post_evidence.get("target_date"),
        "risk_status": risk.get("status"),
        "weekly_status": weekly.get("status"),
        "command": strict_monitor_command,
        "due_status": due_status or None,
    }


def _load_latest_evidence_payload(
    *,
    output_dir: Path,
    formal_candidate_only: bool = False,
) -> dict[str, Any] | None:
    root = Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir
    latest_payload: dict[str, Any] | None = None
    latest_date: date | None = None
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            target_date = date.fromisoformat(str(payload["target_date"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        operation_context = dict(payload.get("operation_context") or {})
        if formal_candidate_only and not _is_acceptance_candidate(
            operation_context=operation_context
        ):
            continue
        if latest_date is None or target_date > latest_date:
            latest_date = target_date
            latest_payload = payload
    return latest_payload


def _extract_evidence_accounts(
    *,
    latest_formal_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for account in latest_formal_payload.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        user_id = _parse_optional_positive_int(account.get("user_id"))
        account_id = _parse_optional_positive_int(account.get("account_id"))
        if user_id is None or account_id is None:
            continue
        key = (user_id, account_id)
        if key in seen:
            continue
        seen.add(key)
        advisor = dict(account.get("auto_advisor") or {})
        accounts.append(
            {
                "user_id": user_id,
                "account_id": account_id,
                "risk_requested": bool(account.get("risk_center_daily_report")),
                "weekly_requested": (
                    advisor.get("weekly_report") is not None
                    or advisor.get("weekly_report_persistence") is not None
                ),
            }
        )
    return accounts


def _collect_current_risk_report_persistence(
    *,
    target_date: date,
    accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        repository = get_risk_daily_report_repository()
        records = []
        for account in accounts:
            account_id = int(account["account_id"])
            report = repository.get_report(account_id=account_id, report_date=target_date)
            records.append(
                {
                    "account_id": account_id,
                    "report_id": _object_or_dict_get(report, "id"),
                    "report_date": _format_optional_date(
                        _object_or_dict_get(report, "report_date")
                    ),
                    "report_status": _object_or_dict_get(report, "status"),
                    "ok": report is not None
                    and str(_object_or_dict_get(report, "status") or "") == "ok",
                }
            )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    ok_count = sum(1 for record in records if record["ok"])
    return {
        "status": "ok" if ok_count == len(records) else "warning",
        "account_count": len(records),
        "ok_account_count": ok_count,
        "missing_account_count": len(records) - ok_count,
        "records": records,
    }


def _collect_current_weekly_report_persistence(
    *,
    target_date: date,
    accounts: list[dict[str, Any]],
) -> dict[str, Any]:
    due_status = build_auto_advisor_weekly_due_status(target_date=target_date)
    if due_status["due"] is not True:
        return {
            "status": "not_due",
            "reason": due_status["reason"],
            "target_date": target_date.isoformat(),
            "scheduled_for": due_status["scheduled_for"],
            "next_scheduled_for": due_status.get("next_scheduled_for"),
            "account_count": len(accounts),
            "ok_account_count": 0,
            "missing_account_count": 0,
            "records": [],
        }

    try:
        repository = get_auto_advisor_report_repository()
        records = []
        target_report_date = target_date.isoformat()
        for account in accounts:
            user_id = int(account["user_id"])
            account_id = int(account["account_id"])
            reports = repository.list_recent_reports(
                user_id=user_id,
                account_id=account_id,
                limit=20,
            )
            matched_report = next(
                (
                    report
                    for report in reports
                    if str(report.get("report_date") or "") == target_report_date
                ),
                None,
            )
            matched_report_id = matched_report.get("id") if matched_report else None
            notifications = repository.list_recent_notifications(
                user_id=user_id,
                account_id=account_id,
                limit=50,
            )
            matched_notifications = [
                notification
                for notification in notifications
                if matched_report_id is not None
                and notification.get("report_id") == matched_report_id
            ]
            delivered_count = sum(
                1
                for notification in matched_notifications
                if str(notification.get("delivery_status") or "").lower() == "delivered"
            )
            records.append(
                {
                    "user_id": user_id,
                    "account_id": account_id,
                    "report_id": matched_report_id,
                    "report_status": matched_report.get("status") if matched_report else None,
                    "matched_notification_count": len(matched_notifications),
                    "delivered_notification_count": delivered_count,
                    "ok": matched_report_id is not None and delivered_count > 0,
                }
            )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    ok_count = sum(1 for record in records if record["ok"])
    return {
        "status": "ok" if ok_count == len(records) else "warning",
        "account_count": len(records),
        "ok_account_count": ok_count,
        "missing_account_count": len(records) - ok_count,
        "records": records,
    }


def _is_acceptance_candidate(*, operation_context: dict[str, Any]) -> bool:
    if not operation_context:
        return True
    return (
        operation_context.get("mode") == "formal"
        and operation_context.get("target_date_closed") is True
        and operation_context.get("allow_unclosed_target_date") is not True
    )


def _parse_optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _object_or_dict_get(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _format_optional_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)
