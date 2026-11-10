"""Read exact simulated holdings and published financial facts for disclosure review."""

from __future__ import annotations

from apps.data_center.application import public as data_center_public
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    RebalanceResourceSnapshotReader,
)


class DjangoOwnedHoldingDisclosureReader:
    """Authorize an active owner/observer scope and check one positive held balance."""

    def __init__(
        self,
        *,
        account_scope_reader: PortfolioRiskResourceSnapshotReaderProtocol,
        positions_reader: RebalanceResourceSnapshotReader,
    ) -> None:
        """Inject the existing read-scope and locked-position readers."""

        self._account_scope_reader = account_scope_reader
        self._positions_reader = positions_reader

    def has_readable_active_holding(
        self, *, actor_user_id: int, account_id: int, asset_code: str
    ) -> bool:
        """Return false uniformly for inaccessible accounts and absent securities."""

        scope = self._account_scope_reader.read_account_scope(
            user_id=actor_user_id,
            account_id=account_id,
        )
        if scope is None or not scope.can_read:
            return False
        snapshot = self._positions_reader.read_account_snapshot(
            account_id=account_id,
            user_id=scope.owner_user_id,
        )
        if snapshot is None or snapshot.owner_user_id != scope.owner_user_id:
            return False
        return any(
            balance.asset_code == asset_code and balance.quantity > 0
            for balance in snapshot.exact_position_balances
        )


class PublishedFinancialFactsReader:
    """Call Data Center's public current-publication financial fact port."""

    def read_published_financial_facts(
        self, asset_code: str, *, limit: int, publication_key: str
    ) -> dict[str, object]:
        """Read published facts without provider refresh or ingestion side effects."""

        return data_center_public.get_published_financial_facts(
            asset_code,
            limit=limit,
            publication_key=publication_key,
        )


__all__: tuple[str, ...] = (
    "DjangoOwnedHoldingDisclosureReader",
    "PublishedFinancialFactsReader",
)
