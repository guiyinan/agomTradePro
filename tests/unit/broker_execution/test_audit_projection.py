"""Fail-closed tests for Broker execution audit read projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.broker_execution.application.audit_projection import (
    project_broker_audit_event,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _event(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 7,
        "actor_type": "user",
        "actor_id": 11,
        "actor_username": "operator",
        "action": "order_approve",
        "account_id": 3,
        "resource_type": "live_order",
        "resource_id": "order-secret-id",
        "request_id": "request-secret-id",
        "reason": "operator supplied reason",
        "created_at": (NOW - timedelta(minutes=1)).isoformat(),
        "before": {"status": "WAITING_APPROVAL", "version": 1},
        "after": {
            "status": "READY",
            "version": 2,
            "approval_digest": "a" * 64,
            "risk_snapshot": {"token": "secret"},
        },
    }
    payload.update(overrides)
    return payload


def test_order_audit_exposes_only_bounded_status_fields() -> None:
    result = project_broker_audit_event(_event(), evaluated_at=NOW).to_payload()

    assert result["before"] == {"status": "WAITING_APPROVAL", "version": 1}
    assert result["after"] == {"status": "READY", "version": 2}
    assert result["details_redacted"] is True
    assert result["permission"] == "display_only"
    assert result["must_not_execute"] is True
    for forbidden in (
        "actor_id",
        "actor_username",
        "resource_id",
        "request_id",
        "reason",
    ):
        assert forbidden not in result


def test_unknown_action_and_resource_publish_no_dynamic_details() -> None:
    result = project_broker_audit_event(
        _event(
            action="future_writer",
            resource_type="future_resource",
            before={"safe": "looks-safe"},
            after={"nested": {"password": "secret"}},
        ),
        evaluated_at=NOW,
    ).to_payload()

    assert result["before"] == {}
    assert result["after"] == {}
    assert "broker_audit_action_resource_unrecognized" in result["blocker_codes"]


def test_agent_command_result_is_never_published() -> None:
    result = project_broker_audit_event(
        _event(
            action="agent_command_cancel_failed",
            resource_type="live_order",
            before={"status": "leased"},
            after={
                "status": "failed",
                "command_status": "failed",
                "awaiting_broker_final_status": True,
                "result": {
                    "status": "failed",
                    "success": False,
                    "error_code": "QMT_REJECTED",
                    "password": "secret",
                    "arbitrary": {"token": "secret"},
                },
            },
        ),
        evaluated_at=NOW,
    ).to_payload()

    assert result["after"] == {
        "status": "failed",
        "command_status": "failed",
        "awaiting_broker_final_status": True,
    }
    assert result["details_redacted"] is True


def test_unknown_agent_command_type_cannot_use_prefix_bypass() -> None:
    result = project_broker_audit_event(
        _event(
            action="agent_command_execute_trade_completed",
            resource_type="broker_command",
            before={"status": "leased"},
            after={"status": "completed", "result": {"success": True}},
        ),
        evaluated_at=NOW,
    ).to_payload()

    assert result["before"] == {}
    assert result["after"] == {}
    assert "broker_audit_action_resource_unrecognized" in result["blocker_codes"]


def test_future_or_naive_created_at_is_blocked_without_time_laundering() -> None:
    future = project_broker_audit_event(
        _event(created_at=(NOW + timedelta(seconds=1)).isoformat()),
        evaluated_at=NOW,
    ).to_payload()
    naive = project_broker_audit_event(
        _event(created_at="2026-08-13T11:59:00"),
        evaluated_at=NOW,
    ).to_payload()

    assert "broker_audit_created_at_future" in future["blocker_codes"]
    assert future["created_at"] != future["evaluated_at"]
    assert "broker_audit_created_at_invalid" in naive["blocker_codes"]
    assert naive["created_at"] is None


def test_credential_and_request_context_never_reach_projection() -> None:
    result = project_broker_audit_event(
        _event(
            action="agent_auth_failed",
            resource_type="agent_authentication",
            before={},
            after={
                "agent_id": "agent-1",
                "credential_id": "credential-1",
                "required_scope": "agent.orders.read",
                "source_ip": "10.0.0.1",
                "failure_code": "BAD_SIGNATURE",
                "request_context": {"user_agent": "secret-agent"},
            },
        ),
        evaluated_at=NOW,
    ).to_payload()

    assert result["after"] == {}
    assert result["details_redacted"] is True
