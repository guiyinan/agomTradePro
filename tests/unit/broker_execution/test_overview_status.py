"""Pure fail-closed contracts for Broker overview readiness."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from apps.broker_execution.application import query_services
from apps.broker_execution.application.overview_status import project_broker_overview
from apps.broker_execution.application.query_services import BrokerExecutionQueryService

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _facts() -> dict[str, Any]:
    observed = NOW - timedelta(seconds=30)
    snapshot_at = NOW - timedelta(seconds=20)
    return {
        "today_readiness": "OFFLINE",
        "bindings": [
            {
                "account_id": 7,
                "agent_id": "agent-7",
                "auto_execution_enabled": True,
                "max_snapshot_age_seconds": 120,
                "is_active": True,
            }
        ],
        "connections": [
            {
                "agent_id": "agent-7",
                "qmt_connected": True,
                "source_observed_at": _iso(observed),
                "received_at": _iso(observed + timedelta(seconds=1)),
                "freshness_status": "fresh",
                "must_not_use_for_decision": False,
                "must_not_execute": False,
            }
        ],
        "account_evidence": [
            {
                "account_id": 7,
                "snapshot": {
                    "id": "snapshot-7",
                    "captured_at": _iso(snapshot_at),
                    "created_at": _iso(snapshot_at + timedelta(seconds=1)),
                },
                "reconciliation": {
                    "id": "recon-7",
                    "status": "completed",
                    "started_at": _iso(snapshot_at + timedelta(seconds=2)),
                    "completed_at": _iso(snapshot_at + timedelta(seconds=3)),
                    "snapshot_id": "snapshot-7",
                    "snapshot_captured_at": _iso(snapshot_at),
                },
            }
        ],
        "open_orders": [
            {
                "account_id": 7,
                "status": "READY",
                "expires_at": _iso(NOW + timedelta(minutes=5)),
                "updated_at": _iso(NOW - timedelta(seconds=10)),
            }
        ],
        "kill_switch": {"active": False, "controls": []},
        "active_alerts": [],
        "execution_exceptions": {"count": 0, "statuses": {}},
        "reconciliation_differences": {"runs": 0},
        "pending_approvals": {"count": 1},
        "order_status_counts": {"READY": 1},
        "daily_reports": [],
    }


def _project(facts: dict[str, Any] | None = None) -> dict[str, object]:
    return project_broker_overview(facts or _facts(), evaluated_at=NOW)


def test_ready_requires_complete_current_same_snapshot_evidence() -> None:
    facts = _facts()

    result = _project(facts)

    assert result["today_readiness"] == "READY"
    assert result["evidence_complete"] is True
    assert result["must_not_use_for_decision"] is False
    assert result["must_not_execute"] is False
    assert result["blocker_codes"] == []
    assert result["connections"] == {"total": 1, "online": 1, "blocked": 0}
    assert result["connection_evidence"] == facts["connections"]
    assert result["pending_approvals"] == facts["pending_approvals"]
    assert result["order_status_counts"] == facts["order_status_counts"]


def test_evaluated_at_never_replaces_or_reformats_source_times() -> None:
    facts = _facts()
    facts["connections"][0]["source_observed_at"] = "2026-08-13T19:59:30+08:00"

    result = _project(facts)
    source = result["source_times"][0]

    assert result["evaluated_at"] == NOW.isoformat()
    assert source["connection_observed_at"] == "2026-08-13T19:59:30+08:00"
    assert source["snapshot_captured_at"] == facts["account_evidence"][0]["snapshot"]["captured_at"]
    assert source["reconciliation_completed_at"] != result["evaluated_at"]


@pytest.mark.parametrize(
    ("mutate", "blocker", "readiness"),
    [
        (lambda value: value.update(bindings=[]), "broker_binding_missing", "REVIEW"),
        (
            lambda value: value["connections"][0].update(
                qmt_connected=False,
                freshness_status="stale",
                must_not_use_for_decision=True,
                must_not_execute=True,
            ),
            "broker_connection_unavailable_or_stale",
            "OFFLINE",
        ),
        (
            lambda value: value["connections"][0].update(
                source_observed_at=_iso(NOW - timedelta(seconds=91)),
                received_at=_iso(NOW - timedelta(seconds=90)),
            ),
            "broker_connection_unavailable_or_stale",
            "OFFLINE",
        ),
        (
            lambda value: value["account_evidence"][0].update(snapshot=None),
            "broker_snapshot_missing_stale_or_invalid",
            "REVIEW",
        ),
        (
            lambda value: value["account_evidence"][0]["snapshot"].update(
                captured_at=_iso(NOW - timedelta(seconds=121))
            ),
            "broker_snapshot_missing_stale_or_invalid",
            "REVIEW",
        ),
        (
            lambda value: value["account_evidence"][0].update(reconciliation=None),
            "broker_reconciliation_missing_stale_or_unbound",
            "REVIEW",
        ),
        (
            lambda value: value["account_evidence"][0]["reconciliation"].update(
                snapshot_id="substituted-snapshot"
            ),
            "broker_reconciliation_missing_stale_or_unbound",
            "REVIEW",
        ),
        (
            lambda value: value["open_orders"][0].update(expires_at=_iso(NOW)),
            "broker_open_order_expired",
            "REVIEW",
        ),
        (
            lambda value: value["open_orders"][0].update(status="SUBMITTING"),
            "broker_open_order_exception",
            "REVIEW",
        ),
    ],
)
def test_each_required_evidence_breaks_ready(
    mutate: Any,
    blocker: str,
    readiness: str,
) -> None:
    facts = _facts()
    mutate(facts)

    result = _project(facts)

    assert result["today_readiness"] == readiness
    assert blocker in result["blocker_codes"]
    assert result["must_not_execute"] is True


def test_all_active_bindings_require_complete_evidence() -> None:
    facts = _facts()
    second = deepcopy(facts["bindings"][0])
    second.update(account_id=8, agent_id="agent-8")
    facts["bindings"].append(second)

    result = _project(facts)

    assert result["today_readiness"] == "REVIEW"
    assert "broker_connection_unavailable_or_stale" in result["blocker_codes"]
    assert "broker_snapshot_missing_stale_or_invalid" in result["blocker_codes"]
    assert "broker_reconciliation_missing_stale_or_unbound" in result["blocker_codes"]
    assert result["evidence_complete"] is False


def test_kill_switch_has_stop_precedence_over_missing_evidence() -> None:
    facts = _facts()
    facts["kill_switch"] = {"active": True, "controls": []}
    facts["connections"] = []

    result = _project(facts)

    assert result["today_readiness"] == "STOPPED"
    assert "broker_kill_switch_active" in result["blocker_codes"]
    assert result["must_not_execute"] is True
    assert result["must_not_use_for_decision"] is True


@pytest.mark.parametrize("severity", ["P0", "P1"])
def test_open_blocking_alert_prevents_ready_without_erasing_source_times(
    severity: str,
) -> None:
    facts = _facts()
    facts["active_alerts"] = [
        {
            "code": "BROKER_ALERT",
            "severity": severity,
            "last_seen_at": _iso(NOW - timedelta(seconds=5)),
        }
    ]

    result = _project(facts)

    assert result["today_readiness"] == "REVIEW"
    assert "broker_blocking_alert_open" in result["blocker_codes"]
    assert result["evidence_complete"] is True
    assert result["must_not_use_for_decision"] is False
    assert result["must_not_execute"] is True


def test_aggregate_exception_and_reconciliation_counts_cannot_be_hidden() -> None:
    facts = _facts()
    facts["execution_exceptions"]["count"] = 1
    facts["reconciliation_differences"]["runs"] = 1

    result = _project(facts)

    assert result["today_readiness"] == "REVIEW"
    assert "broker_execution_exception_open" in result["blocker_codes"]
    assert "broker_reconciliation_difference_open" in result["blocker_codes"]
    assert result["must_not_execute"] is True


def test_naive_evaluation_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        project_broker_overview(
            _facts(),
            evaluated_at=datetime(2026, 8, 13, 12, 0),
        )


def test_query_service_projects_repository_facts_with_one_trusted_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts()
    connection = facts.pop("connections")[0]
    connection.update(
        {
            "display_name": "QMT Agent",
            "status": "online",
            "reported_qmt_connected": True,
            "agent_version": "1.0",
            "is_active": True,
            "bindings": [],
        }
    )
    monkeypatch.setattr(
        query_services,
        "require_action",
        lambda _actor, _action: (7, "owner", False),
    )

    class _Repository:
        def build_overview(self, **_kwargs: object) -> dict[str, Any]:
            return facts

        def list_connections(self, **_kwargs: object) -> list[dict[str, Any]]:
            return [connection]

    result = BrokerExecutionQueryService(_Repository(), clock=lambda: NOW).overview(actor=object())

    assert result["today_readiness"] == "READY"
    assert result["evaluated_at"] == NOW.isoformat()
    assert result["connection_evidence"][0]["source_observed_at"] == connection[
        "source_observed_at"
    ].replace("+00:00", "Z")
