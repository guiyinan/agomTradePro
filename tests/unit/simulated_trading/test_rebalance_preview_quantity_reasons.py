"""Application behavior for partial BUY quantity constraints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.simulated_trading.application import rebalance_plan_preview
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_preview_execution_evidence import (
    RebalancePreviewExecutionEvidenceReader,
)
from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount
from apps.simulated_trading.domain.rebalance_preview_math import estimate_plan_funding


class _ExecutionEvidence:
    """Provide exact identity, quantity, and fee evidence for a row-level test."""

    def read_identity(self, *, asset_code: str, as_of: datetime) -> dict[str, object]:
        return {"security_id": "fixture:SZ:000001.SZ"}

    def read_quantity_rule(
        self,
        *,
        identity: dict[str, object],
        as_of: datetime,
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        rule = SimpleNamespace(
            buy_quantity=SimpleNamespace(
                minimum=Decimal("100"),
                step=Decimal("100"),
                maximum=Decimal("1000000"),
            )
        )
        return rule, {"security_id": "fixture:SZ:000001.SZ"}

    def estimate_fee(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        identity: dict[str, object],
        action: str,
        notional: Decimal,
        as_of: datetime,
    ) -> dict[str, object]:
        return {"total": "1.00"}


def _builder() -> ReadOnlyRebalancePlanPreviewBuilder:
    """Construct the production row builder without invoking unrelated ports."""

    builder = ReadOnlyRebalancePlanPreviewBuilder(
        price_reader=cast(object, None),
        identity_reader=cast(object, None),
        classification_reader=cast(object, None),
        fee_policy_reader=cast(object, None),
        quantity_rule_reader=cast(object, None),
        resource_snapshot_reader=cast(object, None),
        position_rule_evaluator=cast(object, None),
    )
    builder._execution_evidence = cast(
        RebalancePreviewExecutionEvidenceReader, _ExecutionEvidence()
    )
    return builder


def _row_inputs() -> dict[str, object]:
    """Return a supported BUY target whose exact desired quantity is fractional."""

    return {
        "account": SimulatedAccount(
            account_id=4,
            account_name="unit fixture",
            account_type=AccountType.SIMULATED,
            initial_capital=100_000,
            current_cash=100_000,
            current_market_value=12_816.04185,
            total_value=112_816.04185,
        ),
        "user_id": 8,
        "position": Position(
            account_id=4,
            asset_code="000001.SZ",
            asset_name="fixture asset",
            asset_type="equity",
            quantity=Decimal("1281.604185"),
            available_quantity=Decimal("1281.604185"),
            avg_cost=10,
            total_cost=12816.04185,
            current_price=10,
            market_value=12816.04185,
            unrealized_pnl=0,
            unrealized_pnl_pct=0,
            first_buy_date=date(2026, 10, 1),
            last_update_date=date(2026, 10, 27),
            cost_basis_known=True,
        ),
        "check": {"scope": "asset", "asset_name": "fixture asset", "target_weight": "0.1"},
        "asset_code": "000001.SZ",
        "quote": MarketPriceResult(
            normalized_code="000001.SZ",
            price=10,
            as_of=date(2026, 10, 27),
            source="fixture",
            freshness="close_fallback",
            is_fallback=True,
        ),
        "quote_reason": None,
        "portfolio_value": Decimal("1000000"),
        "max_position_pct": None,
        "account_max_position_pct": Decimal("100"),
        "account_stop_loss_pct": None,
        "strategy_stop_loss_pct": None,
        "position_rule_id": None,
        "active_reservations": (),
        "as_of": datetime(2026, 10, 27, 8, 0, tzinfo=UTC),
        "strategy_policy_applicability": "not_applicable",
        "target_mode": "user_target_difference",
        "price_publication": None,
    }


def test_step_rounded_buy_keeps_known_fee_and_cash_but_unknown_reason_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only recognized partial reasons may retain an actionable quantity and fee."""

    inputs = _row_inputs()
    partial = _builder()._asset_item(**inputs)

    assert partial.status == "partial", partial.reason_codes
    assert partial.reason_codes == ("BUY_QUANTITY_STEP_ROUNDED_DOWN",)
    assert partial.suggested_quantity == Decimal("8718.395815")
    assert partial.actionable_quantity == Decimal("8700")
    assert partial.remaining_quantity == Decimal("18.395815")
    assert partial.fee == {"total": "1.00"}
    assert partial.actionable_amount == Decimal("87000.00")

    funding = estimate_plan_funding(
        cash_before=Decimal("100000.00"),
        sell_gross_values=(),
        sell_fee_values=(),
        buy_gross_values=(partial.actionable_amount,),
        buy_fee_values=(Decimal("1.00"),),
    )
    assert funding.status == "known"
    assert funding.cash_after_buys == Decimal("12999.00")

    monkeypatch.setattr(
        rebalance_plan_preview,
        "account_position_cap_reason",
        lambda **kwargs: "UNRECOGNIZED_ACCOUNT_REASON",
    )
    blocked = _builder()._asset_item(**inputs)

    assert "UNRECOGNIZED_ACCOUNT_REASON" in blocked.reason_codes
    assert blocked.status == "blocked"
    assert blocked.fee is None
    assert blocked.actionable_quantity is None
