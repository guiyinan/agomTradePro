"""Reuse canonical account read/write grants for every plan operation."""

from __future__ import annotations

from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_journey_public import (
    RebalanceJourneyAccessDenied,
)


class RebalanceJourneyAccountAuthorizer:
    """Check the existing owner/delegated-read scope before accessing plan rows."""

    def __init__(self, reader: PortfolioRiskResourceSnapshotReaderProtocol) -> None:
        """Inject the same account authority reader used by current portfolio risk."""

        self._reader = reader

    def require_read(self, *, actor_user_id: int, account_id: int) -> int:
        """Return the real account owner only when the actor holds read scope."""

        return self._require(actor_user_id=actor_user_id, account_id=account_id, write=False)

    def require_write(self, *, actor_user_id: int, account_id: int) -> int:
        """Require the existing write grant rather than inferring it from visibility."""

        return self._require(actor_user_id=actor_user_id, account_id=account_id, write=True)

    def _require(self, *, actor_user_id: int, account_id: int, write: bool) -> int:
        if any(type(value) is not int or value <= 0 for value in (actor_user_id, account_id)):
            raise RebalanceJourneyAccessDenied()
        scope = self._reader.read_account_scope(user_id=actor_user_id, account_id=account_id)
        if scope is None or not scope.can_read or (write and not scope.can_write):
            raise RebalanceJourneyAccessDenied()
        return scope.owner_user_id
