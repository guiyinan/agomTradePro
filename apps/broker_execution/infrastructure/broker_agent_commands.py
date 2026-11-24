"""Lease Agent commands and record their terminal acknowledgments."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
    BrokerExecutionNotFoundError,
)
from apps.broker_execution.domain.entities import LiveOrderStatus
from apps.broker_execution.domain.rules import validate_order_transition

from .models import BrokerCommandModel, BrokerExecutionAuditModel, LiveOrderModel


def lease_agent_commands(
    self, *, agent_pk: int, allowed_account_ids: list[int], limit: int
) -> dict[str, Any]:
    """Lease pending commands for delivery to one Agent."""

    rows: list[dict[str, Any]] = []
    now = timezone.now()
    with transaction.atomic():
        BrokerCommandModel._default_manager.filter(
            agent_id=agent_pk,
            status="leased",
            leased_at__lt=now - timedelta(minutes=2),
        ).update(status="pending", leased_at=None)
        commands = list(
            BrokerCommandModel._default_manager.select_for_update()
            .filter(agent_id=agent_pk, status="pending")
            .filter(Q(account_id=0) | Q(account_id__in=allowed_account_ids))
            .order_by("created_at")[:limit]
        )
        for command in commands:
            command.status = "leased"
            command.leased_at = now
            command.save(update_fields=["status", "leased_at"])
            rows.append(
                {
                    "command_id": str(command.command_id),
                    "command_type": command.command_type,
                    "account_id": command.account_id,
                    "payload": command.payload or {},
                    "created_at": command.created_at.isoformat(),
                }
            )
    return {"commands": rows, "total_count": len(rows)}


def complete_agent_command(
    *,
    agent_pk: int,
    allowed_account_ids: list[int],
    command_id: str,
    success: bool,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Complete one leased command and normalize cancel acknowledgement."""

    with transaction.atomic():
        command = (
            BrokerCommandModel._default_manager.select_for_update()
            .filter(command_id=command_id, agent_id=agent_pk)
            .first()
        )
        if command is None:
            raise BrokerExecutionNotFoundError("Agent command does not exist")
        if command.account_id and command.account_id not in set(allowed_account_ids):
            raise BrokerAgentAuthenticationError("Command exceeds the credential account scope")
        if command.status in {"completed", "failed"}:
            return {
                "accepted": True,
                "status": command.status,
                "idempotent_replay": True,
            }
        if command.status != "leased":
            raise BrokerExecutionConflictError("Agent command is not leased")
        command.status = "completed" if success else "failed"
        command.completed_at = timezone.now()
        command.payload = dict(command.payload or {}) | {"result": result}
        command.save(update_fields=["status", "completed_at", "payload"])
        client_order_id = str(command.payload.get("client_order_id") or "")
        audit_account_id = command.account_id
        audit_resource_type = "broker_command"
        audit_resource_id = str(command.command_id)
        audit_before: dict[str, Any] = {"status": "leased"}
        audit_after: dict[str, Any] = {
            "status": command.status,
            "result": result,
        }
        if command.command_type == "cancel" and client_order_id:
            order = (
                LiveOrderModel._default_manager.select_for_update()
                .filter(client_order_id=client_order_id, agent_id=agent_pk)
                .first()
            )
            if order is not None and order.status == LiveOrderStatus.CANCEL_PENDING.value:
                audit_account_id = order.account_id
                audit_resource_type = "live_order"
                audit_resource_id = str(order.client_order_id)
                audit_before = {"status": order.status}
                if not success:
                    target = LiveOrderStatus.RECONCILIATION_REQUIRED.value
                    validate_order_transition(order.status, target)
                    order.status = target
                    order.version += 1
                    order.save(update_fields=["status", "version", "updated_at"])
                audit_after = {
                    "status": order.status,
                    "command_status": command.status,
                    "awaiting_broker_final_status": success,
                    "result": result,
                }
        BrokerExecutionAuditModel._default_manager.create(
            user_id=command.agent.user_id,
            actor=None,
            actor_type="agent",
            action=f"agent_command_{command.command_type}_{command.status}",
            account_id=audit_account_id,
            resource_type=audit_resource_type,
            resource_id=audit_resource_id,
            before=audit_before,
            after=audit_after,
            reason="Agent command completion",
            request_id=str(command.command_id),
        )
        return {"accepted": True, "status": command.status}
