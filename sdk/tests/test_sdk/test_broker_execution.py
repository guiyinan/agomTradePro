"""Formal broker_execution SDK request contracts."""

from unittest.mock import Mock

from agomtradepro.modules.broker_execution import BrokerExecutionModule


def test_sdk_reads_overview_and_order_catalog() -> None:
    client = Mock()
    overview = {
        "today_readiness": "REVIEW",
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "evidence_complete": False,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "blocker_codes": ["broker_snapshot_missing_stale_or_invalid"],
        "source_times": [
            {
                "account_id": 7,
                "snapshot_captured_at": None,
                "connection_observed_at": "2026-08-13T11:59:30Z",
            }
        ],
    }
    client.get.side_effect = [
        {"success": True, "data": overview},
        {"success": True, "data": {"orders": [], "total_count": 0}},
    ]
    module = BrokerExecutionModule(client)
    assert module.overview() == overview
    assert module.list_orders(status="READY")["total_count"] == 0
    client.get.assert_any_call("/api/broker-execution/", params=None)
    client.get.assert_any_call(
        "/api/broker-execution/orders/", params={"status": "READY", "limit": 100}
    )


def test_sdk_connection_read_preserves_current_data_markers() -> None:
    client = Mock()
    expected = {
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "connections": [
            {
                "agent_id": "agent-1",
                "source_observed_at": None,
                "received_at": "2026-08-13T12:00:00Z",
                "freshness_status": "missing_source",
                "qmt_connected": False,
                "blocker_codes": ["broker_agent_source_observation_missing"],
            }
        ],
        "total_count": 1,
    }
    client.get.return_value = {"success": True, "data": expected}

    assert BrokerExecutionModule(client).connections() == expected
    client.get.assert_called_once_with("/api/broker-execution/connections/", params=None)


def test_sdk_audit_read_preserves_redaction_and_display_only_markers() -> None:
    client = Mock()
    expected = {
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "events": [
            {
                "id": 7,
                "actor_type": "user",
                "action": "order_approve",
                "account_id": 3,
                "resource_type": "live_order",
                "created_at": "2026-08-13T11:59:00+00:00",
                "evaluated_at": "2026-08-13T12:00:00+00:00",
                "before": {"status": "WAITING_APPROVAL", "version": 1},
                "after": {"status": "READY", "version": 2},
                "details_redacted": True,
                "blocker_codes": ["broker_audit_details_redacted"],
                "permission": "display_only",
                "must_not_execute": True,
                "must_not_use_for_decision": True,
            }
        ],
        "total_count": 1,
        "permission": "display_only",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
    }
    client.get.return_value = {"success": True, "data": expected}

    assert BrokerExecutionModule(client).audit(limit=10) == expected
    client.get.assert_called_once_with("/api/broker-execution/audit/", params={"limit": 10})


def test_sdk_reconciliation_read_preserves_current_display_only_markers() -> None:
    client = Mock()
    expected = {
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "runs": [
            {
                "id": 9,
                "account_id": 7,
                "status": "completed",
                "summary": {
                    "source": "qmt_snapshot_reconciliation",
                    "snapshot_id": 3,
                    "snapshot_captured_at": "2026-08-13T11:58:00+00:00",
                    "difference_count": 0,
                    "p0_auto_stop": False,
                },
                "difference_counts": {
                    "order": 0,
                    "fill": 0,
                    "cash": 0,
                    "position": 0,
                },
                "differences": [],
                "started_at": "2026-08-13T11:59:00+00:00",
                "completed_at": "2026-08-13T11:59:00+00:00",
                "evaluated_at": "2026-08-13T12:00:00+00:00",
                "content_hash": "a" * 64,
                "blocker_codes": [],
                "permission": "display_only",
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        ],
        "total_count": 1,
        "permission": "display_only",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    client.get.return_value = {"success": True, "data": expected}

    assert BrokerExecutionModule(client).reconciliations(limit=10) == expected
    client.get.assert_called_once_with(
        "/api/broker-execution/reconciliations/", params={"limit": 10}
    )


def test_sdk_order_detail_preserves_governed_evidence_and_permission_markers() -> None:
    client = Mock()
    expected = {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "evaluated_at": "2026-08-13T12:00:00+00:00",
        "lifecycle_transitions": {"approve": False, "reject": True, "cancel": True},
        "actor_authorization": {"approve": False, "reject": True, "cancel": True},
        "transport_blocker_codes": [],
        "event_payload_policy": "omitted_untyped",
        "risk_snapshot_policy": "content_hash_only",
        "risk_snapshot_content_hash": None,
        "approval_evidence_status": "blocked",
        "approval_evidence_blocker_codes": ["broker_order_approval_missing"],
        "approval_evidence": None,
        "permission": "display_only",
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "events": [],
        "fills": [],
    }
    client.get.return_value = {"success": True, "data": expected}

    result = BrokerExecutionModule(client).get_order(expected["client_order_id"])

    assert result == expected
    assert result["actor_authorization"]["approve"] is False
    assert result["approval_evidence_blocker_codes"] == ["broker_order_approval_missing"]
    assert result["must_not_execute"] is True
    client.get.assert_called_once_with(
        "/api/broker-execution/orders/00000000-0000-0000-0000-000000000001/",
        params=None,
    )


def test_sdk_order_action_preserves_preview_and_idempotency() -> None:
    client = Mock()
    client.post.return_value = {"success": True, "data": {"preview_only": False}}
    module = BrokerExecutionModule(client)
    result = module.approve_order(
        "00000000-0000-0000-0000-000000000001",
        reason="reviewed",
        preview_only=False,
        expected_version=3,
        idempotency_key="approve-1",
    )
    assert result == {"preview_only": False}
    client.post.assert_called_once_with(
        "/api/broker-execution/orders/00000000-0000-0000-0000-000000000001/approve/",
        data=None,
        json={
            "reason": "reviewed",
            "preview_only": False,
            "expected_version": 3,
            "idempotency_key": "approve-1",
        },
    )


def test_sdk_resume_sends_password_in_nested_reauthentication_envelope() -> None:
    client = Mock()
    client.post.return_value = {"success": True, "data": {"preview_only": False}}
    module = BrokerExecutionModule(client)

    module.set_kill_switch(
        account_id=7,
        active=False,
        reason="readiness restored",
        preview_only=False,
        idempotency_key="resume-7",
        reauth_password="local-password",
    )

    client.post.assert_called_once_with(
        "/api/broker-execution/kill-switch/",
        data=None,
        json={
            "account_id": 7,
            "active": False,
            "reason": "readiness restored",
            "preview_only": False,
            "idempotency_key": "resume-7",
            "reauth": {"method": "password", "credential": "local-password"},
        },
    )
