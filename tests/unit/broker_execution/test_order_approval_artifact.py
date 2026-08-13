"""Pure coverage for the Broker-owned order approval artifact."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest

from apps.broker_execution.application.evidence_gate import broker_order_evidence_integrated
from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.broker_execution.domain.order_approval_artifact import (
    BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA,
    BrokerOrderApprovalActor,
    BrokerOrderApprovalArtifact,
)
from apps.broker_execution.domain.rules import build_approval_digest

ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"
APPROVED_AT = datetime(2026, 8, 13, 2, tzinfo=UTC)
VALID_UNTIL = APPROVED_AT + timedelta(hours=1)


def _snapshot(**changes: object) -> OrderApprovalSnapshot:
    values: dict[str, object] = {
        "account_id": 7,
        "agent_id": "agent:primary",
        "asset_code": "600000.SH",
        "market": "CN",
        "side": LiveOrderSide.BUY,
        "order_type": LiveOrderType.LIMIT,
        "quantity": Decimal("100.0000"),
        "limit_price": Decimal("10.2500"),
        "estimated_amount": Decimal("1025.00"),
        "expires_at": VALID_UNTIL.isoformat(),
        "risk_policy_version": "risk-policy-v1",
        "risk_snapshot_json": '{"cash":"10000.00","max_position":"0.10"}',
        "approval_mode": "manual",
        "source_recommendation_ids": ("recommendation-1",),
        "source_signal_ids": ("signal-1",),
    }
    values.update(changes)
    return OrderApprovalSnapshot(**values)  # type: ignore[arg-type]


def _artifact(**changes: object) -> BrokerOrderApprovalArtifact:
    snapshot = changes.pop("approval_snapshot", _snapshot())
    assert isinstance(snapshot, OrderApprovalSnapshot)
    values: dict[str, object] = {
        "artifact_id": ORDER_ID,
        "artifact_version": f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.3",
        "client_order_id": ORDER_ID,
        "account_id": 7,
        "order_version": 3,
        "approval_snapshot": snapshot,
        "approval_digest": build_approval_digest(snapshot),
        "approved_by": BrokerOrderApprovalActor(
            actor_id="user:19", user_id=19, role="broker_approver"
        ),
        "approved_at": APPROVED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return BrokerOrderApprovalArtifact(**values)  # type: ignore[arg-type]


def test_artifact_seals_exact_snapshot_but_never_activates_execution() -> None:
    artifact = _artifact()

    assert artifact.artifact_id == artifact.client_order_id
    assert artifact.approval_digest == build_approval_digest(artifact.approval_snapshot)
    assert len(artifact.identity_hash) == 64
    assert len(artifact.content_hash) == 64
    assert artifact.activation_available is False
    assert artifact.must_not_execute is True
    assert artifact.to_payload()["must_not_execute"] is True
    assert broker_order_evidence_integrated() is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, agent_id="agent:backup"),
        lambda value: replace(value, asset_code="000001.SZ"),
        lambda value: replace(value, market="HK"),
        lambda value: replace(value, side=LiveOrderSide.SELL),
        lambda value: replace(
            value, quantity=Decimal("101.0000"), estimated_amount=Decimal("1035.25")
        ),
        lambda value: replace(
            value, limit_price=Decimal("10.2600"), estimated_amount=Decimal("1026.00")
        ),
        lambda value: replace(value, expires_at=(VALID_UNTIL + timedelta(minutes=1)).isoformat()),
        lambda value: replace(value, risk_policy_version="risk-policy-v2"),
        lambda value: replace(value, risk_snapshot_json='{"cash":"9999.00"}'),
        lambda value: replace(value, approval_mode="four-eyes"),
        lambda value: replace(value, source_recommendation_ids=("recommendation-2",)),
        lambda value: replace(value, source_signal_ids=("signal-2",)),
    ],
)
def test_every_snapshot_field_drift_changes_digest_and_artifact_hash(
    mutation: Callable[[OrderApprovalSnapshot], OrderApprovalSnapshot],
) -> None:
    original = _artifact()
    changed_snapshot = mutation(original.approval_snapshot)
    changed = _artifact(
        approval_snapshot=changed_snapshot,
        approval_digest=build_approval_digest(changed_snapshot),
        valid_until=datetime.fromisoformat(changed_snapshot.expires_at),
    )

    assert changed.approval_digest != original.approval_digest
    assert changed.content_hash != original.content_hash


def test_uuid_identity_and_order_version_are_exactly_bound() -> None:
    with pytest.raises(ValueError, match="canonical UUID"):
        _artifact(client_order_id=ORDER_ID.upper())
    with pytest.raises(ValueError, match="artifact_id"):
        _artifact(artifact_id="b35c7b8d-3f91-4708-8e50-ed353cf54da1")
    with pytest.raises(ValueError, match="positive integer"):
        _artifact(order_version=True)
    with pytest.raises(ValueError, match="order_version"):
        _artifact(artifact_version=f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.2")
    assert (
        _artifact(
            order_version=4, artifact_version=f"{BROKER_ORDER_APPROVAL_ARTIFACT_SCHEMA}.4"
        ).content_hash
        != _artifact().content_hash
    )


@pytest.mark.parametrize(
    "field_name",
    ["quantity", "limit_price", "estimated_amount"],
)
def test_non_finite_or_invalid_decimal_snapshot_values_fail_closed(field_name: str) -> None:
    with pytest.raises(ValueError, match="finite Decimal|invalid sign"):
        _artifact(approval_snapshot=_snapshot(**{field_name: Decimal("NaN")}))
    with pytest.raises(ValueError, match="invalid sign"):
        _artifact(approval_snapshot=_snapshot(**{field_name: Decimal("-1")}))


def test_snapshot_amount_and_recommendation_lineage_fail_closed() -> None:
    with pytest.raises(ValueError, match=r"quantity \* limit_price"):
        _artifact(approval_snapshot=_snapshot(estimated_amount=Decimal("1024.99")))
    with pytest.raises(ValueError, match="must not be empty"):
        _artifact(approval_snapshot=_snapshot(source_recommendation_ids=()))


def test_expiry_requires_exact_aware_snapshot_clock_and_valid_window() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _artifact(
            approval_snapshot=_snapshot(expires_at="2026-08-13T03:00:00"),
            valid_until=datetime(2026, 8, 13, 3),
        )
    with pytest.raises(ValueError, match="exactly equal"):
        _artifact(valid_until=VALID_UNTIL + timedelta(seconds=1))
    with pytest.raises(ValueError, match="validity window"):
        _artifact(approved_at=VALID_UNTIL)


def test_actor_digest_and_seal_tamper_fail_closed() -> None:
    with pytest.raises(ValueError, match="user_id"):
        BrokerOrderApprovalActor(actor_id="user:19", user_id=True, role="approver")
    with pytest.raises(ValueError, match="approval_digest"):
        _artifact(approval_digest="b" * 64)
    with pytest.raises(ValueError, match="identity_hash"):
        _artifact(identity_hash="b" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _artifact(content_hash="b" * 64)
    assert (
        replace(
            _artifact(),
            approved_by=BrokerOrderApprovalActor("user:20", 20, "broker_approver"),
            identity_hash="",
            content_hash="",
        ).content_hash
        != _artifact().content_hash
    )


def test_domain_contract_has_no_cross_app_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "broker_execution"
        / "domain"
        / "order_approval_artifact.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("apps.") for module in imported_modules)
