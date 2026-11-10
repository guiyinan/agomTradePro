"""Public-facade and owner/observer adapter tests without database access."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.data_center.application import public as data_center_public
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskAccountScope,
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    RebalanceResourceSnapshot,
    RebalanceResourceSnapshotReader,
)
from apps.simulated_trading.infrastructure.holding_disclosure_reader import (
    DjangoOwnedHoldingDisclosureReader,
    PublishedFinancialFactsReader,
)


class _ObserverScopeReader:
    """Return an observer's existing account read grant and retain the query."""

    def __init__(self, scope: PortfolioRiskAccountScope | None) -> None:
        self.scope = scope
        self.calls: list[tuple[int, int]] = []

    def read_account_scope(
        self, *, user_id: int, account_id: int
    ) -> PortfolioRiskAccountScope | None:
        self.calls.append((user_id, account_id))
        return self.scope


class _SnapshotReader:
    """Return a tiny test projection carrying only adapter-consumed fields."""

    def __init__(self, snapshot: RebalanceResourceSnapshot | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[int, int]] = []

    def read_account_snapshot(
        self, *, account_id: int, user_id: int
    ) -> RebalanceResourceSnapshot | None:
        self.calls.append((account_id, user_id))
        return self.snapshot


def test_public_financial_reader_uses_module_qualified_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered adapter remains patchable at Data Center's public port."""

    calls: list[tuple[str, int, str]] = []
    payload: dict[str, object] = {"rows": [], "publication_id": "p1"}

    def read(
        asset_code: str,
        *,
        limit: int,
        publication_key: str,
    ) -> dict[str, object]:
        calls.append((asset_code, limit, publication_key))
        return payload

    monkeypatch.setattr(data_center_public, "get_published_financial_facts", read)

    result = PublishedFinancialFactsReader().read_published_financial_facts(
        "600000.SH",
        limit=20,
        publication_key="current",
    )

    assert result is payload
    assert calls == [("600000.SH", 20, "current")]


def test_observer_scope_reads_snapshot_as_owner_and_matches_exact_security() -> None:
    """A valid observer grant is checked before using the owner's exact positions."""

    scope = PortfolioRiskAccountScope(owner_user_id=23, can_read=True, can_write=False)
    scope_reader = _ObserverScopeReader(scope)
    snapshot = cast(
        RebalanceResourceSnapshot,
        SimpleNamespace(
            owner_user_id=23,
            exact_position_balances=(
                SimpleNamespace(asset_code="600000.SH", quantity=Decimal("2")),
                SimpleNamespace(asset_code="000001.SZ", quantity=Decimal("9")),
            ),
        ),
    )
    positions_reader = _SnapshotReader(snapshot)
    reader = DjangoOwnedHoldingDisclosureReader(
        account_scope_reader=cast(PortfolioRiskResourceSnapshotReaderProtocol, scope_reader),
        positions_reader=cast(RebalanceResourceSnapshotReader, positions_reader),
    )

    result = reader.has_readable_active_holding(
        actor_user_id=9,
        account_id=17,
        asset_code="600000.SH",
    )

    assert result is True
    assert scope_reader.calls == [(9, 17)]
    assert positions_reader.calls == [(17, 23)]


def test_missing_account_scope_does_not_read_positions() -> None:
    """A foreign, missing, or inactive scope fails before position lookup."""

    scope_reader = _ObserverScopeReader(None)
    positions_reader = _SnapshotReader(None)
    reader = DjangoOwnedHoldingDisclosureReader(
        account_scope_reader=cast(PortfolioRiskResourceSnapshotReaderProtocol, scope_reader),
        positions_reader=cast(RebalanceResourceSnapshotReader, positions_reader),
    )

    result = reader.has_readable_active_holding(
        actor_user_id=9,
        account_id=17,
        asset_code="600000.SH",
    )

    assert result is False
    assert scope_reader.calls == [(9, 17)]
    assert positions_reader.calls == []
