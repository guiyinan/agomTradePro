"""Pure tests for the typed, actor-aware broker order catalog."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.broker_execution.application import query_services
from apps.broker_execution.application.order_catalog import (
    project_broker_order_catalog_item,
)
from apps.broker_execution.application.ports import BrokerExecutionRepositoryProtocol
from apps.broker_execution.application.query_services import BrokerExecutionQueryService
from apps.broker_execution.application.use_case_errors import (
    BrokerExecutionValidationError,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


def _order(*, account_id: int = 7, suffix: int = 1) -> dict[str, object]:
    return {
        "client_order_id": f"00000000-0000-0000-0000-{suffix:012d}",
        "account_id": account_id,
        "agent_id": f"agent-{account_id}",
        "asset_code": "510300.SH",
        "market": "CN",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100.0000",
        "limit_price": "3.9000",
        "estimated_amount": "390.00",
        "status": "READY",
        "risk_snapshot": {"passed": True, "violations": []},
        "approval_digest": "a" * 64,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "submitted_at": None,
        "broker_order_id": "",
        "filled_quantity": "0.0000",
        "average_fill_price": None,
        "failure_code": "",
        "failure_message": "",
        "version": 2,
        "created_at": (NOW - timedelta(minutes=2)).isoformat(),
        "updated_at": (NOW - timedelta(minutes=1)).isoformat(),
        "action_availability": {"approve": True, "reject": True, "cancel": True},
        "source_recommendation_ids": ["must-remain-lossy"],
    }


def _payload(
    raw: dict[str, object],
    *,
    authorization: dict[str, bool] | None = None,
) -> dict[str, object]:
    return project_broker_order_catalog_item(
        raw,
        evaluated_at=NOW,
        actor_authorization=authorization or {"approve": True, "reject": True, "cancel": False},
    ).to_payload()


def test_catalog_is_lossy_typed_and_replaces_raw_risk_with_hash() -> None:
    payload = _payload(_order())

    assert "risk_snapshot" not in payload
    assert "source_recommendation_ids" not in payload
    assert "agent_id" not in payload
    assert "approval_digest" not in payload
    assert "broker_order_id" not in payload
    assert "failure_message" not in payload
    assert payload["risk_snapshot_policy"] == "content_hash_only"
    assert isinstance(payload["risk_snapshot_content_hash"], str)
    assert len(cast(str, payload["risk_snapshot_content_hash"])) == 64
    assert payload["client_order_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["quantity"] == "100.0000"
    assert payload["created_at"] == (NOW - timedelta(minutes=2)).isoformat()
    assert payload["permission"] == "display_only"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True
    assert payload["blocker_codes"] == ["broker_order_catalog_display_only"]


def test_catalog_separates_lifecycle_authorization_and_effective_actions() -> None:
    payload = _payload(_order())

    lifecycle = {"approve": True, "reject": True, "cancel": True}
    assert payload["action_availability"] == lifecycle
    assert payload["lifecycle_transitions"] == lifecycle
    assert payload["actor_authorization"] == {
        "approve": True,
        "reject": True,
        "cancel": False,
    }
    assert payload["evidence_gate"] == {
        "approve": False,
        "reject": True,
        "cancel": True,
    }
    assert payload["effective_actions"] == {
        "approve": False,
        "reject": True,
        "cancel": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("client_order_id", "not-a-uuid", "broker_order_catalog_client_order_id_invalid"),
        ("status", "UNKNOWN", "broker_order_catalog_status_invalid"),
        ("quantity", "NaN", "broker_order_catalog_quantity_invalid"),
        ("created_at", "2026-08-13T09:00:00", "broker_order_catalog_created_at_invalid"),
    ],
)
def test_invalid_typed_fields_fail_closed_without_raw_passthrough(
    field: str,
    value: object,
    blocker: str,
) -> None:
    raw = _order()
    raw[field] = value
    raw["untyped_payload"] = {"token": "must-not-cross"}

    payload = _payload(raw)

    assert blocker in payload["blocker_codes"]
    assert payload["effective_actions"] == {
        "approve": False,
        "reject": False,
        "cancel": False,
    }
    assert "must-not-cross" not in str(payload)


def test_invalid_or_unbounded_risk_json_never_crosses_the_catalog_boundary() -> None:
    raw = _order()
    raw["risk_snapshot"] = {"value": float("nan"), "secret": "raw"}
    raw["failure_message"] = "x" * 1001

    payload = _payload(raw)

    assert payload["risk_snapshot_content_hash"] is None
    assert "broker_order_catalog_risk_snapshot_invalid" in payload["blocker_codes"]
    assert "raw" not in str(payload)


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        (
            {"updated_at": (NOW + timedelta(seconds=1)).isoformat()},
            "broker_order_catalog_time_order_invalid",
        ),
        (
            {"submitted_at": (NOW - timedelta(minutes=3)).isoformat()},
            "broker_order_catalog_submitted_at_invalid",
        ),
        (
            {"expires_at": (NOW - timedelta(minutes=3)).isoformat()},
            "broker_order_catalog_expires_at_invalid",
        ),
        ({"filled_quantity": "101"}, "broker_order_catalog_filled_quantity_invalid"),
        ({"version": 0}, "broker_order_catalog_version_invalid"),
    ],
)
def test_catalog_enforces_time_quantity_and_version_invariants(
    changes: dict[str, object],
    blocker: str,
) -> None:
    raw = _order()
    raw.update(changes)

    payload = _payload(raw)

    assert blocker in payload["blocker_codes"]
    assert not any(cast(dict[str, bool], payload["effective_actions"]).values())


def test_catalog_requires_one_trusted_aware_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        project_broker_order_catalog_item(
            _order(),
            evaluated_at=NOW.replace(tzinfo=None),
            actor_authorization={"approve": True, "reject": True, "cancel": True},
        )


def test_query_service_caches_access_by_account_and_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    access_checks: list[tuple[int, str]] = []
    clock_calls = 0

    def has_account_access(**payload: Any) -> bool:
        access_checks.append((int(payload["account_id"]), str(payload["action"])))
        return payload["action"] != "cancel"

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return NOW

    repository = cast(
        BrokerExecutionRepositoryProtocol,
        SimpleNamespace(
            list_orders=lambda **_payload: [_order(suffix=1), _order(suffix=2)],
            has_account_access=has_account_access,
        ),
    )
    service = BrokerExecutionQueryService(repository, clock=clock)

    result = service.orders(actor=object())

    assert clock_calls == 1
    assert access_checks == [(7, "approve"), (7, "reject"), (7, "cancel")]
    assert result["evaluated_at"] == NOW.isoformat()
    assert result["permission"] == "display_only"
    assert result["must_not_execute"] is True
    assert len(result["orders"]) == 2
    assert all(
        row["effective_actions"] == {"approve": False, "reject": True, "cancel": False}
        for row in result["orders"]
    )


def test_query_rejects_unknown_status_before_repository_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        query_services,
        "require_action",
        lambda _actor, _action: (7, "owner", False),
    )

    def fail_list_orders(**_payload: Any) -> list[dict[str, object]]:
        raise AssertionError("repository must not be called")

    repository = cast(
        BrokerExecutionRepositoryProtocol,
        SimpleNamespace(list_orders=fail_list_orders),
    )
    service = BrokerExecutionQueryService(repository)

    with pytest.raises(BrokerExecutionValidationError, match="status"):
        service.orders(actor=object(), status="UNKNOWN")
