"""Application-boundary safety tests for broker execution."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from apps.broker_execution.application import query_services, tasks
from apps.broker_execution.application.alert_forwarding import (
    forward_operational_alerts,
)
from apps.broker_execution.application.ports import (
    BrokerExecutionRepositoryProtocol,
)
from apps.broker_execution.application.query_services import (
    BrokerExecutionQueryService,
)
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionValidationError,
)
from apps.broker_execution.application.use_cases import (
    CreateLiveOrderFromExecutionPlanUseCase,
)


def _repository(**methods: Any) -> BrokerExecutionRepositoryProtocol:
    """Build a deliberately small structural fake for one test."""

    return cast(BrokerExecutionRepositoryProtocol, SimpleNamespace(**methods))


def _allow_view(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        query_services,
        "require_action",
        lambda _actor, _action: (7, "owner", False),
    )
    monkeypatch.setattr(
        query_services,
        "action_permissions",
        lambda _actor: {"approve": True, "reject": True, "cancel": True},
    )


def test_alert_forwarding_is_fail_safe_and_reports_each_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, Any]] = []

    def fake_record_operational_alert(**payload: Any) -> str:
        recorded.append(payload)
        return "alert-1" if len(recorded) == 1 else ""

    monkeypatch.setattr(
        "apps.task_monitor.application.operational_alerts.record_operational_alert",
        fake_record_operational_alert,
    )

    alert_ids, failure_count = forward_operational_alerts(
        [
            {
                "level": "critical",
                "task_name": "broker.test",
                "title": "first",
                "message": "first message",
                "metadata": {"account_id": 7},
            },
            {"level": "critical"},
            {
                "level": "warning",
                "task_name": "broker.test",
                "title": "second",
                "message": "second message",
            },
        ]
    )

    assert alert_ids == ["alert-1"]
    assert failure_count == 2
    assert recorded[0]["metadata"] == {"account_id": 7}


def test_live_order_default_quote_provider_uses_published_public_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-trade quote evidence must not call Data Center internal services."""

    expected = {
        "asset_code": "000001.SZ",
        "current_price": 12.3,
        "must_not_use_for_decision": False,
        "is_stale": False,
        "publication_id": "pub-1",
    }
    monkeypatch.setattr(
        "apps.data_center.application.public.get_published_latest_quote_payload",
        lambda asset_code: expected if asset_code == "000001.SZ" else None,
    )

    use_case = CreateLiveOrderFromExecutionPlanUseCase(
        repository=_repository(),
        account_projection_provider=lambda **_kwargs: {},
        risk_evaluator=SimpleNamespace(),
    )

    assert use_case.latest_quote_provider is not None
    assert use_case.latest_quote_provider("000001.SZ") == expected


def test_alert_forwarding_never_propagates_monitoring_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_recording(**_payload: Any) -> str:
        raise RuntimeError("monitor unavailable")

    monkeypatch.setattr(
        "apps.task_monitor.application.operational_alerts.record_operational_alert",
        fail_recording,
    )

    alert_ids, failure_count = forward_operational_alerts(
        [
            {
                "level": "critical",
                "task_name": "broker.test",
                "title": "test",
                "message": "test message",
            }
        ]
    )

    assert alert_ids == []
    assert failure_count == 1


def test_maintenance_result_survives_malformed_alert_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        run_maintenance=lambda: {
            "stale_agents": 0,
            "expired_orders": 1,
            "released_leases": 0,
            "alerts": "invalid",
        }
    )
    monkeypatch.setattr(tasks, "get_broker_execution_repository", lambda: repository)

    result = tasks.run_broker_execution_maintenance.run()

    assert result["expired_orders"] == 1
    assert result["task_monitor_alert_ids"] == []
    assert result["task_monitor_alert_failure_count"] == 1
    assert {
        key: result[key]
        for key in ("outcome", "success", "requested", "succeeded", "failed", "stored")
    } == {
        "outcome": "success",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 1,
    }


def test_reconciliation_task_reports_normalized_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(
        list_reconciliation_targets=lambda: [],
        generate_reconciliation_runs=lambda **_payload: {
            "created_runs": 0,
            "duplicate_runs": 0,
            "alerts": [],
        },
    )
    monkeypatch.setattr(tasks, "get_broker_execution_repository", lambda: repository)

    result = tasks.generate_broker_reconciliation_runs.run()

    assert {
        key: result[key]
        for key in ("outcome", "success", "requested", "succeeded", "failed", "stored")
    } == {
        "outcome": "noop",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 0,
    }


def test_reconciliation_rejects_invalid_target_before_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_generate(**_payload: Any) -> dict[str, Any]:
        raise AssertionError("reconciliation persistence must not be called")

    repository = _repository(
        list_reconciliation_targets=lambda: [{"user_id": 7, "account_id": 0}],
        generate_reconciliation_runs=fail_generate,
    )
    monkeypatch.setattr(tasks, "get_broker_execution_repository", lambda: repository)

    with pytest.raises(BrokerExecutionValidationError, match="invalid identifiers"):
        tasks.generate_broker_reconciliation_runs.run()


@pytest.mark.parametrize("limit", [0, -1, 501, True])
def test_order_query_rejects_unbounded_limit_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
    limit: int,
) -> None:
    _allow_view(monkeypatch)

    def fail_list_orders(**_payload: Any) -> list[dict[str, Any]]:
        raise AssertionError("repository must not be called")

    service = BrokerExecutionQueryService(_repository(list_orders=fail_list_orders))

    with pytest.raises(BrokerExecutionValidationError, match="limit"):
        service.orders(actor=object(), limit=limit)


def test_order_query_normalizes_bounded_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_view(monkeypatch)
    received: dict[str, Any] = {}

    def list_orders(**payload: Any) -> list[dict[str, Any]]:
        received.update(payload)
        return []

    service = BrokerExecutionQueryService(_repository(list_orders=list_orders))

    result = service.orders(
        actor=object(),
        account_id=8,
        status="  READY  ",
        limit=25,
    )

    assert result == {"orders": [], "total_count": 0}
    assert received == {
        "user_id": 7,
        "is_admin": False,
        "account_id": 8,
        "status": "READY",
        "limit": 25,
    }


def test_order_detail_canonicalizes_uuid_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_view(monkeypatch)
    received: dict[str, Any] = {}

    def get_order(**payload: Any) -> dict[str, Any]:
        received.update(payload)
        return {
            "client_order_id": payload["client_order_id"],
            "account_id": 7,
            "approval_digest": "",
        }

    service = BrokerExecutionQueryService(
        _repository(
            get_order=get_order,
            has_account_access=lambda **_payload: True,
        )
    )
    order_id = UUID("00000000-0000-0000-0000-000000000001")

    result = service.order_detail(actor=object(), client_order_id=order_id)

    assert result["client_order_id"] == str(order_id)
    assert received["client_order_id"] == str(order_id)


def test_order_detail_separates_lifecycle_from_account_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_view(monkeypatch)
    access_checks: list[str] = []

    def has_account_access(**payload: Any) -> bool:
        action = str(payload["action"])
        access_checks.append(action)
        return action != "cancel"

    repository = _repository(
        get_order=lambda **_payload: {
            "client_order_id": "00000000-0000-0000-0000-000000000001",
            "account_id": 7,
            "approval_digest": "",
            "action_availability": {
                "approve": False,
                "reject": False,
                "cancel": True,
            },
        },
        has_account_access=has_account_access,
    )
    service = BrokerExecutionQueryService(
        repository,
        clock=lambda: datetime(2026, 8, 13, 9, tzinfo=UTC),
    )

    result = service.order_detail(
        actor=object(),
        client_order_id="00000000-0000-0000-0000-000000000001",
    )

    assert access_checks == ["approve", "reject", "cancel"]
    assert result["lifecycle_transitions"] == {
        "approve": False,
        "reject": False,
        "cancel": True,
    }
    assert result["actor_authorization"] == {
        "approve": True,
        "reject": True,
        "cancel": False,
    }
    assert result["must_not_execute"] is True


def test_order_detail_rejects_malformed_uuid_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_view(monkeypatch)

    def fail_get_order(**_payload: Any) -> dict[str, Any]:
        raise AssertionError("repository must not be called")

    service = BrokerExecutionQueryService(_repository(get_order=fail_get_order))

    with pytest.raises(BrokerExecutionValidationError, match="client_order_id"):
        service.order_detail(actor=object(), client_order_id="not-a-uuid")
