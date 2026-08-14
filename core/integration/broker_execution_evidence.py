"""Cross-app projection for legacy Broker approval Evidence."""

from __future__ import annotations

from datetime import datetime

from apps.broker_execution.domain.entities import OrderApprovalSnapshot
from apps.research.application.broker_execution_evidence_adapter import (
    LegacyBrokerApprovalProjection,
    build_broker_approval_projection_legacy_evidence_summary,
)
from apps.research.application.evidence_summary import EvidenceSummaryDTO


def build_order_approval_snapshot_legacy_evidence_summary(
    snapshot: OrderApprovalSnapshot, *, evaluated_at: datetime
) -> EvidenceSummaryDTO:
    """Project one exact Broker snapshot without adding an app-to-app dependency."""

    if type(snapshot) is not OrderApprovalSnapshot:
        raise TypeError("snapshot must be an exact OrderApprovalSnapshot")
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


__all__ = ["build_order_approval_snapshot_legacy_evidence_summary"]
