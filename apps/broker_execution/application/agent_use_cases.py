"""Machine-only use cases used by the local QMT Agent contract."""

from __future__ import annotations

from typing import Any, cast

from .ports import BrokerExecutionRepositoryProtocol
from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerExecutionValidationError


def _agent_scope(agent: dict[str, Any]) -> tuple[int, list[int]]:
    """Normalize authenticated Agent scope without accepting invalid IDs."""

    try:
        agent_pk = int(agent["agent_pk"])
        allowed_account_ids = sorted({int(item) for item in agent["allowed_account_ids"]})
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise BrokerExecutionValidationError("Authenticated Agent scope is invalid") from exc
    if agent_pk <= 0 or not allowed_account_ids or allowed_account_ids[0] <= 0:
        raise BrokerExecutionValidationError("Authenticated Agent scope is invalid")
    return agent_pk, allowed_account_ids


def _bounded_integer(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Parse one bounded integer request parameter."""

    try:
        normalized = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise BrokerExecutionValidationError(f"{field_name} is invalid") from exc
    if not minimum <= normalized <= maximum:
        raise BrokerExecutionValidationError(f"{field_name} is invalid")
    return normalized


class AgentHeartbeatUseCase:
    """Persist one Agent/QMT health heartbeat."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        agent_pk, allowed_account_ids = _agent_scope(agent)
        result = self.repository.heartbeat_agent(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
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

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self, *, agent: dict[str, Any], limit: int = 10, lease_seconds: int = 30
    ) -> dict[str, Any]:
        agent_pk, allowed_account_ids = _agent_scope(agent)
        normalized_limit = _bounded_integer(
            limit,
            field_name="limit",
            minimum=1,
            maximum=50,
        )
        normalized_lease_seconds = _bounded_integer(
            lease_seconds,
            field_name="lease_seconds",
            minimum=10,
            maximum=120,
        )
        return self.repository.lease_agent_orders(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            limit=normalized_limit,
            lease_seconds=normalized_lease_seconds,
        )


class AcknowledgeSubmittingUseCase:
    """Move a leased order into the no-blind-retry SUBMITTING state."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self, *, agent: dict[str, Any], client_order_id: str, lease_token: str
    ) -> dict[str, Any]:
        agent_pk, allowed_account_ids = _agent_scope(agent)
        normalized_order_id = str(client_order_id or "").strip()
        normalized_lease_token = str(lease_token or "").strip()
        if not normalized_order_id or not normalized_lease_token:
            raise BrokerExecutionValidationError("client_order_id and lease_token are required")
        return self.repository.acknowledge_submitting(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            client_order_id=normalized_order_id,
            lease_token=normalized_lease_token,
        )


class ReportAgentEventsUseCase:
    """Persist idempotent normalized broker order/fill events."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(events) <= 200:
            raise BrokerExecutionValidationError("Between 1 and 200 events are required")
        agent_pk, allowed_account_ids = _agent_scope(agent)
        result = self.repository.report_agent_events(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
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

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        agent_pk, allowed_account_ids = _agent_scope(agent)
        return self.repository.sync_agent_snapshot(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            payload=payload,
        )


class LeaseAgentCommandsUseCase:
    """Lease pending cancel/pause/sync commands for the authenticated Agent."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(self, *, agent: dict[str, Any], limit: int = 20) -> dict[str, Any]:
        agent_pk, allowed_account_ids = _agent_scope(agent)
        normalized_limit = _bounded_integer(
            limit,
            field_name="limit",
            minimum=1,
            maximum=50,
        )
        return self.repository.lease_agent_commands(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            limit=normalized_limit,
        )


class CompleteAgentCommandUseCase:
    """Persist the result of a command leased to the authenticated Agent."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
    ) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        agent: dict[str, Any],
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(success, bool):
            raise BrokerExecutionValidationError("success must be boolean")
        normalized_command_id = str(command_id or "").strip()
        if not normalized_command_id:
            raise BrokerExecutionValidationError("command_id is required")
        agent_pk, allowed_account_ids = _agent_scope(agent)
        return self.repository.complete_agent_command(
            agent_pk=agent_pk,
            allowed_account_ids=allowed_account_ids,
            command_id=normalized_command_id,
            success=success,
            result=result,
        )
