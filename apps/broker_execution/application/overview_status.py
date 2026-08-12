"""Pure, source-time-preserving Broker overview readiness projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import NotRequired, TypedDict

from apps.broker_execution.domain.connection_freshness import heartbeat_times_are_fresh


class OverviewBindingFact(TypedDict):
    """One persisted account-to-Agent execution binding."""

    account_id: int
    agent_id: str
    auto_execution_enabled: bool
    max_snapshot_age_seconds: int
    is_active: bool


class OverviewConnectionFact(TypedDict):
    """One already-projected connection-status fact."""

    agent_id: str
    qmt_connected: bool
    source_observed_at: str | None
    received_at: str | None
    freshness_status: str
    must_not_use_for_decision: bool
    must_not_execute: bool


class OverviewSnapshotFact(TypedDict):
    """Latest persisted Broker snapshot for one account."""

    id: int | str
    captured_at: str
    created_at: str


class OverviewReconciliationFact(TypedDict):
    """Latest persisted reconciliation run for one account."""

    id: int | str
    status: str
    started_at: str
    completed_at: str | None
    snapshot_id: int | str
    snapshot_captured_at: str


class OverviewAccountEvidenceFact(TypedDict):
    """Latest snapshot and reconciliation evidence for one account."""

    account_id: int
    snapshot: OverviewSnapshotFact | None
    reconciliation: OverviewReconciliationFact | None


class OverviewOpenOrderFact(TypedDict):
    """One non-terminal order included in current readiness."""

    account_id: int
    status: str
    expires_at: str | None
    updated_at: str


class OverviewKillSwitchFact(TypedDict):
    """Current kill-switch display payload."""

    active: bool
    controls: NotRequired[list[dict[str, object]]]


class OverviewAlertFact(TypedDict):
    """Current alert display payload."""

    code: str
    severity: str
    last_seen_at: str
    account_id: NotRequired[int]
    auto_stop_applied: NotRequired[bool]
    title: NotRequired[str]


class OverviewRawFacts(TypedDict, total=False):
    """Typed repository payload consumed by the pure overview projector."""

    today_readiness: str
    kill_switch: OverviewKillSwitchFact
    connections: list[OverviewConnectionFact]
    bindings: list[OverviewBindingFact]
    account_evidence: list[OverviewAccountEvidenceFact]
    open_orders: list[OverviewOpenOrderFact]
    active_alerts: list[OverviewAlertFact]
    pending_approvals: dict[str, object]
    execution_exceptions: dict[str, object]
    reconciliation_differences: dict[str, object]
    order_status_counts: dict[str, int]
    daily_reports: list[dict[str, object]]
    generated_at: str


_OPEN_EXCEPTION_STATUSES = frozenset(
    {
        "SUBMITTING",
        "BROKER_REJECTED",
        "FAILED",
        "RECONCILIATION_REQUIRED",
        "CANCEL_PENDING",
    }
)
_EVIDENCE_BLOCKERS = frozenset(
    {
        "broker_alert_observation_invalid",
        "broker_binding_invalid",
        "broker_binding_missing",
        "broker_binding_snapshot_policy_invalid",
        "broker_connection_conflict",
        "broker_connection_unavailable_or_stale",
        "broker_open_order_binding_missing",
        "broker_order_observation_invalid",
        "broker_reconciliation_missing_stale_or_unbound",
        "broker_snapshot_missing_stale_or_invalid",
        "broker_snapshot_or_reconciliation_conflict",
    }
)


def _aware_utc_text(value: object) -> tuple[datetime | None, str | None]:
    """Parse an aware ISO clock while retaining the exact caller-owned text."""

    if not isinstance(value, str) or not value.strip():
        return None, None
    exact = value
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None, exact
    if parsed.tzinfo is None:
        return None, exact
    return parsed.astimezone(UTC), exact


def _count(mapping: object, key: str) -> int:
    """Read a non-negative aggregate count without accepting booleans."""

    if not isinstance(mapping, Mapping):
        return 0
    value = mapping.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def project_broker_overview(
    raw: OverviewRawFacts,
    *,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Publish READY only for one complete and current execution evidence graph."""

    if evaluated_at.tzinfo is None:
        raise ValueError("overview evaluated_at must be timezone-aware")
    evaluated = evaluated_at.astimezone(UTC)
    blockers: set[str] = set()
    source_times: list[dict[str, object]] = []

    active_bindings = [item for item in raw.get("bindings", []) if item["is_active"]]
    if not active_bindings:
        blockers.add("broker_binding_missing")

    connection_by_agent: dict[str, OverviewConnectionFact] = {}
    duplicate_connection_agents: set[str] = set()
    connection_facts = raw.get("connections", [])
    for connection in connection_facts:
        agent_id = connection["agent_id"]
        if agent_id in connection_by_agent:
            duplicate_connection_agents.add(agent_id)
        else:
            connection_by_agent[agent_id] = connection
    if duplicate_connection_agents:
        blockers.add("broker_connection_conflict")

    evidence_by_account: dict[int, OverviewAccountEvidenceFact] = {}
    duplicate_evidence_accounts: set[int] = set()
    for evidence in raw.get("account_evidence", []):
        account_id = evidence["account_id"]
        if account_id in evidence_by_account:
            duplicate_evidence_accounts.add(account_id)
        else:
            evidence_by_account[account_id] = evidence
    if duplicate_evidence_accounts:
        blockers.add("broker_snapshot_or_reconciliation_conflict")

    fresh_connection_count = 0
    active_account_ids: set[int] = set()
    for binding in active_bindings:
        account_id = binding["account_id"]
        agent_id = binding["agent_id"]
        active_account_ids.add(account_id)
        if account_id <= 0 or not agent_id.strip():
            blockers.add("broker_binding_invalid")
        if binding["max_snapshot_age_seconds"] <= 0:
            blockers.add("broker_binding_snapshot_policy_invalid")
        if not binding["auto_execution_enabled"]:
            blockers.add("broker_auto_execution_disabled")

        bound_connection = connection_by_agent.get(agent_id)
        connection_source, connection_source_text = _aware_utc_text(
            bound_connection.get("source_observed_at") if bound_connection else None
        )
        connection_received, connection_received_text = _aware_utc_text(
            bound_connection.get("received_at") if bound_connection else None
        )
        connection_fresh = bool(
            bound_connection is not None
            and bound_connection["qmt_connected"]
            and bound_connection["freshness_status"] == "fresh"
            and not bound_connection["must_not_use_for_decision"]
            and not bound_connection["must_not_execute"]
            and connection_source is not None
            and connection_received is not None
            and heartbeat_times_are_fresh(
                source_observed_at=connection_source,
                received_at=connection_received,
                evaluated_at=evaluated,
            )
        )
        if connection_fresh:
            fresh_connection_count += 1
        else:
            blockers.add("broker_connection_unavailable_or_stale")

        account_evidence = evidence_by_account.get(account_id)
        snapshot = account_evidence["snapshot"] if account_evidence else None
        reconciliation = account_evidence["reconciliation"] if account_evidence else None
        captured_at, captured_text = _aware_utc_text(
            snapshot.get("captured_at") if snapshot else None
        )
        snapshot_created_at, snapshot_created_text = _aware_utc_text(
            snapshot.get("created_at") if snapshot else None
        )
        snapshot_fresh = bool(
            snapshot is not None
            and binding["max_snapshot_age_seconds"] > 0
            and captured_at is not None
            and snapshot_created_at is not None
            and captured_at <= snapshot_created_at <= evaluated
            and evaluated - captured_at <= timedelta(seconds=binding["max_snapshot_age_seconds"])
        )
        if not snapshot_fresh:
            blockers.add("broker_snapshot_missing_stale_or_invalid")

        reconciliation_started, reconciliation_started_text = _aware_utc_text(
            reconciliation.get("started_at") if reconciliation else None
        )
        reconciliation_completed, reconciliation_completed_text = _aware_utc_text(
            reconciliation.get("completed_at") if reconciliation else None
        )
        reconciled_snapshot_at, _reconciled_snapshot_text = _aware_utc_text(
            reconciliation.get("snapshot_captured_at") if reconciliation else None
        )
        reconciliation_complete = bool(
            reconciliation is not None
            and snapshot is not None
            and reconciliation["status"].lower() == "completed"
            and str(reconciliation["snapshot_id"]) == str(snapshot["id"])
            and captured_at is not None
            and reconciled_snapshot_at == captured_at
            and reconciliation_started is not None
            and reconciliation_completed is not None
            and captured_at <= reconciliation_started <= reconciliation_completed <= evaluated
        )
        if not reconciliation_complete:
            blockers.add("broker_reconciliation_missing_stale_or_unbound")

        source_times.append(
            {
                "account_id": account_id,
                "agent_id": agent_id,
                "connection_observed_at": connection_source_text,
                "connection_received_at": connection_received_text,
                "snapshot_captured_at": captured_text,
                "snapshot_created_at": snapshot_created_text,
                "reconciliation_started_at": reconciliation_started_text,
                "reconciliation_completed_at": reconciliation_completed_text,
            }
        )

    for order in raw.get("open_orders", []):
        updated_at, _updated_text = _aware_utc_text(order["updated_at"])
        expires_at, _expires_text = _aware_utc_text(order["expires_at"])
        if updated_at is None or updated_at > evaluated:
            blockers.add("broker_order_observation_invalid")
        if order["account_id"] not in active_account_ids:
            blockers.add("broker_open_order_binding_missing")
        if expires_at is None or expires_at <= evaluated:
            blockers.add("broker_open_order_expired")
        if order["status"].upper() in _OPEN_EXCEPTION_STATUSES:
            blockers.add("broker_open_order_exception")

    kill_switch = raw.get("kill_switch")
    kill_active = bool(kill_switch and kill_switch["active"])
    if kill_active:
        blockers.add("broker_kill_switch_active")

    for alert in raw.get("active_alerts", []):
        observed_at, _observed_text = _aware_utc_text(alert["last_seen_at"])
        if observed_at is None or observed_at > evaluated:
            blockers.add("broker_alert_observation_invalid")
        if alert["severity"].upper() in {"P0", "P1"}:
            blockers.add("broker_blocking_alert_open")

    if _count(raw.get("execution_exceptions"), "count") > 0:
        blockers.add("broker_execution_exception_open")
    if _count(raw.get("reconciliation_differences"), "runs") > 0:
        blockers.add("broker_reconciliation_difference_open")

    evidence_incomplete = bool(blockers.intersection(_EVIDENCE_BLOCKERS))
    if not blockers:
        readiness = "READY"
    elif kill_active:
        readiness = "STOPPED"
    elif active_bindings and fresh_connection_count == 0:
        readiness = "OFFLINE"
    else:
        readiness = "REVIEW"

    result: dict[str, object] = dict(raw)
    result.update(
        {
            "today_readiness": readiness,
            "connections": {
                "total": len(connection_facts),
                "online": sum(bool(item["qmt_connected"]) for item in connection_facts),
                "blocked": sum(not bool(item["qmt_connected"]) for item in connection_facts),
            },
            "connection_evidence": connection_facts,
            "evaluated_at": evaluated.isoformat(),
            "evidence_complete": not evidence_incomplete,
            "must_not_use_for_decision": evidence_incomplete,
            "must_not_execute": readiness != "READY",
            "blocker_codes": sorted(blockers),
            "source_times": source_times,
        }
    )
    return result


__all__ = [
    "OverviewAccountEvidenceFact",
    "OverviewAlertFact",
    "OverviewBindingFact",
    "OverviewConnectionFact",
    "OverviewKillSwitchFact",
    "OverviewOpenOrderFact",
    "OverviewRawFacts",
    "OverviewReconciliationFact",
    "OverviewSnapshotFact",
    "project_broker_overview",
]
