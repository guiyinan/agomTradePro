"""Scheduled dashboard application tasks."""

from __future__ import annotations

from datetime import date
from typing import Any

from celery import shared_task

from apps.account.application.query_services import get_application_user_by_id
from apps.simulated_trading.application.query_services import (
    list_active_account_targets,
    list_dashboard_account_payloads,
)

from .query_services import build_auto_advisor_weekly_report_payload


@shared_task(name="dashboard.generate_auto_advisor_weekly_reports", time_limit=900, soft_time_limit=850)
def generate_auto_advisor_weekly_reports_task(
    *,
    user_id: int | None = None,
    account_ids: list[int] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Generate weekly auto-advisor reports for scheduled personal review."""

    report_date = _parse_report_date(as_of)
    targets = _resolve_weekly_report_targets(user_id=user_id, account_ids=account_ids)
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for target in targets:
        target_user_id = int(target["user_id"])
        target_account_id = int(target["account_id"])
        user = get_application_user_by_id(target_user_id)
        if user is None:
            errors.append(
                {
                    "account_id": target_account_id,
                    "user_id": target_user_id,
                    "error": "user_not_found",
                }
            )
            continue

        try:
            report = build_auto_advisor_weekly_report_payload(
                account_id=str(target_account_id),
                user=user,
                as_of=report_date,
            )
        except Exception as exc:  # pragma: no cover - defensive task boundary
            errors.append(
                {
                    "account_id": target_account_id,
                    "user_id": target_user_id,
                    "error": str(exc),
                }
            )
            continue

        reports.append(
            {
                "account_id": target_account_id,
                "user_id": target_user_id,
                "report": report,
            }
        )

    return {
        "status": "ok" if not errors else "partial",
        "as_of": report_date.isoformat(),
        "requested_user_id": user_id,
        "requested_account_ids": account_ids or [],
        "target_count": len(targets),
        "generated_count": len(reports),
        "failed_count": len(errors),
        "reports": reports,
        "errors": errors,
    }


def _parse_report_date(as_of: str | None) -> date:
    if not as_of:
        return date.today()
    return date.fromisoformat(str(as_of))


def _resolve_weekly_report_targets(
    *,
    user_id: int | None,
    account_ids: list[int] | None,
) -> list[dict[str, int]]:
    requested_account_ids = {int(account_id) for account_id in account_ids or []}
    if user_id is not None:
        accounts = list_dashboard_account_payloads(int(user_id))
        targets = [
            {
                "account_id": int(account["id"]),
                "user_id": int(user_id),
            }
            for account in accounts
            if (not requested_account_ids or int(account["id"]) in requested_account_ids)
            and (requested_account_ids or bool(account.get("is_active")))
        ]
    else:
        targets = [
            {
                "account_id": int(target["account_id"]),
                "user_id": int(target["user_id"]),
            }
            for target in list_active_account_targets()
            if not requested_account_ids or int(target["account_id"]) in requested_account_ids
        ]

    return _dedupe_targets(targets)


def _dedupe_targets(targets: list[dict[str, int]]) -> list[dict[str, int]]:
    seen: set[tuple[int, int]] = set()
    deduped: list[dict[str, int]] = []
    for target in targets:
        key = (int(target["user_id"]), int(target["account_id"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped
