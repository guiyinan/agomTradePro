"""Pure tests for the typed, fail-closed broker order-detail projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.broker_execution.application.order_detail_evidence import (
    project_broker_order_detail,
)
from apps.broker_execution.domain.services import (
    approval_digest_for_order,
    approval_snapshot_for_order,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)
AUTHORIZATION = {"approve": True, "reject": True, "cancel": False}


def _order() -> dict[str, object]:
    order: dict[str, object] = {
        "client_order_id": "00000000-0000-0000-0000-000000000001",
        "account_id": 7,
        "agent_id": "agent-7",
        "asset_code": "510300.SH",
        "market": "CN",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": "100.0000",
        "limit_price": "3.9000",
        "estimated_amount": "390.00",
        "status": "READY",
        "source_recommendation_ids": ["recommendation-1"],
        "source_signal_ids": ["signal-1"],
        "risk_policy_version": "risk-v1",
        "risk_snapshot": {"passed": True, "violations": []},
        "approval_mode": "manual",
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "action_availability": {"approve": False, "reject": False, "cancel": True},
        "events": [
            {
                "event_id": "event-1",
                "event_type": "accepted",
                "status": "SUBMITTED",
                "payload": {"untyped_secret": "must-not-cross-boundary"},
                "occurred_at": NOW.isoformat(),
                "received_at": NOW.isoformat(),
            }
        ],
        "fills": [],
    }
    order["approval_digest"] = approval_digest_for_order(order)
    return order


def _rebind(order: dict[str, object]) -> dict[str, object]:
    rebound = deepcopy(order)
    rebound["approval_digest"] = approval_digest_for_order(rebound)
    return rebound


def _payload(order: dict[str, object]) -> dict[str, object]:
    return project_broker_order_detail(
        order,
        evaluated_at=NOW,
        actor_authorization=AUTHORIZATION,
    ).to_payload()


def test_order_detail_reuses_the_exact_domain_approval_content_hash() -> None:
    order = _order()
    snapshot = approval_snapshot_for_order(order)

    payload = _payload(order)
    evidence = payload["approval_evidence"]

    assert snapshot.quantity == Decimal("100.0000")
    assert payload["approval_evidence_status"] == "display_only"
    assert isinstance(evidence, dict)
    assert evidence["output_content_hash"] == order["approval_digest"]
    assert evidence["output_artifact_type"] == "order_approval_snapshot"
    assert evidence["permission"] == "display_only"
    assert evidence["must_not_use_for_decision"] is True
    assert evidence["must_not_execute"] is True
    assert payload["permission"] == "display_only"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True


def test_lifecycle_transitions_are_distinct_from_actor_authorization() -> None:
    payload = _payload(_order())

    assert "action_availability" not in payload
    assert payload["lifecycle_transitions"] == {
        "approve": False,
        "reject": False,
        "cancel": True,
    }
    assert payload["actor_authorization"] == AUTHORIZATION


def test_untyped_event_payload_is_removed_by_an_explicit_allowlist() -> None:
    payload = _payload(_order())

    assert payload["event_payload_policy"] == "omitted_untyped"
    assert payload["transport_blocker_codes"] == []
    assert payload["events"] == [
        {
            "event_id": "event-1",
            "event_type": "accepted",
            "status": "SUBMITTED",
            "occurred_at": NOW.isoformat(),
            "received_at": NOW.isoformat(),
        }
    ]
    assert "untyped_secret" not in str(payload)


def test_raw_risk_snapshot_is_replaced_by_a_content_bound_hash() -> None:
    payload = _payload(_order())

    assert "risk_snapshot" not in payload
    assert payload["risk_snapshot_policy"] == "content_hash_only"
    assert isinstance(payload["risk_snapshot_content_hash"], str)
    assert len(payload["risk_snapshot_content_hash"]) == 64


@pytest.mark.parametrize(
    ("approval_digest", "blocker"),
    [
        ("", "broker_order_approval_missing"),
        ("A" * 64, "broker_order_approval_digest_invalid"),
        ("0" * 63, "broker_order_approval_digest_invalid"),
    ],
)
def test_order_detail_rejects_missing_or_malformed_digest(
    approval_digest: str,
    blocker: str,
) -> None:
    order = _order()
    order["approval_digest"] = approval_digest

    payload = _payload(order)

    assert payload["approval_evidence_status"] == "blocked"
    assert payload["approval_evidence_blocker_codes"] == [blocker]
    assert payload["approval_evidence"] is None
    assert payload["must_not_execute"] is True


def test_order_detail_detects_any_post_approval_content_change() -> None:
    order = _order()
    order["quantity"] = "200.0000"

    payload = _payload(order)

    assert payload["approval_evidence_blocker_codes"] == ["broker_order_approval_digest_mismatch"]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("expires_at", NOW.isoformat()),
        ("estimated_amount", "389.99"),
        ("source_recommendation_ids", []),
        ("source_recommendation_ids", ["recommendation-1", "recommendation-1"]),
        ("agent_id", ""),
        ("risk_policy_version", ""),
        ("risk_snapshot", {}),
        ("quantity", "NaN"),
        ("limit_price", "Infinity"),
    ],
)
def test_exact_digest_still_blocks_unverifiable_legacy_projection(
    field_name: str,
    value: object,
) -> None:
    order = _order()
    order[field_name] = value
    rebound = _rebind(order)

    payload = _payload(rebound)

    assert payload["approval_evidence_status"] == "blocked"
    assert payload["approval_evidence_blocker_codes"] == ["broker_order_approval_evidence_invalid"]
    assert payload["approval_evidence"] is None
    assert payload["permission"] == "display_only"
    assert payload["must_not_use_for_decision"] is True
    assert payload["must_not_execute"] is True


@pytest.mark.parametrize(
    "field_name",
    ["account_id", "asset_code", "side", "order_type", "quantity", "estimated_amount"],
)
def test_malformed_snapshot_fields_return_a_stable_blocker(field_name: str) -> None:
    order = _order()
    order.pop(field_name)

    payload = _payload(order)

    assert payload["approval_evidence_blocker_codes"] == ["broker_order_approval_snapshot_invalid"]
    assert payload["must_not_execute"] is True


def test_malformed_timeline_rows_are_flagged_without_exposing_raw_payload() -> None:
    order = _order()
    order["events"] = ["invalid-row"]
    order["fills"] = {"unexpected": True}

    payload = _payload(order)

    assert payload["events"] == []
    assert payload["fills"] == []
    assert payload["transport_blocker_codes"] == [
        "broker_order_events_invalid",
        "broker_order_fills_invalid",
    ]


def test_order_detail_requires_a_trusted_aware_evaluation_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        project_broker_order_detail(
            order=_order(),
            evaluated_at=NOW.replace(tzinfo=None),
            actor_authorization=AUTHORIZATION,
        )
