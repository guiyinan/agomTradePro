"""Resolve an authenticated User through Account before reading Strategy content."""

from __future__ import annotations

from apps.account.application.owner_profile_identity import GetAccountOwnerProfileIdentityUseCase
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    StrategyM1RiskSourceReader,
)
from apps.strategy.application.execution_gateway import (
    InspectionSelection,
    StrategyExecutionGateway,
)


class AccountProfileScopedStrategyM1RiskSourceReader(StrategyM1RiskSourceReader):
    """Adapt an authenticated User to Strategy's established Profile ownership scope."""

    def __init__(
        self,
        *,
        owner_profile_identity: GetAccountOwnerProfileIdentityUseCase,
        strategy_gateway: StrategyExecutionGateway,
    ) -> None:
        """Inject Account's public identity use case and Strategy's public query gateway."""

        self._owner_profile_identity = owner_profile_identity
        self._strategy_gateway = strategy_gateway

    def get_owner_inspection_selection(
        self,
        account_id: int,
        owner_user_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """Return an unavailable Strategy source when no real owner Profile maps through."""

        identity = self._owner_profile_identity.execute(user_id=owner_user_id)
        profile_id = identity.profile_id if identity is not None else 0
        return self._strategy_gateway.get_profile_scoped_inspection_selection(
            account_id=account_id,
            owner_profile_id=profile_id,
            strategy_id=strategy_id,
        )


__all__: tuple[str, ...] = ("AccountProfileScopedStrategyM1RiskSourceReader",)
