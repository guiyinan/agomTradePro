"""Research app-root adapter for legacy Broker approval Evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Final, cast

from apps.research.application.broker_execution_evidence_adapter import (
    LegacyBrokerApprovalProjection,
    build_broker_approval_projection_legacy_evidence_summary,
)

_REQUEST_FIELDS: Final = frozenset(
    {
        "account_id",
        "agent_id",
        "asset_code",
        "market",
        "side",
        "order_type",
        "quantity",
        "limit_price",
        "estimated_amount",
        "expires_at",
        "risk_policy_version",
        "risk_snapshot_json",
        "approval_mode",
        "source_recommendation_ids",
        "source_signal_ids",
        "evaluated_at",
    }
)


def project_legacy_broker_approval_evidence(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Translate one closed Broker payload into a legacy Evidence summary."""

    if type(payload) is not dict or set(payload) != _REQUEST_FIELDS:
        raise ValueError("legacy Broker approval Evidence payload is not closed")
    projection = LegacyBrokerApprovalProjection(
        account_id=cast(int, payload["account_id"]),
        agent_id=cast(str, payload["agent_id"]),
        asset_code=cast(str, payload["asset_code"]),
        market=cast(str, payload["market"]),
        side=cast(str, payload["side"]),
        order_type=cast(str, payload["order_type"]),
        quantity=cast(Decimal, payload["quantity"]),
        limit_price=cast(Decimal | None, payload["limit_price"]),
        estimated_amount=cast(Decimal, payload["estimated_amount"]),
        expires_at=cast(str, payload["expires_at"]),
        risk_policy_version=cast(str, payload["risk_policy_version"]),
        risk_snapshot_json=cast(str, payload["risk_snapshot_json"]),
        approval_mode=cast(str, payload["approval_mode"]),
        source_recommendation_ids=cast(tuple[str, ...], payload["source_recommendation_ids"]),
        source_signal_ids=cast(tuple[str, ...], payload["source_signal_ids"]),
    )
    summary = build_broker_approval_projection_legacy_evidence_summary(
        projection,
        evaluated_at=cast(datetime, payload["evaluated_at"]),
    )
    return {
        "output_owner": summary.output_owner,
        "output_artifact_type": summary.output_artifact_type,
        "output_artifact_id": summary.output_artifact_id,
        "output_artifact_version": summary.output_artifact_version,
        "output_content_hash": summary.output_content_hash,
        "envelope_content_hash": summary.envelope_content_hash,
        "operator_spec_content_hash": summary.operator_spec_content_hash,
        "claim_kind": summary.claim_kind,
        "method_kind": summary.method_kind,
        "research_family": summary.research_family,
        "governance_state": summary.governance_state,
        "permission": summary.permission,
        "blocker_codes": list(summary.blocker_codes),
        "dependency_flags": list(summary.dependency_flags),
        "track_record_availability": summary.track_record_availability,
        "track_record_content_hash": summary.track_record_content_hash,
        "n_eff": summary.n_eff,
        "coverage": summary.coverage,
        "evaluated_at": summary.evaluated_at.isoformat(),
        "valid_until": summary.valid_until.isoformat(),
        "must_not_use_for_decision": summary.must_not_use_for_decision,
        "must_not_execute": summary.must_not_execute,
    }


__all__ = ["project_legacy_broker_approval_evidence"]
