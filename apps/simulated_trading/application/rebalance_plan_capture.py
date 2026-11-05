"""Capture the typed preview from the existing server-owned inspection producer."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview
from apps.simulated_trading.domain.entities import Position, SimulatedAccount
from apps.simulated_trading.domain.temporary_rebalance_targets import TemporarySecurityTargets
from apps.strategy.application.execution_gateway import StrategySelectionState
from core.exceptions import BusinessLogicError


class CapturingRebalancePlanPreviewBuilder(ReadOnlyRebalancePlanPreviewBuilder):
    """Decorate the existing builder without decoding JSON or rerunning its sources."""

    def __init__(self, delegate: ReadOnlyRebalancePlanPreviewBuilder) -> None:
        """Retain the configured source reader and no account data at construction."""

        self._delegate = delegate
        self._captured: RebalancePlanPreview | None = None

    @property
    def captured(self) -> RebalancePlanPreview:
        """Return only the completed typed result of this exact inspection call."""

        if self._captured is None:
            raise BusinessLogicError(code="REBALANCE_PLAN_PREVIEW_NOT_CAPTURED")
        return self._captured

    def build(
        self,
        *,
        account: SimulatedAccount,
        user_id: int,
        positions: tuple[Position, ...],
        checks: tuple[Mapping[str, object], ...],
        summary: Mapping[str, object],
        strategy_id: int | None,
        position_rule_id: int | None,
        strategy_name: str | None,
        strategy_type: str | None,
        strategy_version: int | None,
        rule_name: str | None,
        max_position_pct: Decimal | None,
        max_total_position_pct: Decimal | None,
        stop_loss_pct: Decimal | None,
        macro_regime: str,
        policy_gear: str,
        as_of: datetime,
        inspection_date: date,
        current_local_date: date,
        strategy_selection_state: StrategySelectionState = "unavailable",
        temporary_targets: TemporarySecurityTargets | None = None,
    ) -> RebalancePlanPreview:
        """Preserve the exact existing source, resource, fee and risk validations."""

        self._captured = None
        result = self._delegate.build(
            account=account,
            user_id=user_id,
            positions=positions,
            checks=checks,
            summary=summary,
            strategy_id=strategy_id,
            position_rule_id=position_rule_id,
            strategy_name=strategy_name,
            strategy_type=strategy_type,
            strategy_version=strategy_version,
            rule_name=rule_name,
            max_position_pct=max_position_pct,
            max_total_position_pct=max_total_position_pct,
            stop_loss_pct=stop_loss_pct,
            macro_regime=macro_regime,
            policy_gear=policy_gear,
            as_of=as_of,
            inspection_date=inspection_date,
            current_local_date=current_local_date,
            strategy_selection_state=strategy_selection_state,
            temporary_targets=temporary_targets,
        )
        if type(result) is not RebalancePlanPreview:
            raise BusinessLogicError(code="REBALANCE_PLAN_PREVIEW_TYPE_INVALID")
        self._captured = result
        return result
