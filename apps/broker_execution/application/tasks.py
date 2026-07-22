"""Scheduled broker-execution maintenance and reconciliation tasks."""

from __future__ import annotations

from celery import shared_task

from .repository_provider import get_broker_execution_repository


@shared_task(name="broker_execution.run_maintenance")
def run_broker_execution_maintenance() -> dict[str, object]:
    """Expire orders/leases and mark stale Agents offline."""

    from apps.task_monitor.application.operational_alerts import (
        record_operational_alert,
    )

    result = get_broker_execution_repository().run_maintenance()
    result["task_monitor_alert_ids"] = [
        alert_id
        for alert in result.get("alerts", [])
        if (alert_id := record_operational_alert(**alert))
    ]
    return result


@shared_task(name="broker_execution.generate_reconciliation_runs")
def generate_broker_reconciliation_runs() -> dict[str, object]:
    """Reconcile QMT facts with the unified ledger and forward P0 alerts."""

    from apps.simulated_trading.application.query_services import (
        get_account_execution_projection,
    )
    from apps.task_monitor.application.operational_alerts import (
        record_operational_alert,
    )

    repository = get_broker_execution_repository()
    projections: dict[int, dict[str, object] | None] = {}
    for target in repository.list_reconciliation_targets():
        projections[target["account_id"]] = get_account_execution_projection(
            user_id=target["user_id"],
            account_id=target["account_id"],
        )
    result = repository.generate_reconciliation_runs(
        account_projections=projections
    )
    alert_ids = []
    for alert in result.get("alerts", []):
        alert_ids.append(record_operational_alert(**alert))
    result["task_monitor_alert_ids"] = [item for item in alert_ids if item]
    return result
