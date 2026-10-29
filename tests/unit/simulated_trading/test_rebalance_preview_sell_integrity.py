"""M1 holding SELL integrity contracts for the read-only rebalance preview.

The scenarios cover production valuation, row construction, and plan assembly
with injected readers. They do not claim browser or PostgreSQL acceptance.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.data_center.application import market_calendar
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview_assembly import (
    finish_rebalance_plan_preview,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    RebalancePlanRiskContext,
)
from apps.simulated_trading.application.rebalance_preview_execution_evidence import (
    RebalancePreviewExecutionEvidenceReader,
)
from apps.simulated_trading.application.rebalance_preview_m1_risk import (
    stop_loss_observation,
)
from apps.simulated_trading.application.rebalance_preview_valuation import (
    CurrentRebalanceValuation,
    CurrentRebalanceValuationReader,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
)
from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount
from tests.unit.simulated_trading.test_rebalance_preview_quantity_reasons import (
    _builder as _row_builder,
)
from tests.unit.test_rebalance_preview_m1_risk import _qualification as _m1_risk_qualification

CUTOFF = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
CURRENT_LOCAL_DATE = date(2026, 10, 28)
SECURITY_ID = "fixture:SZ:000001.SZ"


class _SellExecutionEvidence:
    """Read-only identity, lot-rule, and fee evidence for SELL row tests."""

    def read_identity(self, *, asset_code: str, as_of: datetime) -> dict[str, object]:
        return {"security_id": SECURITY_ID}

    def read_quantity_rule(
        self, *, identity: dict[str, object], as_of: datetime
    ) -> tuple[SimpleNamespace, dict[str, object]]:
        lot = {"minimum": Decimal("100"), "step": Decimal("100"), "maximum": Decimal("1000000")}
        rule = SimpleNamespace(
            buy_quantity=SimpleNamespace(**lot),
            sell_quantity=SimpleNamespace(**lot),
            sell_odd_lot_mode=SimpleNamespace(value="SELLABLE_BALANCE_TO_ZERO"),
        )
        return rule, {"security_id": SECURITY_ID}

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


class _StubPriceReader:
    """Read-only market price port returning one prepared result."""

    def __init__(self, result: MarketPriceResult) -> None:
        self._result = result
        self.calls: list[tuple[str, date | None]] = []

    def get_price_result(
        self, asset_code: str, trade_date: date | None = None
    ) -> MarketPriceResult | None:
        self.calls.append((asset_code, trade_date))
        return self._result

    def clear_cache(self) -> None:
        raise AssertionError("cache mutation is outside the read-only preview contract")


def _builder() -> ReadOnlyRebalancePlanPreviewBuilder:
    """Reuse the shared row-builder shell with SELL-capable evidence."""

    builder = _row_builder()
    builder._execution_evidence = cast(
        RebalancePreviewExecutionEvidenceReader, _SellExecutionEvidence()
    )
    return builder


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=613,
        account_name="unit fixture",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000,
        current_cash=100_000,
        current_market_value=3_000,
        total_value=103_000,
        stop_loss_pct=8,
    )


def _holding(*, available_known: bool = True) -> Position:
    """One synthetic holding with 300 total and 100 known available shares."""

    return Position(
        account_id=613,
        asset_code="000001.SZ",
        asset_name="fixture asset",
        asset_type="equity",
        quantity=Decimal("300"),
        available_quantity=Decimal("100"),
        avg_cost=10,
        total_cost=3000,
        current_price=10,
        market_value=3000,
        unrealized_pnl=0,
        unrealized_pnl_pct=0,
        first_buy_date=date(2026, 10, 20),
        last_update_date=date(2026, 10, 27),
        cost_basis_known=True,
        available_quantity_known=available_known,
    )


def _quote() -> MarketPriceResult:
    return MarketPriceResult(
        normalized_code="000001.SZ",
        price=10,
        as_of=date(2026, 10, 27),
        source="fixture",
        freshness="close_fallback",
        is_fallback=True,
    )


def _reservation(remaining_shares: str) -> ActiveRebalanceReservation:
    return ActiveRebalanceReservation(
        reservation_id=1,
        asset_code="000001.SZ",
        security_id=SECURITY_ID,
        side="sell",
        remaining_cash=Decimal("0.00"),
        remaining_shares=Decimal(remaining_shares),
        remaining_buy_notional=None,
    )


def _sell_row(**overrides: object) -> RebalancePlanPreviewItem:
    """Build a user-target SELL-to-zero row through the production builder."""

    inputs: dict[str, object] = {
        "account": _account(),
        "user_id": 41,
        "position": _holding(),
        "check": {"scope": "asset", "asset_name": "fixture asset", "target_weight": "0"},
        "asset_code": "000001.SZ",
        "quote": _quote(),
        "quote_reason": None,
        "portfolio_value": Decimal("30000"),
        "max_position_pct": None,
        "account_max_position_pct": Decimal("20"),
        "account_stop_loss_pct": Decimal("8"),
        "strategy_stop_loss_pct": None,
        "position_rule_id": None,
        "active_reservations": (),
        "as_of": CUTOFF,
        "strategy_policy_applicability": "not_applicable",
        "target_mode": "user_target_difference",
        "price_publication": None,
    }
    inputs.update(overrides)
    return _builder()._asset_item(**inputs)


def test_unknown_available_quantity_preserves_none_and_blocks_sell() -> None:
    """available_quantity_known=False never synthesizes a sellable share count."""

    row = _sell_row(position=_holding(available_known=False))

    assert row.action == "sell"
    assert row.suggested_quantity == Decimal("300")
    assert row.sellable_quantity is None
    assert row.actionable_quantity is None
    assert row.actionable_amount is None
    assert row.fee is None
    assert row.status == "blocked"
    assert "SELLABLE_QUANTITY_UNKNOWN" in row.reason_codes


def test_sell_capped_by_available_not_total_and_reservation_reduces_free() -> None:
    """Reservations reduce free shares while preserving the supplied lot rule."""

    row = _sell_row()

    assert row.suggested_quantity == Decimal("300")
    assert row.sellable_quantity == Decimal("100")
    assert row.actionable_quantity == Decimal("100")
    assert row.actionable_amount == Decimal("1000.00")
    assert row.fee == {"total": "1.00"}
    assert row.status == "partial"
    assert "SELL_QUANTITY_LIMITED_BY_RULE" in row.reason_codes
    assert "SELLABLE_QUANTITY_PARTIAL" in row.reason_codes

    reserved = _sell_row(active_reservations=(_reservation("40"),))

    assert reserved.reserved_sell_quantity == Decimal("40")
    assert reserved.sellable_quantity == Decimal("60")
    assert reserved.actionable_quantity is None
    assert reserved.status == "blocked"
    assert "SELL_QUANTITY_NOT_ON_RULE_STEP" in reserved.reason_codes

    over_reserved = _sell_row(active_reservations=(_reservation("150"),))

    assert over_reserved.sellable_quantity is None
    assert over_reserved.actionable_quantity is None
    assert over_reserved.status == "blocked"
    assert "ACTIVE_SELL_RESERVATION_EXCEEDS_SELLABLE" in over_reserved.reason_codes
    assert "SELLABLE_QUANTITY_INVALID" in over_reserved.reason_codes


def _valuation(
    result: MarketPriceResult, *, cutoff: datetime = CUTOFF
) -> CurrentRebalanceValuation:
    """Run the production valuation reader with one injected price port."""

    reader = CurrentRebalanceValuationReader(price_reader=_StubPriceReader(result))
    return reader.read(
        asset_codes={"000001.SZ"},
        account=_account(),
        positions=(_holding(),),
        checks=(),
        position_codes_valid=True,
        cutoff=cutoff,
        current_local_date=CURRENT_LOCAL_DATE,
    )


def test_valuation_rejects_stale_or_future_quotes_and_row_stays_unactionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale closes and future-dated quotes never reach an actionable SELL."""

    # Inject only the external calendar loader; the production freshness and
    # valuation checks still run. Missing provider setup cannot explain a pass.
    def open_sessions(start_date: date, end_date: date) -> tuple[date, ...]:
        assert start_date <= date(2026, 10, 26)
        assert end_date == CURRENT_LOCAL_DATE
        return (date(2026, 10, 26), date(2026, 10, 27), CURRENT_LOCAL_DATE)

    monkeypatch.setattr(market_calendar, "load_open_cn_market_sessions", open_sessions)
    current = _quote()
    assert _valuation(current).prices["000001.SZ"] == current
    assert _sell_row(quote=current).actionable_quantity == Decimal("100")
    # The existing current-purpose contract rejects yesterday's close during
    # an open session even though the same close was valid before the open.
    intraday = _valuation(current, cutoff=CUTOFF.replace(hour=6))
    assert intraday.prices["000001.SZ"] is None
    assert intraday.price_reasons["000001.SZ"] == "QUOTE_OBSERVATION_STALE"

    def close_result(**kw: object) -> MarketPriceResult:
        base: dict[str, object] = {
            "normalized_code": "000001.SZ",
            "price": 10,
            "source": "fixture",
            "freshness": "close_fallback",
            "is_fallback": True,
        }
        base.update(kw)
        return MarketPriceResult(**base)

    cases = (
        (close_result(as_of=date(2026, 10, 20)), "QUOTE_OBSERVATION_STALE"),
        (close_result(as_of=date(2026, 10, 29)), "QUOTE_DATE_IN_FUTURE"),
        (
            close_result(
                as_of=date(2026, 10, 28),
                freshness="realtime",
                is_fallback=False,
                observed_at=datetime(2026, 10, 28, 7, 0, tzinfo=UTC),
            ),
            "QUOTE_OBSERVATION_IN_FUTURE",
        ),
    )
    for result, expected_reason in cases:
        valuation = _valuation(result)

        assert valuation.prices["000001.SZ"] is None
        assert valuation.price_reasons["000001.SZ"] == expected_reason

        row = _sell_row(quote=None, quote_reason=valuation.price_reasons["000001.SZ"])

        assert row.action == "sell"
        assert row.status == "blocked"
        assert row.actionable_quantity is None
        assert row.actionable_amount is None
        assert row.fee is None
        assert expected_reason in row.reason_codes


def _preview_item(
    *,
    action: str,
    asset_code: str,
    status: str,
    suggested: Decimal,
    actionable: Decimal | None,
    fee: dict[str, object] | None,
    sellable: Decimal | None = None,
    reasons: tuple[str, ...] = (),
) -> RebalancePlanPreviewItem:
    """One asset row as the production row builder would emit it."""

    price = Decimal("10")
    is_sell = action == "sell"
    return RebalancePlanPreviewItem(
        scope="asset",
        action=action,
        asset_code=asset_code,
        asset_name=f"fixture {asset_code}",
        asset_type="equity",
        currency_unit="CNY",
        quantity_unit="shares",
        current_weight=Decimal("0.03") if is_sell else Decimal("0"),
        target_weight=(
            (Decimal("300") - suggested) * price / Decimal("100000") if is_sell else Decimal("0.02")
        ),
        portfolio_value=Decimal("100000"),
        current_amount=Decimal("3000") if is_sell else Decimal("0"),
        target_amount=(Decimal("300") - suggested) * price if is_sell else Decimal("2000"),
        suggested_amount=(suggested * price).quantize(Decimal("0.01")),
        actionable_amount=(
            (actionable * price).quantize(Decimal("0.01")) if actionable is not None else None
        ),
        current_quantity=Decimal("300") if is_sell else Decimal("0"),
        target_quantity=Decimal("300") - suggested if is_sell else Decimal("200"),
        suggested_quantity=suggested,
        actionable_quantity=actionable,
        remaining_quantity=Decimal("0") if actionable is not None else suggested,
        sellable_quantity=sellable,
        reference_price=price,
        price_source="fixture",
        price_as_of=date(2026, 10, 27),
        price_freshness="close_fallback",
        price_is_fallback=True,
        price_observed_at=None,
        identity={"security_id": f"fixture:SZ:{asset_code}"},
        fee=fee,
        drift_threshold=None,
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status=status,
        reason_codes=reasons,
        target_mode="user_target_difference",
    )


def _finish(
    items: list[RebalancePlanPreviewItem],
    *,
    available_cash: Decimal = Decimal("100000"),
) -> RebalancePlanPreview:
    """Run the production assembly with qualified M1 risk and enough funding."""

    risk_context = RebalancePlanRiskContext(
        strategy_id=None,
        position_rule_id=None,
        strategy_name=None,
        strategy_type=None,
        strategy_version=None,
        rule_name=None,
        risk_profile=None,
        macro_regime=None,
        policy_gear=None,
        max_position_pct=None,
        max_total_position_pct=None,
        stop_loss_pct=None,
        account_max_position_pct=Decimal("20"),
        account_max_total_position_pct=Decimal("95"),
        account_stop_loss_pct=Decimal("8"),
        target_allocation=None,
        pulse=None,
        rule_version=None,
        rule_effective_from=None,
        rule_effective_until=None,
        strategy_policy_applicability="not_applicable",
    )
    return finish_rebalance_plan_preview(
        cutoff=CUTOFF,
        financial_snapshot_read_at=CUTOFF,
        portfolio_value=Decimal("100000"),
        cash_before=available_cash,
        reserved_cash=Decimal("0.00"),
        available_cash_before=available_cash,
        projected_position_amount=Decimal("5000"),
        max_total_position_pct=None,
        account_max_total_position_pct=Decimal("95"),
        strategy_policy_applicability="not_applicable",
        reason_codes=(),
        allocation_items=(),
        items=items,
        risk_context=risk_context,
        risk_policy_qualification=_m1_risk_qualification(),
        m1_stop_loss_observation=stop_loss_observation(
            positions=(_holding(),), prices={"000001.SZ": _quote()}
        ),
        projected_buy_position_amount_by_asset={"000002.SZ": Decimal("2000")},
    )


def _ready_buy() -> RebalancePlanPreviewItem:
    return _preview_item(
        action="buy",
        asset_code="000002.SZ",
        status="ready",
        suggested=Decimal("200"),
        actionable=Decimal("200"),
        fee={"total": "1.00"},
    )


def _rows(preview: RebalancePlanPreview, action: str) -> RebalancePlanPreviewItem:
    return next(item for item in preview.asset_items if item.action == action)


def _assert_read_only_payload(preview: RebalancePlanPreview) -> None:
    """The final payload never carries execution or writer capability."""

    payload = preview.to_payload()
    assert payload["read_only"] is True
    assert payload["execution_submitted"] is False
    assert payload["must_not_execute"] is True


def test_ready_sell_marks_dependent_buy_conditional_and_payload_read_only() -> None:
    """Funded BUY quantities stay withheld until the SELL proceeds settle."""

    sell = _preview_item(
        action="sell",
        asset_code="000001.SZ",
        status="ready",
        suggested=Decimal("100"),
        actionable=Decimal("100"),
        fee={"total": "1.00"},
        sellable=Decimal("100"),
    )
    preview = _finish([sell, _ready_buy()])

    sell_row = _rows(preview, "sell")
    buy_row = _rows(preview, "buy")
    assert sell_row.status == "ready"
    assert sell_row.actionable_quantity == Decimal("100")
    assert buy_row.status == "conditional"
    assert buy_row.actionable_quantity is None
    assert buy_row.actionable_amount is None
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in buy_row.reason_codes
    assert preview.funding_status == "conditional"
    assert preview.status == "conditional"
    assert preview.estimated_sell_net == Decimal("999.00")
    assert preview.sell_before_buy["buy_requires_settled_sales"] is True
    _assert_read_only_payload(preview)


def test_unknown_available_sell_blocks_dependent_buy() -> None:
    """A SELL without known sellable shares can never fund a BUY."""

    blocked_sell = _sell_row(position=_holding(available_known=False))
    preview = _finish([blocked_sell, _ready_buy()])

    buy_row = _rows(preview, "buy")
    assert buy_row.status == "blocked"
    assert buy_row.actionable_quantity is None
    assert buy_row.actionable_amount is None
    assert "SELL_DEPENDENCY_INCOMPLETE" in buy_row.reason_codes
    assert preview.funding_status == "unknown"
    assert preview.status == "blocked"
    _assert_read_only_payload(preview)


def test_fee_deficit_sell_with_insufficient_cash_cannot_fund_buy() -> None:
    """A SELL whose fee exceeds gross proceeds and free cash is withheld."""

    fee_deficit_sell = _preview_item(
        action="sell",
        asset_code="000001.SZ",
        status="ready",
        suggested=Decimal("100"),
        actionable=Decimal("100"),
        fee={"total": "2000.00"},
        sellable=Decimal("100"),
    )
    preview = _finish([fee_deficit_sell, _ready_buy()], available_cash=Decimal("50"))

    sell_row = _rows(preview, "sell")
    buy_row = _rows(preview, "buy")
    assert sell_row.status == "blocked"
    assert sell_row.actionable_quantity is None
    assert sell_row.actionable_amount is None
    assert "SELL_FEE_CASH_SHORTFALL" in sell_row.reason_codes
    assert buy_row.status == "blocked"
    assert buy_row.actionable_quantity is None
    assert buy_row.actionable_amount is None
    assert "SELL_DEPENDENCY_INCOMPLETE" in buy_row.reason_codes
    assert preview.sell_before_buy["buy_requires_settled_sales"] is False
    _assert_read_only_payload(preview)
