"""Strategy output boundary: targets only, never executable orders."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Protocol

from apps.portfolio.domain.entities import TargetPortfolio, TargetPosition


class TargetWeightStrategy(Protocol):
    """Pure strategy calculation contract."""

    def calculate_targets(self, snapshot_id: str, parameters: dict[str, Any]) -> dict[str, Decimal]:
        """Return desired asset weights for a frozen decision snapshot."""


class BuildTargetPortfolioUseCase:
    """Convert strategy weights into a validated TargetPortfolio value."""

    def __init__(self, strategy: TargetWeightStrategy):
        self._strategy = strategy

    def execute(
        self,
        *,
        decision_snapshot_id: str,
        strategy_version: str,
        parameters: dict[str, Any],
        target_cash_weight: Decimal,
        explanation: str = "",
    ) -> TargetPortfolio:
        if not decision_snapshot_id:
            raise ValueError("strategy requires a frozen decision_snapshot_id")
        weights = self._strategy.calculate_targets(decision_snapshot_id, parameters)
        target = TargetPortfolio(
            target_id=uuid.uuid5(
                uuid.NAMESPACE_URL, f"{decision_snapshot_id}:{strategy_version}:{parameters}"
            ).hex,
            decision_snapshot_id=decision_snapshot_id,
            positions=tuple(
                TargetPosition(asset_code=code, target_weight=weight)
                for code, weight in sorted(weights.items())
            ),
            target_cash_weight=target_cash_weight,
            strategy_version=strategy_version,
            explanation=explanation,
        )
        target.validate()
        return target

