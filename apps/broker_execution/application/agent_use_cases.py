"""Machine-only use cases used by the local QMT Agent contract."""

from __future__ import annotations

from typing import Any

from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionValidationError


class AgentHeartbeatUseCase:
    """Persist one Agent/QMT health heartbeat."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        result = self.repository.heartbeat_agent(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            payload=payload,
        )
        from apps.task_monitor.application.operational_alerts import (
            record_operational_alert,
        )

        result["task_monitor_alert_ids"] = [
            alert_id
            for alert in result.get("alerts", [])
            if (alert_id := record_operational_alert(**alert))
        ]
        return result


class LeaseAgentOrdersUseCase:
    """Atomically lease READY orders bound to the authenticated Agent."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self, *, agent: dict[str, Any], limit: int = 10, lease_seconds: int = 30
    ) -> dict[str, Any]:
        if not 1 <= int(limit) <= 50 or not 10 <= int(lease_seconds) <= 120:
            raise BrokerExecutionValidationError("Invalid lease limits")
        return self.repository.lease_agent_orders(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            limit=int(limit),
            lease_seconds=int(lease_seconds),
        )


class AcknowledgeSubmittingUseCase:
    """Move a leased order into the no-blind-retry SUBMITTING state."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self, *, agent: dict[str, Any], client_order_id: str, lease_token: str
    ) -> dict[str, Any]:
        return self.repository.acknowledge_submitting(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            client_order_id=client_order_id,
            lease_token=lease_token,
        )


class ReportAgentEventsUseCase:
    """Persist idempotent normalized broker order/fill events."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self, *, agent: dict[str, Any], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if len(events) > 200:
            raise BrokerExecutionValidationError("At most 200 events are accepted")
        result = self.repository.report_agent_events(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            events=events,
        )
        from apps.task_monitor.application.operational_alerts import (
            record_operational_alert,
        )

        result["task_monitor_alert_ids"] = [
            alert_id
            for alert in result.get("alerts", [])
            if (alert_id := record_operational_alert(**alert))
        ]
        return result


class SyncAgentSnapshotUseCase:
    """Persist cash and position snapshots from the authenticated Agent."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.sync_agent_snapshot(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            payload=payload,
        )


class LeaseAgentCommandsUseCase:
    """Lease pending cancel/pause/sync commands for the authenticated Agent."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], limit: int = 20) -> dict[str, Any]:
        return self.repository.lease_agent_commands(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            limit=max(1, min(int(limit), 50)),
        )


class CompleteAgentCommandUseCase:
    """Persist the result of a command leased to the authenticated Agent."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        agent: dict[str, Any],
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self.repository.complete_agent_command(
            agent_pk=int(agent["agent_pk"]),
            allowed_account_ids=list(agent["allowed_account_ids"]),
            command_id=command_id,
            success=bool(success),
            result=result,
        )
