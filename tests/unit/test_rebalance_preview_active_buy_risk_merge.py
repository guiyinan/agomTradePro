"""Combined M1 risk and active-BUY exposure counterexamples."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from apps.risk_center.application.m1_rebalance_risk_policy import (
    M1RiskPolicyQualification,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    M1RiskCondition,
    M1RiskObservation,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
    RiskApplicability,
    RiskQualificationState,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.rebalance_preview_m1_risk import (
    block_buys_for_m1_risk,
    build_m1_risk_falsification,
    projected_buy_position_percentages,
    single_position_observation,
    total_position_observation,
)
from apps.simulated_trading.application.rebalance_preview_resources import (
    projected_buy_position_amount_by_asset,
    projected_position_amount,
)
from apps.simulated_trading.application.rebalance_resource_snapshot import (
    ActiveRebalanceReservation,
)
from apps.simulated_trading.domain.entities import Position
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationIdentity,
)
from apps.simulated_trading.domain.rebalance_preview_math import (
    account_position_cap_reason,
    account_total_position_cap_reason,
)

AS_OF = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _qualification(
    *,
    max_single_pct: Decimal,
    max_total_pct: Decimal,
    source_max_single_pct: Decimal = Decimal("20"),
) -> M1RiskPolicyQualification:
    """Bind a qualified revision whose limits are stricter than legacy where requested."""

    source = M1RiskSourceSnapshot(
        account_id=613,
        account_owner_user_id=41,
        account_type="simulated",
        account_is_active=True,
        account_max_single_position_pct=source_max_single_pct,
        account_max_total_position_pct=Decimal("80"),
        account_stop_loss_pct=None,
        strategy_selection_state="confirmed_unconfigured",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )
    revision = M1RiskPolicyRevision(
        risk_policy_version="cda35bb0-8266-4db7-b32c-2d097e2563c0",
        account_id=613,
        actor_user_id=41,
        effective_from=AS_OF,
        effective_until=datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
        known_at=datetime(2026, 10, 25, 11, 55, tzinfo=UTC),
        reason="Owner approved explicit M1 limits.",
        max_single_position=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            max_single_pct,
        ),
        max_total_position=M1RiskCondition(
            RiskApplicability.APPLICABLE,
            max_total_pct,
        ),
        max_stop_loss=M1RiskCondition(
            RiskApplicability.NOT_APPLICABLE,
            None,
            "This projection-only test has no held cost-basis stop-loss input.",
        ),
        source_snapshot=source,
    )
    return M1RiskPolicyQualification(
        state=RiskQualificationState.QUALIFIED,
        reason_codes=(),
        revision=revision,
    )


def _buy_item(
    *,
    asset_code: str,
    target_weight: Decimal,
    current_amount: Decimal,
    suggested_amount: Decimal,
    target_amount: Decimal,
) -> RebalancePlanPreviewItem:
    """Build one typed BUY row with separate held, target, and requested amounts."""

    reference_price = Decimal("10")
    current_quantity = current_amount / reference_price
    target_quantity = target_amount / reference_price
    suggested_quantity = suggested_amount / reference_price
    return RebalancePlanPreviewItem(
        scope="asset",
        action="buy",
        asset_code=asset_code,
        asset_name="Fixture A-share",
        asset_type="equity",
        currency_unit="CNY",
        quantity_unit="shares",
        current_weight=current_amount / Decimal("1000"),
        target_weight=target_weight,
        portfolio_value=Decimal("1000"),
        current_amount=current_amount,
        target_amount=target_amount,
        suggested_amount=suggested_amount,
        actionable_amount=suggested_amount,
        current_quantity=current_quantity,
        target_quantity=target_quantity,
        suggested_quantity=suggested_quantity,
        actionable_quantity=suggested_quantity,
        remaining_quantity=Decimal("0"),
        sellable_quantity=current_quantity,
        reference_price=reference_price,
        price_source="fixture_quote",
        price_as_of=AS_OF.date(),
        price_freshness="fresh",
        price_is_fallback=False,
        price_observed_at=AS_OF,
        identity={},
        fee={"total": "0.00"},
        drift_threshold=None,
        risk_rule_result=None,
        risk_rule_reason_code=None,
        risk_rule_entry_price_basis=None,
        status="ready",
        reason_codes=(),
        target_mode="user_target_difference",
    )


def _held_position(asset_code: str, market_value: Decimal = Decimal("300.00")) -> Position:
    """Build the real entity shape for a known current holding."""

    current_price = float(market_value / Decimal("10"))
    return Position(
        account_id=613,
        asset_code=asset_code,
        asset_name="Fixture A-share",
        asset_type="equity",
        quantity=10.0,
        available_quantity=10.0,
        avg_cost=current_price,
        total_cost=float(market_value),
        current_price=current_price,
        market_value=float(market_value),
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 10, 1),
        last_update_date=date(2026, 10, 25),
        cost_basis_known=True,
    )


def _reservation(
    *,
    reservation_id: int,
    asset_code: str,
    side: Literal["buy", "sell"],
    remaining_cash: Decimal,
    remaining_shares: Decimal = Decimal("0.000000"),
    remaining_buy_notional: Decimal | None,
) -> ActiveRebalanceReservation:
    """Build a reservation snapshot without conflating the cash and exposure fields."""

    return ActiveRebalanceReservation(
        reservation_id=reservation_id,
        asset_code=asset_code,
        security_id=f"fixture:{asset_code}",
        side=side,
        remaining_cash=remaining_cash,
        remaining_shares=remaining_shares,
        remaining_buy_notional=remaining_buy_notional,
    )


def test_single_position_policy_observes_held_plus_open_plus_requested_notional() -> None:
    """The 19% M1 cap blocks a BUY whose held/reserved/requested exposure is 25%."""

    item = _buy_item(
        asset_code="600000.SH",
        target_weight=Decimal("0.20"),
        current_amount=Decimal("150.00"),
        suggested_amount=Decimal("50.00"),
        target_amount=Decimal("200.00"),
    )
    reservation = _reservation(
        reservation_id=1,
        asset_code="600000.SH",
        side="buy",
        remaining_cash=Decimal("60.00"),
        remaining_buy_notional=Decimal("50.00"),
    )
    amount_by_asset = projected_buy_position_amount_by_asset(
        items=[item],
        active_reservations=(reservation,),
    )
    exposure_by_asset = projected_buy_position_percentages(
        projected_buy_position_amount_by_asset=amount_by_asset,
        projected_equity=Decimal("1000.00"),
    )

    assert amount_by_asset == {"600000.SH": Decimal("250.00")}
    assert exposure_by_asset == {"600000.SH": Decimal("25.0000")}
    assert (
        account_position_cap_reason(
            action="buy",
            target_weight=Decimal("0.20"),
            max_position_pct=Decimal("30"),
            active_buy_notional=Decimal("50.00"),
            portfolio_value=Decimal("1000.00"),
        )
        is None
    )
    single_observation = single_position_observation(
        items=(item,),
        projected_position_pct_by_asset=exposure_by_asset,
    )
    assert single_observation.observed_pct == Decimal("25.0000")

    qualification = _qualification(
        max_single_pct=Decimal("19"),
        max_total_pct=Decimal("80"),
        source_max_single_pct=Decimal("30"),
    )
    assert qualification.revision is not None
    assert qualification.revision.source_snapshot.account_max_single_position_pct == Decimal("30")
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_observation,
            M1RiskObservation("max_total_position", RiskApplicability.APPLICABLE, Decimal("25")),
            M1RiskObservation("max_stop_loss", RiskApplicability.NOT_APPLICABLE, None),
        ),
    )
    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.status == "falsified"
    assert blocked.status == "blocked"
    assert blocked.actionable_quantity is None
    assert "M1_RISK_FALSIFICATION_TRIGGERED" in blocked.reason_codes


def test_total_position_policy_gets_held_open_and_requested_amount_with_fee_adjusted_equity() -> (
    None
):
    """The legacy 80% cap allows 53%; M1 50% blocks while the 20% single cap passes."""

    hold_a = replace(
        _buy_item(
            asset_code="600000.SH",
            target_weight=Decimal("0.155"),
            current_amount=Decimal("155.00"),
            suggested_amount=Decimal("0.00"),
            target_amount=Decimal("155.00"),
        ),
        action="hold",
    )
    buy_b = replace(
        _buy_item(
            asset_code="000001.SZ",
            target_weight=Decimal("0.185"),
            current_amount=Decimal("155.00"),
            suggested_amount=Decimal("30.00"),
            target_amount=Decimal("185.00"),
        ),
        fee={"total": Decimal("0.50")},
    )
    hold_c = replace(
        _buy_item(
            asset_code="000002.SZ",
            target_weight=Decimal("0.16"),
            current_amount=Decimal("160.00"),
            suggested_amount=Decimal("0.00"),
            target_amount=Decimal("160.00"),
        ),
        action="hold",
    )
    items = [hold_a, buy_b, hold_c]
    reservation = _reservation(
        reservation_id=2,
        asset_code="600000.SH",
        side="buy",
        remaining_cash=Decimal("35.00"),
        remaining_buy_notional=Decimal("30.00"),
    )
    projected_amount = projected_position_amount(
        positions=(
            _held_position("600000.SH", Decimal("155.00")),
            _held_position("000001.SZ", Decimal("155.00")),
            _held_position("000002.SZ", Decimal("160.00")),
        ),
        targets={"600000.SH": {}, "000001.SZ": {}, "000002.SZ": {}},
        items=items,
        prices={},
        portfolio_value=Decimal("1000.00"),
        active_reservations=(reservation,),
    )
    amount_by_asset = projected_buy_position_amount_by_asset(
        items=items,
        active_reservations=(reservation,),
    )
    projected_equity = Decimal("999.50")
    exposure_by_asset = projected_buy_position_percentages(
        projected_buy_position_amount_by_asset=amount_by_asset,
        projected_equity=projected_equity,
    )

    assert projected_amount == Decimal("530.00")
    assert amount_by_asset == {"000001.SZ": Decimal("185.00")}
    assert exposure_by_asset == {"000001.SZ": Decimal("18.5092546273136568284142071")}
    assert (
        account_total_position_cap_reason(
            action="buy",
            projected_position_amount=projected_amount,
            projected_equity=projected_equity,
            max_total_position_pct=Decimal("80"),
        )
        is None
    )
    total_observation = total_position_observation(
        has_buy=True,
        projected_position_amount=projected_amount,
        projected_equity=projected_equity,
    )
    assert total_observation.observed_pct == Decimal("53.02651325662831415707853927")
    single_observation = single_position_observation(
        items=tuple(items),
        projected_position_pct_by_asset=exposure_by_asset,
    )
    assert single_observation.observed_pct == Decimal("18.5092546273136568284142071")

    qualification = _qualification(
        max_single_pct=Decimal("20"),
        max_total_pct=Decimal("50"),
    )
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_observation,
            total_observation,
            M1RiskObservation("max_stop_loss", RiskApplicability.NOT_APPLICABLE, None),
        ),
    )
    blocked = block_buys_for_m1_risk(
        items=[buy_b],
        qualification=qualification,
        falsification=falsification,
    )[0]

    assert falsification.status == "falsified"
    assert falsification.conditions[0].outcome.value == "not_falsified"
    assert falsification.conditions[1].outcome.value == "falsified"
    assert blocked.status == "blocked"
    assert blocked.actionable_amount is None


def test_unknown_same_asset_buy_notional_makes_both_risk_observations_unknown() -> None:
    """Missing accepted notional is not replaced by the available cash reserve."""

    item = _buy_item(
        asset_code="600000.SH",
        target_weight=Decimal("0.20"),
        current_amount=Decimal("150.00"),
        suggested_amount=Decimal("50.00"),
        target_amount=Decimal("200.00"),
    )
    reservation = _reservation(
        reservation_id=3,
        asset_code="600000.SH",
        side="buy",
        remaining_cash=Decimal("100.00"),
        remaining_buy_notional=None,
    )
    amount_by_asset = projected_buy_position_amount_by_asset(
        items=[item],
        active_reservations=(reservation,),
    )
    exposure_by_asset = projected_buy_position_percentages(
        projected_buy_position_amount_by_asset=amount_by_asset,
        projected_equity=Decimal("1000.00"),
    )
    projected_amount = projected_position_amount(
        positions=(_held_position("600000.SH", Decimal("150.00")),),
        targets={"600000.SH": {}},
        items=[item],
        prices={},
        portfolio_value=Decimal("1000.00"),
        active_reservations=(reservation,),
    )

    single_observation = single_position_observation(
        items=(item,),
        projected_position_pct_by_asset=exposure_by_asset,
    )
    total_observation = total_position_observation(
        has_buy=True,
        projected_position_amount=projected_amount,
        projected_equity=Decimal("1000.00"),
    )
    assert "600000.SH" not in amount_by_asset
    assert "600000.SH" not in exposure_by_asset
    assert projected_amount is None
    assert single_observation.applicability is RiskApplicability.UNKNOWN
    assert total_observation.applicability is RiskApplicability.UNKNOWN

    qualification = _qualification(
        max_single_pct=Decimal("19"),
        max_total_pct=Decimal("50"),
    )
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_observation,
            total_observation,
            M1RiskObservation("max_stop_loss", RiskApplicability.NOT_APPLICABLE, None),
        ),
    )
    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]
    assert falsification.status == "unknown"
    assert blocked.status == "blocked"
    assert "M1_RISK_FALSIFICATION_UNKNOWN" in blocked.reason_codes


def test_known_fee_reduces_shared_equity_denominator_and_unknown_fee_stays_unknown() -> None:
    """Single and total use the same net equity while gross exposure stays fee-free."""

    item = replace(
        _buy_item(
            asset_code="600000.SH",
            target_weight=Decimal("0.05"),
            current_amount=Decimal("100.00"),
            suggested_amount=Decimal("50.00"),
            target_amount=Decimal("150.00"),
        ),
        fee={"total": Decimal("5.00")},
    )
    reservation = _reservation(
        reservation_id=5,
        asset_code="600000.SH",
        side="buy",
        remaining_cash=Decimal("54.50"),
        remaining_buy_notional=Decimal("49.50"),
    )
    amount_by_asset = projected_buy_position_amount_by_asset(
        items=[item],
        active_reservations=(reservation,),
    )
    projected_equity = Decimal("995.00")
    exposure_by_asset = projected_buy_position_percentages(
        projected_buy_position_amount_by_asset=amount_by_asset,
        projected_equity=projected_equity,
    )

    assert amount_by_asset == {"600000.SH": Decimal("199.50")}
    assert exposure_by_asset["600000.SH"] > Decimal("19.99")
    assert amount_by_asset["600000.SH"] * Decimal("100") / Decimal("1000.00") < Decimal("19.99")
    single_observation = single_position_observation(
        items=(item,),
        projected_position_pct_by_asset=exposure_by_asset,
    )
    total_observation = total_position_observation(
        has_buy=True,
        projected_position_amount=amount_by_asset["600000.SH"],
        projected_equity=projected_equity,
    )
    assert single_observation.observed_pct == total_observation.observed_pct

    qualification = _qualification(
        max_single_pct=Decimal("19.99"),
        max_total_pct=Decimal("80"),
    )
    falsification = build_m1_risk_falsification(
        qualification=qualification,
        observations=(
            single_observation,
            total_observation,
            M1RiskObservation("max_stop_loss", RiskApplicability.NOT_APPLICABLE, None),
        ),
    )
    blocked = block_buys_for_m1_risk(
        items=[item],
        qualification=qualification,
        falsification=falsification,
    )[0]
    unknown_equity_percentages = projected_buy_position_percentages(
        projected_buy_position_amount_by_asset=amount_by_asset,
        projected_equity=None,
    )
    unknown_single = single_position_observation(
        items=(item,),
        projected_position_pct_by_asset=unknown_equity_percentages,
    )
    unknown_total = total_position_observation(
        has_buy=True,
        projected_position_amount=amount_by_asset["600000.SH"],
        projected_equity=None,
    )

    assert falsification.status == "falsified"
    assert blocked.status == "blocked"
    assert blocked.actionable_quantity is None
    assert unknown_single.applicability is RiskApplicability.UNKNOWN
    assert unknown_total.applicability is RiskApplicability.UNKNOWN


def test_numeric_exposure_over_one_hundred_percent_remains_a_falsifiable_observation() -> None:
    """A large known exposure stays numeric instead of being disguised as unknown."""

    item = _buy_item(
        asset_code="600000.SH",
        target_weight=Decimal("0.05"),
        current_amount=Decimal("900.00"),
        suggested_amount=Decimal("200.00"),
        target_amount=Decimal("1100.00"),
    )
    observation = single_position_observation(
        items=(item,),
        projected_position_pct_by_asset={"600000.SH": Decimal("110")},
    )

    assert observation.applicability is RiskApplicability.APPLICABLE
    assert observation.observed_pct == Decimal("110")


def test_planned_and_active_sells_never_release_projected_exposure_early() -> None:
    """A SELL target and its share hold leave the complete current holding exposed."""

    sell_item = _buy_item(
        asset_code="600000.SH",
        target_weight=Decimal("0.05"),
        current_amount=Decimal("300.00"),
        suggested_amount=Decimal("250.00"),
        target_amount=Decimal("50.00"),
    )
    sell_item = replace(sell_item, action="sell")
    active_sell = _reservation(
        reservation_id=4,
        asset_code="600000.SH",
        side="sell",
        remaining_cash=Decimal("0.00"),
        remaining_shares=Decimal("5.000000"),
        remaining_buy_notional=None,
    )

    projected_amount = projected_position_amount(
        positions=(_held_position("600000.SH"),),
        targets={"600000.SH": {}},
        items=[sell_item],
        prices={},
        portfolio_value=Decimal("1000.00"),
        active_reservations=(active_sell,),
    )

    assert projected_amount == Decimal("300.00")


def test_remaining_active_buy_notional_excludes_filled_shares_and_fee_cash() -> None:
    """The reservation source is residual quantity times accepted limit, not cash."""

    reservation = OrderReservation(
        identity=OrderReservationIdentity(
            account_id=613,
            security_id="fixture:SH:600000.SH",
            idempotency_key="m1-risk-active-buy-merge-test",
            request_payload_hash="a" * 64,
        ),
        side=SimulatedTradeSide.BUY,
        quantity=Decimal("10.000000"),
        limit_price=Decimal("10.00"),
        notional=Decimal("100.00"),
        fee_estimate=Decimal("0.50"),
        fee_budget=Decimal("2.00"),
        cash_reserved=Decimal("102.00"),
        shares_reserved=Decimal("0.000000"),
        reserved_at=AS_OF,
        filled_quantity=Decimal("4.000000"),
        cash_consumed=Decimal("36.50"),
    )

    assert reservation.remaining_buy_notional == Decimal("60.00")
    assert reservation.remaining_cash == Decimal("65.50")
    assert reservation.remaining_cash != reservation.remaining_buy_notional
