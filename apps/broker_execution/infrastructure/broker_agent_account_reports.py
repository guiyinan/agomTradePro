"""Persist authenticated Agent heartbeats and account snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.broker_execution.application.execution_contract_capabilities import (
    parse_agent_execution_contracts,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerAgentAuthenticationError,
    BrokerExecutionConflictError,
)
from apps.broker_execution.domain.connection_freshness import heartbeat_times_are_fresh

from .broker_repository_contract import BrokerExecutionRepositoryMixinSupport
from .models import (
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerExecutionAlertModel,
    BrokerPositionSnapshotModel,
    TradingControlModel,
)


def _snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Preserve exact validated numbers and source timestamps in the JSON ledger."""
    return [
        {
            key: (
                value.isoformat()
                if isinstance(value, datetime)
                else str(value) if isinstance(value, Decimal) else value
            )
            for key, value in row.items()
        }
        for row in rows
    ]


def heartbeat_agent(
    repository: BrokerExecutionRepositoryMixinSupport,
    *,
    agent_pk: int,
    allowed_account_ids: list[int],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist Agent health without trusting account ownership from the payload."""

    contracts = parse_agent_execution_contracts(payload.get("execution_constraint_schemas", []))
    agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
    was_connected = agent.qmt_connected
    account_ids = [int(item) for item in payload.get("account_ids", [])]
    if not set(account_ids).issubset(set(allowed_account_ids)):
        raise BrokerAgentAuthenticationError("Heartbeat exceeds the credential account scope")
    allowed_ids = set(
        agent.account_bindings.filter(is_active=True).values_list("account_id", flat=True)
    )
    if not set(account_ids).issubset(allowed_ids):
        raise BrokerAgentAuthenticationError("Heartbeat contains an unbound account")
    received_at = timezone.now()
    raw_observed_at = payload.get("observed_at")
    try:
        observed_at = datetime.fromisoformat(str(raw_observed_at).strip().replace("Z", "+00:00"))
    except ValueError:
        observed_at = None
    source_is_fresh = heartbeat_times_are_fresh(
        source_observed_at=observed_at,
        received_at=received_at,
        evaluated_at=received_at,
    )
    reported_qmt_connected = bool(payload.get("qmt_connected"))
    effective_qmt_connected = bool(reported_qmt_connected and source_is_fresh)
    agent.status = (
        BrokerAgentModel.STATUS_ONLINE
        if effective_qmt_connected
        else BrokerAgentModel.STATUS_DEGRADED
    )
    agent.qmt_connected = effective_qmt_connected
    agent.agent_version = str(payload.get("agent_version") or "")[:32]
    source_observed_at = (
        observed_at.isoformat()
        if isinstance(observed_at, datetime) and observed_at.tzinfo is not None
        else None
    )
    agent.last_heartbeat_at = received_at
    agent.health_snapshot = {
        "account_ids": account_ids,
        "qmt_version": str(payload.get("qmt_version") or "")[:64],
        "dry_run": bool(payload.get("dry_run", True)),
        "message": str(payload.get("message") or "")[:500],
        "source_observed_at": source_observed_at,
        "reported_qmt_connected": reported_qmt_connected,
        "execution_constraint_schemas": list(contracts.schemas),
    }
    agent.save(
        update_fields=[
            "status",
            "qmt_connected",
            "agent_version",
            "last_heartbeat_at",
            "health_snapshot",
            "updated_at",
        ]
    )
    alerts = []
    if not agent.qmt_connected:
        for binding in agent.account_bindings.filter(is_active=True):
            already_open = BrokerExecutionAlertModel._default_manager.filter(
                user_id=binding.user_id,
                account_id=binding.account_id,
                code="P1_QMT_DISCONNECTED",
                status="open",
            ).exists()
            if already_open and not was_connected:
                continue
            alerts.append(
                repository._upsert_operational_alert(
                    user_id=binding.user_id,
                    account_id=binding.account_id,
                    code="P1_QMT_DISCONNECTED",
                    severity="P1",
                    title="QMT 连接已断开",
                    message=f"Agent {agent.agent_id} 仍可通信，但 QMT 当前不可用。",
                    resource_key=agent.agent_id,
                    payload={"agent_id": agent.agent_id},
                )
            )
    else:
        BrokerExecutionAlertModel._default_manager.filter(
            user_id=agent.user_id,
            account_id__in=allowed_ids,
            code__in=["P1_QMT_DISCONNECTED", "P1_QMT_AGENT_OFFLINE"],
            status="open",
        ).update(status="resolved")
    return {
        "accepted": True,
        "server_time": timezone.now().isoformat(),
        "kill_switch_active": TradingControlModel._default_manager.filter(
            user_id=agent.user_id, kill_switch_active=True
        ).exists(),
        "alerts": alerts,
    }


def sync_agent_snapshot(
    repository: BrokerExecutionRepositoryMixinSupport,
    *,
    agent_pk: int,
    allowed_account_ids: list[int],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist one account snapshot and its normalized positions."""

    agent = BrokerAgentModel._default_manager.get(pk=agent_pk, is_active=True)
    account_id = int(payload.get("account_id") or 0)
    if account_id not in set(allowed_account_ids):
        raise BrokerAgentAuthenticationError("Snapshot exceeds the credential account scope")
    captured_at = repository._parse_agent_datetime(payload.get("captured_at"))
    if captured_at > timezone.now() + timedelta(minutes=5):
        raise BrokerExecutionConflictError("Broker snapshot timestamp is too far in the future")
    with transaction.atomic():
        if (
            not agent.account_bindings.select_for_update()
            .filter(account_id=account_id, is_active=True)
            .exists()
        ):
            raise BrokerAgentAuthenticationError("Snapshot account is not bound to this Agent")
        BrokerAccountSnapshotModel._default_manager.update_or_create(
            agent=agent,
            account_id=account_id,
            captured_at=captured_at,
            defaults={
                "user_id": agent.user_id,
                "cash_available": Decimal(str(payload.get("cash_available") or "0")),
                "total_asset": Decimal(str(payload.get("total_asset") or "0")),
                "payload": dict(payload.get("payload") or {})
                | {
                    "orders": _snapshot_rows(payload.get("orders") or []),
                    "trades": _snapshot_rows(payload.get("trades") or []),
                },
            },
        )
        for position in payload.get("positions", []):
            BrokerPositionSnapshotModel._default_manager.update_or_create(
                agent=agent,
                account_id=account_id,
                asset_code=str(position.get("asset_code") or "")[:32],
                captured_at=captured_at,
                defaults={
                    "user_id": agent.user_id,
                    "quantity": Decimal(str(position.get("quantity") or "0")),
                    "available_quantity": Decimal(str(position.get("available_quantity") or "0")),
                    "payload": dict(position.get("payload") or {}),
                },
            )
    return {"accepted": True, "captured_at": captured_at.isoformat()}
