"""Application boundary for close-only Sina snapshot simulation assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from apps.data_center.domain.sina_quote_capture import SinaQuoteCapture
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationBundle,
    CloseSnapshotSimulationDecision,
    CloseSnapshotSimulationEvaluation,
    CloseSnapshotSimulationPolicy,
    evaluate_close_snapshot_order,
    evaluate_close_snapshot_simulation,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import ExecutionOrder
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
)


@dataclass(frozen=True, slots=True)
class CloseSnapshotSimulationInput:
    """Typed source, policy, calendar, rule, and exact request scope for evaluation."""

    capture: SinaQuoteCapture | None
    policy: CloseSnapshotSimulationPolicy | None
    calendar: LocalSimulatedCalendarContext | None
    rule: ExecutionSubmissionRuleV2 | None
    account_id: int
    security_id: str
    asset_code: str
    trading_date: date
    requested_price: Decimal | None
    as_of: datetime


class CloseSnapshotSimulationUseCase:
    """Evaluate a captured close quote without fetching or mutating external state."""

    def evaluate(self, request: CloseSnapshotSimulationInput) -> CloseSnapshotSimulationEvaluation:
        """Return a content-addressed close-snapshot decision and bundle if qualified."""

        return evaluate_close_snapshot_simulation(
            capture=request.capture,
            policy=request.policy,
            calendar=request.calendar,
            rule=request.rule,
            account_id=request.account_id,
            security_id=request.security_id,
            asset_code=request.asset_code,
            trading_date=request.trading_date,
            requested_price=request.requested_price,
            as_of=request.as_of,
        )

    def evaluate_order(
        self,
        *,
        rule: ExecutionSubmissionRuleV2,
        bundle: CloseSnapshotSimulationBundle,
        order: ExecutionOrder,
        as_of: datetime,
    ) -> CloseSnapshotSimulationDecision:
        """Recheck a close bundle and all ordinary rule/lot/position terms for one order."""

        return evaluate_close_snapshot_order(
            rule=rule,
            bundle=bundle,
            order=order,
            as_of=as_of,
        )
