from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_journey_read_consistency import (
    plan_preview_reservation_read_reasons,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
)
from tests.unit.simulated_trading.application import (
    test_rebalance_journey_preparation as preparation_fixtures,
)


def _read_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PreparedPortfolioRisk, RebalancePlanPreview]:
    """Reuse the complete typed preparation fixture and make its SELL row exact."""

    provider, preview = preparation_fixtures._provider(monkeypatch)
    reads = cast(preparation_fixtures._Reads, provider._reads)
    prepared = reads._prepared
    assert len(prepared.snapshot.holdings) == 1
    assert prepared.snapshot.holdings[0].asset_code == preparation_fixtures._ASSET_CODE
    assert prepared.snapshot.holdings[0].security_id == preparation_fixtures._SECURITY_ID
    assert len(prepared.snapshot.active_orders) == 2
    sell_holds = tuple(order for order in prepared.snapshot.active_orders if order.side == "sell")
    assert len(sell_holds) == 1
    assert sell_holds[0].remaining_quantity == Decimal("3")
    assert sell_holds[0].remaining_cash == Decimal("0")
    assert prepared.snapshot.holdings[0].available_quantity == Decimal("90")

    assert len(preview.asset_items) == 1
    original_row = preview.asset_items[0]
    identity = dict(original_row.identity or {})
    identity["security_id"] = preparation_fixtures._SECURITY_ID
    sell_row = replace(
        original_row,
        action="sell",
        identity=identity,
        reserved_sell_quantity=Decimal("3"),
        sellable_quantity=Decimal("87"),
    )
    return prepared, replace(preview, asset_items=(sell_row,))


def _with_bindings(
    prepared: PreparedPortfolioRisk,
    bindings: tuple[PortfolioRiskIdentityBinding, ...],
    *,
    ledger_security_id: str | None,
) -> PreparedPortfolioRisk:
    """Change only ledger identity evidence while preserving exact snapshot facts."""

    holding = replace(prepared.snapshot.holdings[0], security_id=ledger_security_id)
    snapshot = replace(prepared.snapshot, holdings=(holding,))
    return replace(prepared, snapshot=snapshot, identity_bindings=bindings)


def _pinned_binding(*, asset_code: str, source_security_id: str) -> PortfolioRiskIdentityBinding:
    """Build one typed binding that explicitly preserves a missing ledger ID."""

    return PortfolioRiskIdentityBinding(
        asset_code=asset_code,
        ledger_security_id=None,
        source_security_id=source_security_id,
        basis="pinned_policy_source_mapping",
    )


def test_unique_policy_pinned_identity_resolves_missing_ledger_id_without_rewriting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single exact source binding permits comparison while the raw ID stays unknown."""

    prepared, preview = _read_case(monkeypatch)
    asset_code = preparation_fixtures._ASSET_CODE
    security_id = preparation_fixtures._SECURITY_ID
    mapped = _with_bindings(
        prepared,
        (_pinned_binding(asset_code=asset_code, source_security_id=security_id),),
        ledger_security_id=None,
    )

    reasons = plan_preview_reservation_read_reasons(preview, mapped)

    assert reasons == ()
    assert mapped.snapshot.holdings[0].security_id is None
    assert prepared.snapshot.holdings[0].security_id == security_id


@pytest.mark.parametrize(
    "case",
    (
        "missing_binding",
        "duplicate_binding",
        "ambiguous_binding",
        "different_asset",
        "different_source_security",
        "known_ledger_id_conflicts_with_preview",
    ),
)
def test_unproven_or_conflicting_identity_stays_unknown(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Only one exact mapping may resolve a missing ledger security identity."""

    prepared, preview = _read_case(monkeypatch)
    asset_code = preparation_fixtures._ASSET_CODE
    security_id = preparation_fixtures._SECURITY_ID
    other_security_id = "SSE:600519"
    preview_row = preview.asset_items[0]
    preview_identity = dict(preview_row.identity or {})
    ledger_security_id: str | None = None

    if case == "missing_binding":
        bindings: tuple[PortfolioRiskIdentityBinding, ...] = ()
    elif case == "duplicate_binding":
        binding = _pinned_binding(asset_code=asset_code, source_security_id=security_id)
        bindings = (binding, binding)
    elif case == "ambiguous_binding":
        bindings = (
            _pinned_binding(asset_code=asset_code, source_security_id=security_id),
            _pinned_binding(asset_code=asset_code, source_security_id=other_security_id),
        )
    elif case == "different_asset":
        bindings = (_pinned_binding(asset_code="600519.SH", source_security_id=security_id),)
    elif case == "different_source_security":
        bindings = (_pinned_binding(asset_code=asset_code, source_security_id=other_security_id),)
    else:
        ledger_security_id = security_id
        bindings = (
            PortfolioRiskIdentityBinding(
                asset_code=asset_code,
                ledger_security_id=security_id,
                source_security_id=security_id,
                basis="ledger",
            ),
        )
        preview_identity["security_id"] = other_security_id
        preview = replace(
            preview,
            asset_items=(replace(preview_row, identity=preview_identity),),
        )

    unproven = _with_bindings(
        prepared,
        bindings,
        ledger_security_id=ledger_security_id,
    )
    reasons = plan_preview_reservation_read_reasons(preview, unproven)

    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_UNKNOWN" in reasons
    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_CHANGED" not in reasons


def test_exact_sellable_quantity_change_remains_blocked_after_identity_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid mapping does not relax exact available-minus-reserved quantity checks."""

    prepared, preview = _read_case(monkeypatch)
    binding = _pinned_binding(
        asset_code=preparation_fixtures._ASSET_CODE,
        source_security_id=preparation_fixtures._SECURITY_ID,
    )
    mapped = _with_bindings(prepared, (binding,), ledger_security_id=None)
    row = replace(preview.asset_items[0], sellable_quantity=Decimal("86"))
    changed_preview = replace(preview, asset_items=(row,))

    reasons = plan_preview_reservation_read_reasons(changed_preview, mapped)

    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_CHANGED" in reasons
    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_UNKNOWN" not in reasons


def test_existing_sell_reservation_quantity_must_still_match_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity mapping does not relax the existing active-SELL reservation check."""

    prepared, preview = _read_case(monkeypatch)
    binding = _pinned_binding(
        asset_code=preparation_fixtures._ASSET_CODE,
        source_security_id=preparation_fixtures._SECURITY_ID,
    )
    mapped = _with_bindings(prepared, (binding,), ledger_security_id=None)
    row = replace(preview.asset_items[0], reserved_sell_quantity=Decimal("2"))
    changed_preview = replace(preview, asset_items=(row,))

    reasons = plan_preview_reservation_read_reasons(changed_preview, mapped)

    assert "REBALANCE_PLAN_RESERVED_SELL_CHANGED" in reasons
    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_CHANGED" not in reasons
