"""Scheduled dashboard application tasks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol, TypedDict, TypeVar, cast

from celery import shared_task

from apps.account.application.query_services import get_application_user_by_id
from apps.simulated_trading.application.query_services import (
    list_active_account_targets,
    list_dashboard_account_payloads,
)

from .auto_advisor_outputs import persist_auto_advisor_weekly_report_outputs
from .query_services import build_auto_advisor_weekly_report_payload

logger = logging.getLogger(__name__)
TaskResult = TypeVar("TaskResult", covariant=True)
DecoratedResult = TypeVar("DecoratedResult")


class WeeklyReportTarget(TypedDict):
    """One account owner selected for scheduled weekly reporting."""

    account_id: int
    user_id: int


class _TypedTask(Protocol[TaskResult]):
    """Callable Celery task exposing a typed synchronous runner."""

    def __call__(self, *args: Any, **kwargs: Any) -> TaskResult: ...

    def run(self, *args: Any, **kwargs: Any) -> TaskResult: ...


def _typed_shared_task(
    *decorator_args: object,
    **decorator_kwargs: object,
) -> Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]]:
    """Narrow Celery's decorator while preserving task result types."""

    return cast(
        Callable[[Callable[..., DecoratedResult]], _TypedTask[DecoratedResult]],
        shared_task(*decorator_args, **decorator_kwargs),
    )


@_typed_shared_task(
    name="dashboard.generate_auto_advisor_weekly_reports",
    time_limit=900,
    soft_time_limit=850,
)
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
            persisted = persist_auto_advisor_weekly_report_outputs(
                user=user,
                report_payload=report,
            )
        except Exception as exc:  # pragma: no cover - defensive task boundary
            logger.error(
                "Auto-advisor weekly report generation failed " "(account_id=%s, error_type=%s)",
                target_account_id,
                type(exc).__name__,
            )
            errors.append(
                {
                    "account_id": target_account_id,
                    "user_id": target_user_id,
                    "error": "auto_advisor_weekly_report_failed",
                }
            )
            continue

        reports.append(
            {
                "account_id": target_account_id,
                "user_id": target_user_id,
                "report": report,
                "persisted": persisted,
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
    if not isinstance(as_of, str) or len(as_of) != 10:
        raise ValueError("as_of must use YYYY-MM-DD")
    return date.fromisoformat(as_of)


def _resolve_weekly_report_targets(
    *,
    user_id: int | None,
    account_ids: list[int] | None,
) -> list[WeeklyReportTarget]:
    if user_id is not None:
        user_id = _positive_id(user_id, "user_id")
    if account_ids is not None and not isinstance(account_ids, list):
        raise ValueError("account_ids must be a list")
    if account_ids is not None and len(account_ids) > 1000:
        raise ValueError("account_ids exceeds the maximum size")
    requested_account_ids = {
        _positive_id(account_id, "account_id") for account_id in account_ids or []
    }
    if user_id is not None:
        accounts = list_dashboard_account_payloads(int(user_id))
        targets: list[WeeklyReportTarget] = [
            {
                "account_id": _positive_id(account["id"], "account_id"),
                "user_id": user_id,
            }
            for account in accounts
            if (
                not requested_account_ids
                or _positive_id(account["id"], "account_id") in requested_account_ids
            )
            and (requested_account_ids or bool(account.get("is_active")))
        ]
    else:
        targets = [
            {
                "account_id": _positive_id(target["account_id"], "account_id"),
                "user_id": _positive_id(target["user_id"], "user_id"),
            }
            for target in list_active_account_targets()
            if not requested_account_ids
            or _positive_id(target["account_id"], "account_id") in requested_account_ids
        ]

    return _dedupe_targets(targets)


def _dedupe_targets(targets: list[WeeklyReportTarget]) -> list[WeeklyReportTarget]:
    seen: set[tuple[int, int]] = set()
    deduped: list[WeeklyReportTarget] = []
    for target in targets:
        key = (int(target["user_id"]), int(target["account_id"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _positive_id(value: object, field_name: str) -> int:
    """Return a positive non-boolean identifier."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        raise ValueError(f"{field_name} must be a positive integer")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed
