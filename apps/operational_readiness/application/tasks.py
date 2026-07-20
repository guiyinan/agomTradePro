"""Canonical Celery tasks for operational readiness evidence."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from celery import shared_task

from apps.operational_readiness.management.commands.run_personal_readiness_daily import (
    _parse_date,
    _validate_target_date_is_closed,
    run_personal_readiness_daily,
)

CANONICAL_READINESS_TASK_NAME = (
    "apps.operational_readiness.application.tasks.run_personal_readiness_daily_task"
)
LEGACY_READINESS_TASK_NAME = "apps.task_monitor.application.tasks.run_personal_readiness_daily_task"


def execute_personal_readiness_daily_task(
    *,
    task: Any,
    target_date: str | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    output_dir: str = "var/readiness-evidence",
    required_days: int = 20,
    calendar_source: str = "auto",
    max_qlib_staleness_days: int = 5,
    repair_accounts: bool = False,
    run_workspace_refresh: bool = True,
    include_weekly_advisor: bool = True,
    persist_risk_report: bool = True,
    strict_daily: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "scheduler",
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute readiness with provenance derived from the invoking Celery task."""

    task_request = getattr(task, "request", None)
    trigger_task_id = getattr(task_request, "id", None)
    resolved_target_date = _parse_date(target_date)
    _validate_target_date_is_closed(
        target_date=resolved_target_date,
        allow_unclosed_target_date=allow_unclosed_target_date,
    )
    active_runner = runner or run_personal_readiness_daily
    payload = active_runner(
        target_date=resolved_target_date,
        user_id=user_id,
        account_id=account_id,
        output_dir=Path(output_dir),
        required_days=required_days,
        calendar_source=calendar_source,
        max_qlib_staleness_days=max_qlib_staleness_days,
        repair_accounts=repair_accounts,
        run_workspace_refresh=run_workspace_refresh,
        include_weekly_advisor=include_weekly_advisor,
        persist_risk_report=persist_risk_report,
        allow_unclosed_target_date=allow_unclosed_target_date,
        trigger_source=trigger_source,
        trigger_task_id=trigger_task_id,
        trigger_task_name=getattr(task, "name", None),
    )
    if strict_daily and payload.get("status") != "ok":
        raise RuntimeError(f"Personal readiness daily run is {payload.get('status')}")
    return payload


@shared_task(
    bind=True,
    name=CANONICAL_READINESS_TASK_NAME,
    time_limit=3600,
    soft_time_limit=3300,
)
def run_personal_readiness_daily_task(
    self: Any,
    target_date: str | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    output_dir: str = "var/readiness-evidence",
    required_days: int = 20,
    calendar_source: str = "auto",
    max_qlib_staleness_days: int = 5,
    repair_accounts: bool = False,
    run_workspace_refresh: bool = True,
    include_weekly_advisor: bool = True,
    persist_risk_report: bool = True,
    strict_daily: bool = False,
    allow_unclosed_target_date: bool = False,
    trigger_source: str = "scheduler",
) -> dict[str, Any]:
    """Run the canonical operational-readiness daily pipeline."""

    return execute_personal_readiness_daily_task(
        task=self,
        target_date=target_date,
        user_id=user_id,
        account_id=account_id,
        output_dir=output_dir,
        required_days=required_days,
        calendar_source=calendar_source,
        max_qlib_staleness_days=max_qlib_staleness_days,
        repair_accounts=repair_accounts,
        run_workspace_refresh=run_workspace_refresh,
        include_weekly_advisor=include_weekly_advisor,
        persist_risk_report=persist_risk_report,
        strict_daily=strict_daily,
        allow_unclosed_target_date=allow_unclosed_target_date,
        trigger_source=trigger_source,
    )


__all__ = [
    "CANONICAL_READINESS_TASK_NAME",
    "LEGACY_READINESS_TASK_NAME",
    "execute_personal_readiness_daily_task",
    "run_personal_readiness_daily_task",
]
