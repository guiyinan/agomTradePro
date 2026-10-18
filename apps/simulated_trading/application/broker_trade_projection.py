"""Public Application boundary for factual broker trade projections."""

from __future__ import annotations

from collections.abc import Mapping

from apps.account.application.broker_trade_projection_contracts import (
    BrokerActualFact,
    BrokerLegacyPositionSeed,
    BrokerPositionExpectation,
    BrokerPositionMapState,
    BrokerProjectionAction,
    BrokerTradeProjectionCommand,
    BrokerTradeProjectionRepository,
    BrokerTradeProjectionResult,
    BrokerUnifiedPositionSnapshot,
)
from apps.account.application.broker_trade_projection_errors import BrokerTradeProjectionConflict


class BrokerTradeProjectionService:
    """Public Application service for non-order broker balance projections."""

    def __init__(self, repository: BrokerTradeProjectionRepository) -> None:
        """Inject the projection repository used by this Application service."""

        self._repository = repository

    def get_existing_real_account_id(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
    ) -> int | None:
        """Return an already mapped owner-scoped real account without ensuring one."""

        return self._repository.get_existing_real_account_id(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
        )

    def capture_position_snapshots(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        portfolio_name: str,
        asset_codes: tuple[str, ...],
        legacy_position_ids: Mapping[str, int | None],
    ) -> tuple[BrokerUnifiedPositionSnapshot, ...]:
        """Read exact Sim ledger identity and balance state for an asset set."""

        return self._repository.capture_position_snapshots(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            asset_codes=asset_codes,
            legacy_position_ids=legacy_position_ids,
        )

    def apply_actual_broker_fact(
        self,
        command: BrokerTradeProjectionCommand,
    ) -> BrokerTradeProjectionResult:
        """Apply a broker execution independently of simulated order gates."""

        return self._repository.apply_actual_broker_fact(command)

    def bind_legacy_position_source(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        source_position_id: int,
        unified_position_id: int,
    ) -> bool:
        """Record exact source identity after a new legacy-facing position is created."""

        return self._repository.bind_legacy_position_source(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            source_position_id=source_position_id,
            unified_position_id=unified_position_id,
        )


__all__ = [
    "BrokerActualFact",
    "BrokerLegacyPositionSeed",
    "BrokerPositionExpectation",
    "BrokerPositionMapState",
    "BrokerProjectionAction",
    "BrokerTradeProjectionCommand",
    "BrokerTradeProjectionConflict",
    "BrokerTradeProjectionRepository",
    "BrokerTradeProjectionResult",
    "BrokerUnifiedPositionSnapshot",
    "BrokerTradeProjectionService",
]
