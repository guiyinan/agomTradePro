"""Formal broker_execution SDK request contracts."""

from unittest.mock import Mock

from agomtradepro.modules.broker_execution import BrokerExecutionModule


def test_sdk_reads_overview_and_order_catalog() -> None:
    client = Mock()
    client.get.side_effect = [
        {"success": True, "data": {"today_readiness": "READY"}},
        {"success": True, "data": {"orders": [], "total_count": 0}},
    ]
    module = BrokerExecutionModule(client)
    assert module.overview()["today_readiness"] == "READY"
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
