"""Tests for the fail-closed legacy broker approval snapshot adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.research.application.broker_execution_evidence_adapter import (
    LegacyBrokerApprovalProjection,
    build_broker_approval_projection_legacy_evidence_summary,
)
from apps.research.application.evidence_summary import EvidenceSummaryDTO
from apps.research.broker_execution_evidence_composition import (
    project_legacy_broker_approval_evidence,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


def _snapshot() -> OrderApprovalSnapshot:
    return OrderApprovalSnapshot(
        account_id=7,
        agent_id="agent-1",
        asset_code="510300.SH",
        market="CN",
        side=LiveOrderSide.BUY,
        order_type=LiveOrderType.LIMIT,
        quantity=Decimal("100"),
        limit_price=Decimal("3.9000"),
        estimated_amount=Decimal("390.00"),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
        risk_policy_version="risk-v1",
        risk_snapshot_json='{"passed":true,"violations":[]}',
        approval_mode="manual",
        source_recommendation_ids=("recommendation-1",),
        source_signal_ids=("signal-1",),
    )


def _summary(snapshot: OrderApprovalSnapshot, *, evaluated_at: datetime) -> EvidenceSummaryDTO:
    return build_broker_approval_projection_legacy_evidence_summary(
        LegacyBrokerApprovalProjection(
            account_id=snapshot.account_id,
            agent_id=snapshot.agent_id,
            asset_code=snapshot.asset_code,
            market=snapshot.market,
            side=snapshot.side.value,
            order_type=snapshot.order_type.value,
            quantity=snapshot.quantity,
            limit_price=snapshot.limit_price,
            estimated_amount=snapshot.estimated_amount,
            expires_at=snapshot.expires_at,
            risk_policy_version=snapshot.risk_policy_version,
            risk_snapshot_json=snapshot.risk_snapshot_json,
            approval_mode=snapshot.approval_mode,
            source_recommendation_ids=snapshot.source_recommendation_ids,
            source_signal_ids=snapshot.source_signal_ids,
        ),
        evaluated_at=evaluated_at,
    )


def _composition_payload(snapshot: OrderApprovalSnapshot) -> dict[str, object]:
    return {
        "account_id": snapshot.account_id,
        "agent_id": snapshot.agent_id,
        "asset_code": snapshot.asset_code,
        "market": snapshot.market,
        "side": snapshot.side.value,
        "order_type": snapshot.order_type.value,
        "quantity": snapshot.quantity,
        "limit_price": snapshot.limit_price,
        "estimated_amount": snapshot.estimated_amount,
        "expires_at": snapshot.expires_at,
        "risk_policy_version": snapshot.risk_policy_version,
        "risk_snapshot_json": snapshot.risk_snapshot_json,
        "approval_mode": snapshot.approval_mode,
        "source_recommendation_ids": snapshot.source_recommendation_ids,
        "source_signal_ids": snapshot.source_signal_ids,
        "evaluated_at": NOW,
    }


def test_approval_snapshot_adapter_is_content_bound_and_fail_closed() -> None:
    first = _summary(_snapshot(), evaluated_at=NOW)
    changed = _summary(
        replace(
            _snapshot(),
            quantity=Decimal("200"),
            estimated_amount=Decimal("780.00"),
        ),
        evaluated_at=NOW,
    )

    assert first.output_owner == "broker_execution"
    assert first.output_artifact_type == "order_approval_snapshot"
    assert first.output_artifact_id == first.output_content_hash
    assert first.output_artifact_version == "approval-snapshot-v1"
    assert first.claim_kind == "derived"
    assert first.method_kind == "deterministic"
    assert first.research_family == "legacy"
    assert first.governance_state == "research_only"
    assert first.permission == "display_only"
    assert first.blocker_codes == ("evidence.legacy_unverified",)
    assert first.must_not_use_for_decision is True
    assert first.must_not_execute is True
    assert first.output_content_hash != changed.output_content_hash
    assert first.envelope_content_hash != changed.envelope_content_hash


def test_approval_snapshot_adapter_rejects_unverifiable_inputs() -> None:
    snapshots = (
        replace(_snapshot(), quantity=Decimal("NaN")),
        replace(_snapshot(), limit_price=Decimal("Infinity")),
        replace(_snapshot(), estimated_amount=Decimal("389.99")),
        replace(_snapshot(), risk_snapshot_json='{"violations":[],"passed":true}'),
        replace(_snapshot(), risk_snapshot_json='{"passed":NaN,"violations":[]}'),
        replace(_snapshot(), source_recommendation_ids=()),
        replace(
            _snapshot(),
            source_recommendation_ids=("recommendation-2", "recommendation-1"),
        ),
        replace(_snapshot(), expires_at=NOW.isoformat()),
        replace(
            _snapshot(), expires_at=(NOW + timedelta(hours=1)).replace(tzinfo=None).isoformat()
        ),
    )
    for snapshot in snapshots:
        with pytest.raises((TypeError, ValueError)):
            _summary(snapshot, evaluated_at=NOW)


def test_approval_snapshot_adapter_rejects_naive_evaluation_clock() -> None:
    with pytest.raises(ValueError, match="evaluated_at"):
        _summary(_snapshot(), evaluated_at=NOW.replace(tzinfo=None))


def test_research_app_root_projects_the_closed_registry_payload() -> None:
    result = project_legacy_broker_approval_evidence(_composition_payload(_snapshot()))

    assert result["output_owner"] == "broker_execution"
    assert result["permission"] == "display_only"
    assert result["blocker_codes"] == ["evidence.legacy_unverified"]
    assert result["evaluated_at"] == NOW.isoformat()
    assert result["must_not_use_for_decision"] is True
    assert result["must_not_execute"] is True


def test_research_app_root_rejects_open_or_substituted_payloads() -> None:
    open_payload = _composition_payload(_snapshot())
    open_payload["unexpected"] = "must-not-cross-boundary"

    with pytest.raises(ValueError, match="not closed"):
        project_legacy_broker_approval_evidence(open_payload)

    substituted = _composition_payload(_snapshot())
    substituted["account_id"] = True
    with pytest.raises(ValueError, match="account_id"):
        project_legacy_broker_approval_evidence(substituted)
