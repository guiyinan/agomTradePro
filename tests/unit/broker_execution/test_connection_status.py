"""Pure current-data contracts for Agent/QMT connection health."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from apps.broker_execution.application import query_services
from apps.broker_execution.application.connection_status import project_connection_status
from apps.broker_execution.application.query_services import BrokerExecutionQueryService
from apps.broker_execution.domain.connection_freshness import heartbeat_times_are_fresh

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _row(**overrides: Any) -> dict[str, object]:
    observed_at = NOW - timedelta(seconds=30)
    payload: dict[str, object] = {
        "agent_id": "agent-1",
        "display_name": "QMT Agent",
        "status": "online",
        "qmt_connected": True,
        "source_observed_at": observed_at.isoformat(),
        "received_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "is_active": True,
        "bindings": [],
    }
    payload.update(overrides)
    return payload


def test_fresh_connection_preserves_source_and_receipt_clocks() -> None:
    result = project_connection_status(_row(), evaluated_at=NOW)

    assert result["source_observed_at"] == "2026-08-13T11:59:30Z"
    assert result["received_at"] == "2026-08-13T11:59:31Z"
    assert result["valid_until"] == "2026-08-13T12:01:00Z"
    assert result["freshness_status"] == "fresh"
    assert result["qmt_connected"] is True
    assert result["blocker_codes"] == []
    assert result["must_not_use_for_decision"] is False
    assert result["must_not_execute"] is False


@pytest.mark.parametrize(
    ("overrides", "freshness", "blocker"),
    [
        (
            {
                "source_observed_at": (NOW - timedelta(seconds=91)).isoformat(),
                "received_at": (NOW - timedelta(seconds=90)).isoformat(),
            },
            "stale",
            "broker_agent_heartbeat_stale",
        ),
        ({"source_observed_at": None}, "missing_source", "broker_agent_source_observation_missing"),
        ({"received_at": None}, "missing_receipt", "broker_agent_receipt_missing"),
        (
            {"source_observed_at": (NOW + timedelta(seconds=1)).isoformat()},
            "invalid_future",
            "broker_agent_source_observation_future",
        ),
    ],
)
def test_source_or_receipt_clock_failures_block_current_health(
    overrides: dict[str, object],
    freshness: str,
    blocker: str,
) -> None:
    result = project_connection_status(_row(**overrides), evaluated_at=NOW)

    assert result["freshness_status"] == freshness
    assert blocker in result["blocker_codes"]
    assert result["qmt_connected"] is False
    assert result["must_not_use_for_decision"] is True
    assert result["must_not_execute"] is True


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"is_active": False}, "broker_agent_inactive"),
        ({"status": "offline"}, "broker_agent_not_online"),
        ({"qmt_connected": False}, "qmt_not_reported_connected"),
    ],
)
def test_reported_state_cannot_override_connection_blockers(
    overrides: dict[str, object],
    blocker: str,
) -> None:
    result = project_connection_status(_row(**overrides), evaluated_at=NOW)

    assert blocker in result["blocker_codes"]
    assert result["qmt_connected"] is False


def test_naive_evaluation_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        project_connection_status(_row(), evaluated_at=datetime(2026, 8, 13, 12, 0))


def test_execution_freshness_helper_rejects_old_or_misordered_clocks() -> None:
    assert heartbeat_times_are_fresh(
        source_observed_at=NOW - timedelta(seconds=30),
        received_at=NOW - timedelta(seconds=29),
        evaluated_at=NOW,
    )
    assert not heartbeat_times_are_fresh(
        source_observed_at=NOW - timedelta(seconds=91),
        received_at=NOW - timedelta(seconds=30),
        evaluated_at=NOW,
    )
    assert not heartbeat_times_are_fresh(
        source_observed_at=NOW,
        received_at=NOW - timedelta(seconds=1),
        evaluated_at=NOW,
    )


def test_execution_freshness_helper_rejects_missing_or_naive_clocks() -> None:
    assert not heartbeat_times_are_fresh(
        source_observed_at=NOW - timedelta(seconds=1),
        received_at=NOW,
        evaluated_at=NOW.replace(tzinfo=None),
    )
    assert not heartbeat_times_are_fresh(
        source_observed_at=None,
        received_at=NOW,
        evaluated_at=NOW,
    )


def test_query_service_uses_shared_projection_and_aggregate_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "require_action",
        lambda _actor, _action: (7, "owner", False),
    )
    repository = SimpleNamespace(
        list_connections=lambda **_kwargs: [
            _row(source_observed_at=None),
        ]
    )
    service = BrokerExecutionQueryService(repository, clock=lambda: NOW)

    result = service.connections(actor=object())

    assert result["evaluated_at"] == NOW.isoformat()
    assert result["total_count"] == 1
    assert result["must_not_use_for_decision"] is True
    assert result["must_not_execute"] is True
    assert result["connections"][0]["freshness_status"] == "missing_source"
