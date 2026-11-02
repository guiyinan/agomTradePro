"""Validate a stop-loss audit against its exact still-locked execution intent."""

from __future__ import annotations

from datetime import datetime

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.close_snapshot_execution_market_audit import (
    CloseSnapshotExecutionMarketAuditV1,
)
from apps.simulated_trading.domain.execution_current_reference import (
    LocalSimulatedExecutionMarketAuditV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent


def validate_locked_execution_market_audit(
    market_audit: LocalSimulatedExecutionMarketAuditV1 | CloseSnapshotExecutionMarketAuditV1,
    *,
    intent: SimulatedTradeIntent,
    now: datetime,
) -> None:
    """Reject any changed audit identity, source price or locked evaluation clock."""

    if type(market_audit) not in (
        LocalSimulatedExecutionMarketAuditV1,
        CloseSnapshotExecutionMarketAuditV1,
    ):
        raise SimulatedTradeExecutionBlocked(
            "automatic stop-loss Risk guard returned an invalid audit"
        )
    market_audit.__post_init__()
    if (
        market_audit.account_id != intent.account_id
        or market_audit.user_id != intent.user_id
        or market_audit.idempotency_key != intent.idempotency_key
        or market_audit.request_payload_hash != intent.request_payload_hash
        or market_audit.security_id != intent.security_id
        or market_audit.asset_code != intent.asset_code
        or market_audit.execution_price != intent.price
        or (
            market_audit.close_evaluated_at
            if isinstance(market_audit, CloseSnapshotExecutionMarketAuditV1)
            else market_audit.risk_evaluated_at
        )
        != now
    ):
        raise SimulatedTradeExecutionBlocked(
            "automatic stop-loss Risk audit differs from the exact locked intent",
            code="AUTO_STOP_LOSS_MARKET_AUDIT_MISMATCH",
        )
