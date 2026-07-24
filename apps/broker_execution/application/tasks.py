"""Scheduled broker-execution maintenance and reconciliation tasks."""

from __future__ import annotations

from typing import Any

from shared.infrastructure.celery_typing import typed_shared_task

from .alert_forwarding import forward_operational_alerts
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionValidationError


@typed_shared_task(name="broker_execution.run_maintenance")
def run_broker_execution_maintenance() -> dict[str, object]:
    """Expire orders/leases and mark stale Agents offline."""

    result = get_broker_execution_repository().run_maintenance()
    alert_ids, failure_count = forward_operational_alerts(result.get("alerts"))
    result["task_monitor_alert_ids"] = alert_ids
    result["task_monitor_alert_failure_count"] = failure_count
    return result


@typed_shared_task(name="broker_execution.generate_reconciliation_runs")
def generate_broker_reconciliation_runs() -> dict[str, object]:
    """Reconcile QMT facts with the unified ledger and forward P0 alerts."""

    from apps.simulated_trading.application.query_services import (
        get_account_execution_projection,
    )

    repository = get_broker_execution_repository()
    projections: dict[int, dict[str, Any] | None] = {}
    for target in repository.list_reconciliation_targets():
        user_id = target.get("user_id")
        account_id = target.get("account_id")
        if (
            isinstance(user_id, bool)
            or not isinstance(user_id, int)
            or user_id <= 0
            or isinstance(account_id, bool)
            or not isinstance(account_id, int)
            or account_id <= 0
        ):
            raise BrokerExecutionValidationError(
                "Reconciliation target contains invalid identifiers"
            )
        if account_id in projections:
            raise BrokerExecutionValidationError(
                "Reconciliation target contains a duplicate account"
            )
        projections[account_id] = get_account_execution_projection(
            user_id=user_id,
            account_id=account_id,
        )
    result = repository.generate_reconciliation_runs(account_projections=projections)
    alert_ids, failure_count = forward_operational_alerts(result.get("alerts"))
    result["task_monitor_alert_ids"] = alert_ids
    result["task_monitor_alert_failure_count"] = failure_count
    return result
