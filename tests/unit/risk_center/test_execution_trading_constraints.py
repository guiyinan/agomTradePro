from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.risk_center.application.execution_trading_constraints import (
    ExecutionConstraintsEvaluation,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionDecisionStatus,
    ExecutionDenyCode,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    ExecutionTradingDecision,
    PriceBoundaryMode,
    SecurityTradingState,
    SellOddLotMode,
    SellPositionCompleteness,
    SessionState,
    evaluate_execution_order,
)
from qmt_agent.execution_constraints import validate_effective_constraints

AS_OF = datetime(2026, 10, 16, 1, 45, tzinfo=UTC)
TRADING_DATE = date(2026, 10, 16)
SYNTHETIC_SOURCE_HASH = "a" * 64


def _quantity(
    minimum: str = "10", step: str = "10", maximum: str = "1000"
) -> ExecutionQuantityConstraint:
    return ExecutionQuantityConstraint(
        minimum=Decimal(minimum),
        step=Decimal(step),
        maximum=Decimal(maximum),
    )


def _rule(**changes: object) -> AShareExecutionRule:
    values: dict[str, object] = {
        "rule_id": "synthetic-rule-mainboard-v1",
        "rule_version": "fixture-v1",
        "security_id": "600000.SH",
        "market": "SH",
        "board": "MAIN",
        "buy_quantity": _quantity(),
        "sell_quantity": _quantity(),
        "sell_odd_lot_mode": SellOddLotMode.FORBID,
        "price_tick": Decimal("0.05"),
        "rule_source_id": "synthetic-rule-source",
        "rule_source_version": "fixture-v1",
        "rule_source_hash": SYNTHETIC_SOURCE_HASH,
        "source_observed_at": AS_OF - timedelta(hours=2),
        "source_available_at": AS_OF - timedelta(hours=1),
        "effective_from": AS_OF - timedelta(days=1),
        "valid_until": AS_OF + timedelta(hours=1),
    }
    values.update(changes)
    return AShareExecutionRule(**values)  # type: ignore[arg-type]


def _market(**changes: object) -> ExecutionMarketEvidence:
    values: dict[str, object] = {
        "security_id": "600000.SH",
        "market": "SH",
        "board": "MAIN",
        "trading_date": TRADING_DATE,
        "calendar_id": "synthetic-calendar",
        "calendar_version": "fixture-v1",
        "calendar_source_hash": "b" * 64,
        "calendar_observed_at": AS_OF - timedelta(days=1),
        "calendar_available_at": AS_OF - timedelta(hours=1),
        "calendar_valid_until": AS_OF + timedelta(days=1),
        "session_id": "synthetic-day-session",
        "session_timezone": "Asia/Shanghai",
        "session_open_at": datetime(2026, 10, 16, 1, 30, tzinfo=UTC),
        "session_close_at": datetime(2026, 10, 16, 3, 30, tzinfo=UTC),
        "session_state": SessionState.OPEN,
        "security_state": SecurityTradingState.TRADING,
        "market_source_id": "synthetic-quote-source",
        "market_source_version": "fixture-v1",
        "market_source_hash": "c" * 64,
        "price_boundary_mode": PriceBoundaryMode.LIMITED,
        "lower_limit_price": Decimal("9.00"),
        "upper_limit_price": Decimal("11.00"),
        "reference_price": Decimal("10.00"),
        "market_observed_at": AS_OF - timedelta(seconds=2),
        "market_available_at": AS_OF - timedelta(seconds=1),
        "market_valid_until": AS_OF + timedelta(minutes=1),
    }
    values.update(changes)
    return ExecutionMarketEvidence(**values)  # type: ignore[arg-type]


def _sell_position(**changes: object):
    from apps.risk_center.domain.execution_trading_constraints import SellPositionEvidence

    values: dict[str, object] = {
        "security_id": "600000.SH",
        "account_id": 7,
        "available_to_sell_quantity": Decimal("15"),
        "restricted_quantity": Decimal("0"),
        "completeness": SellPositionCompleteness.COMPLETE,
        "source_id": "synthetic-position-source",
        "source_version": "fixture-v1",
        "source_hash": "d" * 64,
        "observed_at": AS_OF - timedelta(seconds=2),
        "available_at": AS_OF - timedelta(seconds=1),
        "valid_until": AS_OF + timedelta(minutes=1),
    }
    values.update(changes)
    return SellPositionEvidence(**values)  # type: ignore[arg-type]


def _odd_remainder_once_mode() -> SellOddLotMode:
    mode = SellOddLotMode.__members__.get("SELL_ODD_REMAINDER_ONCE")
    if mode is None:
        pytest.fail("SELL_ODD_REMAINDER_ONCE rule mode is not implemented")
    return mode


def _order(**changes: object) -> ExecutionOrder:
    values: dict[str, object] = {
        "order_id": "synthetic-order-1",
        "account_id": 7,
        "security_id": "600000.SH",
        "side": ExecutionSide.BUY,
        "quantity": Decimal("20"),
        "limit_price": Decimal("10.00"),
        "sell_position_evidence": None,
    }
    values.update(changes)
    return ExecutionOrder(**values)  # type: ignore[arg-type]


def _decision_codes(
    order: ExecutionOrder,
    *,
    rule: AShareExecutionRule | None = None,
    market: ExecutionMarketEvidence | None = None,
) -> tuple[ExecutionDenyCode, ...]:
    return evaluate_execution_order(rule or _rule(), market or _market(), order, AS_OF).reason_codes


def test_synthetic_mainboard_fixture_allows_explicit_valid_limit_order() -> None:
    decision = evaluate_execution_order(_rule(), _market(), _order(), AS_OF)

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert decision.reason_codes == ()
    assert decision.order_id == "synthetic-order-1"


def test_synthetic_star_fixture_uses_its_own_buy_and_sell_constraints() -> None:
    # Synthetic fixture values only; this does not encode an official STAR rule.
    star_rule = _rule(
        security_id="688001.SH",
        market="SH",
        board="STAR",
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("3"), step=Decimal("1"), maximum=Decimal("700")
        ),
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("2"), step=Decimal("2"), maximum=Decimal("800")
        ),
        price_tick=Decimal("0.01"),
        content_hash="",
    )
    evidence = _market(
        security_id="688001.SH",
        board="STAR",
        lower_limit_price=Decimal("8.00"),
        upper_limit_price=Decimal("12.00"),
        reference_price=Decimal("10.01"),
        market_valid_until=AS_OF + timedelta(minutes=1),
        content_hash="",
    )
    decision = evaluate_execution_order(
        star_rule,
        evidence,
        _order(security_id="688001.SH", quantity=Decimal("3"), limit_price=Decimal("10.02")),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    codes = _decision_codes(
        _order(
            security_id="688001.SH",
            side=ExecutionSide.SELL,
            quantity=Decimal("3"),
            limit_price=Decimal("10.02"),
        ),
        rule=star_rule,
        market=evidence,
    )
    assert ExecutionDenyCode.QUANTITY_NOT_ON_STEP in codes
    assert ExecutionDenyCode.POSITION_EVIDENCE_MISSING in codes


@pytest.mark.parametrize(
    ("side", "quantity", "expected"),
    [
        (ExecutionSide.BUY, "5", ExecutionDenyCode.QUANTITY_BELOW_MINIMUM),
        (ExecutionSide.BUY, "15", ExecutionDenyCode.QUANTITY_NOT_ON_STEP),
        (ExecutionSide.BUY, "1010", ExecutionDenyCode.QUANTITY_ABOVE_MAXIMUM),
        (ExecutionSide.SELL, "25", ExecutionDenyCode.QUANTITY_NOT_ON_STEP),
    ],
)
def test_buy_and_sell_minimum_step_and_maximum_are_independent(
    side: ExecutionSide,
    quantity: str,
    expected: ExecutionDenyCode,
) -> None:
    codes = _decision_codes(
        _order(side=side, quantity=Decimal(quantity)),
        rule=_rule(
            buy_quantity=_quantity("10", "10", "1000"),
            sell_quantity=_quantity("20", "20", "900"),
            content_hash="",
        ),
    )

    assert expected in codes


def test_sell_to_zero_only_clears_fully_proven_available_balance() -> None:
    rule = _rule(sell_odd_lot_mode=SellOddLotMode.SELLABLE_BALANCE_TO_ZERO, content_hash="")
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("15"),
        sell_position_evidence=_sell_position(),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.ALLOWED


def test_sellable_balance_clear_can_bypass_sell_minimum_only_with_full_evidence() -> None:
    rule = _rule(
        sell_quantity=_quantity("20", "10", "1000"),
        sell_odd_lot_mode=SellOddLotMode.SELLABLE_BALANCE_TO_ZERO,
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("15"),
        sell_position_evidence=_sell_position(),
    )

    market = _market()
    decision = evaluate_execution_order(rule, market, order, AS_OF)
    assert decision.status is ExecutionDecisionStatus.ALLOWED
    envelope = ExecutionConstraintsEvaluation(
        rule=rule,
        market_evidence=market,
        order=order,
        as_of=AS_OF,
        decision=decision,
    ).to_payload()
    validate_effective_constraints(envelope, submitted_at=AS_OF)


def test_aligned_sellable_balance_below_minimum_can_be_cleared_with_full_evidence() -> None:
    rule = _rule(
        sell_quantity=_quantity("200", "1", "1000"),
        sell_odd_lot_mode=SellOddLotMode.SELLABLE_BALANCE_TO_ZERO,
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("150"),
        sell_position_evidence=_sell_position(available_to_sell_quantity=Decimal("150")),
    )

    market = _market()
    decision = evaluate_execution_order(rule, market, order, AS_OF)
    assert decision.status is ExecutionDecisionStatus.ALLOWED
    envelope = ExecutionConstraintsEvaluation(
        rule=rule,
        market_evidence=market,
        order=order,
        as_of=AS_OF,
        decision=decision,
    ).to_payload()
    validate_effective_constraints(envelope, submitted_at=AS_OF)


def test_regular_sell_requires_fresh_complete_available_balance_but_not_zero_restricted_balance() -> (
    None
):
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("20"),
        sell_position_evidence=_sell_position(
            available_to_sell_quantity=Decimal("30"),
            restricted_quantity=Decimal("5"),
        ),
    )
    decision = evaluate_execution_order(_rule(), _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT in _decision_codes(
        _order(
            side=ExecutionSide.SELL,
            quantity=Decimal("20"),
            sell_position_evidence=_sell_position(available_to_sell_quantity=Decimal("15")),
        )
    )


def test_regular_sell_fails_closed_when_position_evidence_is_absent_incomplete_or_stale() -> None:
    no_evidence = _order(side=ExecutionSide.SELL)
    incomplete = _order(
        side=ExecutionSide.SELL,
        sell_position_evidence=_sell_position(completeness=SellPositionCompleteness.INCOMPLETE),
    )
    stale = _order(
        side=ExecutionSide.SELL,
        sell_position_evidence=_sell_position(valid_until=AS_OF),
    )

    assert ExecutionDenyCode.POSITION_EVIDENCE_MISSING in _decision_codes(no_evidence)
    assert ExecutionDenyCode.POSITION_EVIDENCE_INCOMPLETE in _decision_codes(incomplete)
    assert ExecutionDenyCode.POSITION_EVIDENCE_EXPIRED in _decision_codes(stale)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (None, ExecutionDenyCode.POSITION_EVIDENCE_MISSING),
        (
            "partial",
            ExecutionDenyCode.POSITION_EVIDENCE_INCOMPLETE,
        ),
        (
            "restricted",
            ExecutionDenyCode.ODD_LOT_HAS_RESTRICTED_BALANCE,
        ),
        (
            "different-quantity",
            ExecutionDenyCode.ODD_LOT_NOT_FULL_SELLABLE_BALANCE,
        ),
        (
            "wrong-security",
            ExecutionDenyCode.POSITION_SECURITY_MISMATCH,
        ),
        (
            "stale",
            ExecutionDenyCode.POSITION_EVIDENCE_EXPIRED,
        ),
    ],
)
def test_sell_to_zero_fails_closed_without_complete_fresh_unrestricted_evidence(
    evidence: str | None,
    expected: ExecutionDenyCode,
) -> None:
    position = None
    if evidence == "partial":
        position = _sell_position(completeness=SellPositionCompleteness.INCOMPLETE)
    elif evidence == "restricted":
        position = _sell_position(restricted_quantity=Decimal("5"))
    elif evidence == "different-quantity":
        position = _sell_position(available_to_sell_quantity=Decimal("20"))
    elif evidence == "wrong-security":
        position = _sell_position(security_id="000001.SZ")
    elif evidence == "stale":
        position = _sell_position(valid_until=AS_OF)
    order = _order(side=ExecutionSide.SELL, quantity=Decimal("15"), sell_position_evidence=position)
    rule = _rule(sell_odd_lot_mode=SellOddLotMode.SELLABLE_BALANCE_TO_ZERO, content_hash="")

    assert expected in _decision_codes(order, rule=rule)


def test_sell_odd_lot_is_denied_when_rule_does_not_enable_sellable_balance_clear() -> None:
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("15"),
        sell_position_evidence=_sell_position(),
    )

    codes = _decision_codes(order)
    assert ExecutionDenyCode.QUANTITY_NOT_ON_STEP in codes
    assert ExecutionDenyCode.POSITION_EVIDENCE_MISSING not in codes


@pytest.mark.parametrize(
    ("available", "quantity"),
    [
        ("150", "50"),
        ("150", "150"),
        ("299", "99"),
        ("299", "100"),
        ("299", "199"),
        ("299", "200"),
        ("299", "299"),
    ],
)
def test_sell_odd_remainder_once_allows_sse_lot_or_single_remainder(
    available: str, quantity: str
) -> None:
    rule = _rule(
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal(quantity),
        sell_position_evidence=_sell_position(available_to_sell_quantity=Decimal(available)),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.ALLOWED


@pytest.mark.parametrize(
    ("available", "quantity"),
    [
        ("150", "25"),
        ("299", "1"),
        ("299", "101"),
        ("299", "198"),
        ("299", "298"),
        ("500", "201"),
    ],
)
def test_sell_odd_remainder_once_rejects_split_odd_lots(available: str, quantity: str) -> None:
    rule = _rule(
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal(quantity),
        sell_position_evidence=_sell_position(available_to_sell_quantity=Decimal(available)),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED


def test_sell_odd_remainder_once_requires_zero_restricted_balance() -> None:
    rule = _rule(
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("99"),
        sell_position_evidence=_sell_position(
            available_to_sell_quantity=Decimal("299"),
            restricted_quantity=Decimal("1"),
        ),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.ODD_LOT_HAS_RESTRICTED_BALANCE in decision.reason_codes


def test_sell_odd_remainder_once_requires_fresh_complete_position_evidence() -> None:
    rule = _rule(
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    position = _sell_position(
        available_to_sell_quantity=Decimal("299"),
        completeness=SellPositionCompleteness.INCOMPLETE,
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("99"),
        sell_position_evidence=position,
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.POSITION_EVIDENCE_INCOMPLETE in decision.reason_codes


@pytest.mark.parametrize(
    ("position_kind", "expected"),
    [
        ("missing", ExecutionDenyCode.POSITION_EVIDENCE_MISSING),
        ("stale", ExecutionDenyCode.POSITION_EVIDENCE_EXPIRED),
        ("over-available", ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT),
    ],
)
def test_sell_odd_remainder_once_fails_closed_on_missing_or_stale_balance(
    position_kind: str, expected: ExecutionDenyCode
) -> None:
    position = None
    quantity = Decimal("99")
    if position_kind == "stale":
        position = _sell_position(
            available_to_sell_quantity=Decimal("299"),
            valid_until=AS_OF,
        )
    elif position_kind == "over-available":
        position = _sell_position(
            available_to_sell_quantity=Decimal("98"),
        )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=quantity,
        sell_position_evidence=position,
    )
    rule = _rule(
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert expected in decision.reason_codes


def test_sell_odd_remainder_once_cannot_bypass_maximum() -> None:
    rule = _rule(
        sell_quantity=_quantity("100", "100", "200"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=Decimal("299"),
        sell_position_evidence=_sell_position(available_to_sell_quantity=Decimal("299")),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.QUANTITY_ABOVE_MAXIMUM in decision.reason_codes


def test_sell_odd_remainder_once_rejects_minimum_step_mismatch() -> None:
    with pytest.raises(ValueError, match="minimum and step"):
        _rule(
            sell_quantity=_quantity("200", "1", "1000"),
            sell_odd_lot_mode=_odd_remainder_once_mode(),
            content_hash="",
        )


def test_sell_odd_remainder_once_does_not_enable_buy_odd_lots() -> None:
    rule = _rule(
        buy_quantity=_quantity("100", "100", "1000"),
        sell_quantity=_quantity("100", "100", "1000"),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    decision = evaluate_execution_order(
        rule,
        _market(),
        _order(side=ExecutionSide.BUY, quantity=Decimal("50")),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.QUANTITY_BELOW_MINIMUM in decision.reason_codes


def test_sell_odd_remainder_once_uses_exact_integer_difference_for_large_shares() -> None:
    available = Decimal(10**128 + 99)
    odd_remainder_order = Decimal(10**128 - 1)
    rule = _rule(
        sell_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("100"),
            step=Decimal("100"),
            maximum=available,
        ),
        sell_odd_lot_mode=_odd_remainder_once_mode(),
        content_hash="",
    )
    order = _order(
        side=ExecutionSide.SELL,
        quantity=odd_remainder_order,
        sell_position_evidence=_sell_position(available_to_sell_quantity=available),
    )

    decision = evaluate_execution_order(rule, _market(), order, AS_OF)

    assert decision.status is ExecutionDecisionStatus.ALLOWED


@pytest.mark.parametrize("position_kind", ("stale", "wrong-security"))
def test_agent_accepts_domain_allowed_buy_with_unused_sell_position(
    position_kind: str,
) -> None:
    rule = _rule()
    market = _market()
    position = _sell_position(
        valid_until=AS_OF if position_kind == "stale" else AS_OF + timedelta(minutes=1),
        security_id="000001.SZ" if position_kind == "wrong-security" else "600000.SH",
    )
    order = _order(
        side=ExecutionSide.BUY,
        sell_position_evidence=position,
    )
    decision = evaluate_execution_order(rule, market, order, AS_OF)
    assert decision.status is ExecutionDecisionStatus.ALLOWED
    envelope = ExecutionConstraintsEvaluation(
        rule=rule,
        market_evidence=market,
        order=order,
        as_of=AS_OF,
        decision=decision,
    ).to_payload()

    validate_effective_constraints(envelope, submitted_at=AS_OF)


def test_agent_accepts_domain_allowed_canonical_130_digit_decimal() -> None:
    expanded_quantity = Decimal("1E+129")
    rule = _rule(
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=expanded_quantity
        ),
        content_hash="",
    )
    market = _market()
    order = _order(quantity=expanded_quantity)
    decision = evaluate_execution_order(rule, market, order, AS_OF)
    assert decision.status is ExecutionDecisionStatus.ALLOWED
    envelope = ExecutionConstraintsEvaluation(
        rule=rule,
        market_evidence=market,
        order=order,
        as_of=AS_OF,
        decision=decision,
    ).to_payload()

    validate_effective_constraints(envelope, submitted_at=AS_OF)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("10.01", ExecutionDenyCode.LIMIT_PRICE_NOT_ON_TICK),
        ("8.95", ExecutionDenyCode.LIMIT_PRICE_OUTSIDE_BOUNDARY),
        ("11.05", ExecutionDenyCode.LIMIT_PRICE_OUTSIDE_BOUNDARY),
    ],
)
def test_limit_price_must_obey_tick_and_limited_boundary(
    price: str, expected: ExecutionDenyCode
) -> None:
    assert expected in _decision_codes(_order(limit_price=Decimal(price)))


def test_unknown_boundary_denies() -> None:
    market = _market(
        price_boundary_mode=PriceBoundaryMode.UNKNOWN,
        lower_limit_price=None,
        upper_limit_price=None,
        content_hash="",
    )
    assert ExecutionDenyCode.PRICE_BOUNDARY_UNKNOWN in _decision_codes(_order(), market=market)


def test_unrestricted_boundary_is_explicit_and_still_enforces_tick() -> None:
    market = _market(
        price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
        lower_limit_price=None,
        upper_limit_price=None,
        content_hash="",
    )

    assert (
        evaluate_execution_order(_rule(), market, _order(), AS_OF).status
        is ExecutionDecisionStatus.ALLOWED
    )
    assert ExecutionDenyCode.LIMIT_PRICE_NOT_ON_TICK in _decision_codes(
        _order(limit_price=Decimal("10.01")), market=market
    )


def test_reference_price_must_obey_tick_and_limited_boundary() -> None:
    unticked = _market(reference_price=Decimal("10.01"), content_hash="")
    outside = _market(reference_price=Decimal("11.05"), content_hash="")

    assert ExecutionDenyCode.REFERENCE_PRICE_NOT_ON_TICK in _decision_codes(
        _order(), market=unticked
    )
    assert ExecutionDenyCode.REFERENCE_PRICE_OUTSIDE_BOUNDARY in _decision_codes(
        _order(), market=outside
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (SecurityTradingState.SUSPENDED, ExecutionDenyCode.SECURITY_SUSPENDED),
        (SecurityTradingState.DELISTED, ExecutionDenyCode.SECURITY_DELISTED),
        (SecurityTradingState.UNKNOWN, ExecutionDenyCode.SECURITY_STATE_UNKNOWN),
    ],
)
def test_security_state_is_independent_of_open_session(
    state: SecurityTradingState,
    expected: ExecutionDenyCode,
) -> None:
    market = _market(security_state=state, content_hash="")

    assert expected in _decision_codes(_order(), market=market)


@pytest.mark.parametrize(
    ("session_state", "expected"),
    [
        (SessionState.CLOSED, ExecutionDenyCode.SESSION_CLOSED),
        (SessionState.UNKNOWN, ExecutionDenyCode.SESSION_STATE_UNKNOWN),
    ],
)
def test_session_state_must_be_explicitly_open(
    session_state: SessionState,
    expected: ExecutionDenyCode,
) -> None:
    market = _market(session_state=session_state, content_hash="")

    assert expected in _decision_codes(_order(), market=market)


def test_open_session_still_denies_outside_time_or_trading_date() -> None:
    assert ExecutionDenyCode.OUTSIDE_SESSION in _decision_codes(
        _order(),
        market=_market(session_open_at=AS_OF + timedelta(minutes=1), content_hash=""),
    )
    assert ExecutionDenyCode.OUTSIDE_TRADING_DATE in _decision_codes(
        _order(), market=_market(trading_date=TRADING_DATE + timedelta(days=1), content_hash="")
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("rule", ExecutionDenyCode.RULE_SOURCE_EXPIRED),
        ("rule-not-effective", ExecutionDenyCode.RULE_NOT_YET_EFFECTIVE),
        ("calendar", ExecutionDenyCode.CALENDAR_EVIDENCE_EXPIRED),
        ("market", ExecutionDenyCode.MARKET_EVIDENCE_EXPIRED),
    ],
)
def test_rule_calendar_and_market_evidence_expiry_fail_closed(
    source: str,
    expected: ExecutionDenyCode,
) -> None:
    rule = (
        _rule(valid_until=AS_OF, content_hash="")
        if source == "rule"
        else (
            _rule(effective_from=AS_OF + timedelta(seconds=1), content_hash="")
            if source == "rule-not-effective"
            else _rule()
        )
    )
    market = _market(
        calendar_valid_until=AS_OF if source == "calendar" else AS_OF + timedelta(days=1),
        market_valid_until=AS_OF if source == "market" else AS_OF + timedelta(minutes=1),
        content_hash="",
    )

    assert expected in _decision_codes(_order(), rule=rule, market=market)


def test_unavailable_future_source_evidence_is_denied() -> None:
    rule = _rule(source_available_at=AS_OF + timedelta(seconds=1), content_hash="")
    market = _market(calendar_available_at=AS_OF + timedelta(seconds=1), content_hash="")

    assert ExecutionDenyCode.RULE_SOURCE_NOT_YET_AVAILABLE in _decision_codes(_order(), rule=rule)
    assert ExecutionDenyCode.CALENDAR_EVIDENCE_NOT_YET_AVAILABLE in _decision_codes(
        _order(), market=market
    )


def test_rule_market_order_and_position_security_ids_must_match_exactly() -> None:
    assert ExecutionDenyCode.RULE_MARKET_SECURITY_MISMATCH in _decision_codes(
        _order(), market=_market(security_id="600001.SH", content_hash="")
    )
    assert ExecutionDenyCode.ORDER_SECURITY_MISMATCH in _decision_codes(
        _order(security_id="600002.SH")
    )


def test_sell_position_evidence_must_be_bound_to_the_exact_order_account() -> None:
    foreign_account_position = _sell_position(
        account_id=8,
        available_to_sell_quantity=Decimal("20"),
    )
    order = _order(
        account_id=7,
        side=ExecutionSide.SELL,
        quantity=Decimal("20"),
        sell_position_evidence=foreign_account_position,
    )

    assert "POSITION_ACCOUNT_MISMATCH" in {code.value for code in _decision_codes(order)}


@pytest.mark.parametrize(
    ("market_field", "market_value", "expected_code"),
    [
        ("market", "SZ", "RULE_MARKET_MISMATCH"),
        ("board", "STAR", "RULE_BOARD_MISMATCH"),
    ],
)
def test_market_identity_must_match_the_exact_rule(
    market_field: str,
    market_value: str,
    expected_code: str,
) -> None:
    market = _market(**{market_field: market_value, "content_hash": ""})

    assert expected_code in {code.value for code in _decision_codes(_order(), market=market)}


def test_canonical_hashes_normalize_decimal_and_utc_and_detect_tampering() -> None:
    first = _rule()
    second = _rule(
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("10.0"), step=Decimal("10.00"), maximum=Decimal("1000.0")
        ),
        source_observed_at=(AS_OF - timedelta(hours=2)).astimezone(timezone(timedelta(hours=8))),
        source_available_at=(AS_OF - timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))),
        effective_from=(AS_OF - timedelta(days=1)).astimezone(timezone(timedelta(hours=8))),
        valid_until=(AS_OF + timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))),
    )

    assert first.content_hash == second.content_hash
    assert _rule(content_hash=first.content_hash).content_hash == first.content_hash
    assert first.to_payload()["buy_quantity"] == {
        "minimum": "10",
        "step": "10",
        "maximum": "1000",
    }
    assert first.to_payload()["source_observed_at"].endswith("Z")  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="content_hash"):
        replace(first, content_hash="e" * 64)

    evidence = _market()
    assert _market(content_hash=evidence.content_hash).content_hash == evidence.content_hash
    assert evidence.to_payload()["session_open_at"] == "2026-10-16T01:30:00Z"


def test_all_wire_dtos_expose_exact_payload_keys_and_decision_omits_duplicate_clock() -> None:
    rule = _rule()
    market = _market()
    order = _order()
    decision = evaluate_execution_order(rule, market, order, AS_OF)
    position = _sell_position()

    assert set(rule.to_payload()) == {
        "rule_id",
        "rule_version",
        "security_id",
        "market",
        "board",
        "buy_quantity",
        "sell_quantity",
        "sell_odd_lot_mode",
        "price_tick",
        "rule_source_id",
        "rule_source_version",
        "rule_source_hash",
        "source_observed_at",
        "source_available_at",
        "effective_from",
        "valid_until",
        "content_hash",
    }
    assert set(market.to_payload()) == {
        "security_id",
        "market",
        "board",
        "trading_date",
        "calendar_id",
        "calendar_version",
        "calendar_source_hash",
        "calendar_observed_at",
        "calendar_available_at",
        "calendar_valid_until",
        "session_id",
        "session_timezone",
        "session_open_at",
        "session_close_at",
        "session_state",
        "security_state",
        "market_source_id",
        "market_source_version",
        "market_source_hash",
        "price_boundary_mode",
        "lower_limit_price",
        "upper_limit_price",
        "reference_price",
        "market_observed_at",
        "market_available_at",
        "market_valid_until",
        "content_hash",
    }
    assert set(position.to_payload()) == {
        "security_id",
        "account_id",
        "available_to_sell_quantity",
        "restricted_quantity",
        "completeness",
        "source_id",
        "source_version",
        "source_hash",
        "observed_at",
        "available_at",
        "valid_until",
    }
    assert set(order.to_payload()) == {
        "order_id",
        "account_id",
        "security_id",
        "side",
        "quantity",
        "limit_price",
        "sell_position_evidence",
    }
    assert set(decision.to_payload()) == {
        "status",
        "reason_codes",
        "order_id",
        "rule_content_hash",
        "market_evidence_content_hash",
    }
    assert decision.to_payload()["status"] == "ALLOWED"


@pytest.mark.parametrize(
    "changes",
    [
        {"rule_source_hash": "A" * 64},
        {"source_observed_at": datetime(2026, 10, 16, 0)},
        {"price_tick": Decimal("0")},
    ],
)
def test_rule_rejects_invalid_identity_time_hash_and_quantity_ranges(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _rule(**changes)


def test_quantity_constraints_reject_nonpositive_step_and_reversed_range() -> None:
    with pytest.raises(ValueError, match="step"):
        ExecutionQuantityConstraint(
            minimum=Decimal("10"), step=Decimal("0"), maximum=Decimal("100")
        )
    with pytest.raises(ValueError, match="maximum"):
        ExecutionQuantityConstraint(minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("5"))


@pytest.mark.parametrize(
    "build",
    [
        lambda: _rule(rule_id=" bad token "),
        lambda: _rule(sell_odd_lot_mode="FORBID"),
        lambda: _rule(buy_quantity=None),
        lambda: _rule(sell_quantity=None),
        lambda: _rule(source_observed_at=AS_OF, source_available_at=AS_OF - timedelta(seconds=1)),
        lambda: _rule(effective_from=AS_OF, valid_until=AS_OF),
        lambda: _sell_position(
            completeness=SellPositionCompleteness.COMPLETE,
            available_to_sell_quantity=None,
        ),
        lambda: _sell_position(account_id=0),
        lambda: _sell_position(account_id=True),
        lambda: _market(market=" invalid token "),
        lambda: _market(board=""),
        lambda: _sell_position(available_at=AS_OF, valid_until=AS_OF),
        lambda: _market(trading_date=datetime(2026, 10, 16)),
        lambda: _market(
            calendar_available_at=AS_OF,
            calendar_valid_until=AS_OF,
        ),
        lambda: _market(market_available_at=AS_OF, market_valid_until=AS_OF),
        lambda: _market(session_open_at=AS_OF, session_close_at=AS_OF),
        lambda: _market(
            price_boundary_mode=PriceBoundaryMode.LIMITED,
            lower_limit_price=None,
            upper_limit_price=Decimal("11"),
        ),
        lambda: _market(
            price_boundary_mode=PriceBoundaryMode.LIMITED,
            lower_limit_price=Decimal("12"),
            upper_limit_price=Decimal("11"),
        ),
        lambda: _order(order_id=" invalid token "),
        lambda: _order(quantity=20.0),
        lambda: _order(side="BUY"),
        lambda: _order(sell_position_evidence=object()),
    ],
)
def test_typed_contracts_reject_noncanonical_shapes(build: Callable[[], object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        build()


def test_sell_position_payload_keeps_unknown_quantities_explicit_as_null() -> None:
    position = _sell_position(
        completeness=SellPositionCompleteness.UNKNOWN,
        available_to_sell_quantity=None,
        restricted_quantity=None,
    )

    payload = position.to_payload()
    assert payload["account_id"] == 7
    assert payload["available_to_sell_quantity"] is None
    assert payload["restricted_quantity"] is None


def test_position_zero_quantities_with_large_redundant_exponents_normalize_as_zero() -> None:
    zero = Decimal("0E-1000000")
    position = _sell_position(
        available_to_sell_quantity=zero,
        restricted_quantity=zero,
    )

    payload = position.to_payload()
    assert payload["available_to_sell_quantity"] == "0"
    assert payload["restricted_quantity"] == "0"


@pytest.mark.parametrize(
    "build",
    [
        lambda: ExecutionQuantityConstraint(
            minimum=Decimal("1.5"), step=Decimal("1"), maximum=Decimal("100")
        ),
        lambda: ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("0.5"), maximum=Decimal("100")
        ),
        lambda: ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=Decimal("100.5")
        ),
        lambda: _order(quantity=Decimal("1.5")),
        lambda: _sell_position(available_to_sell_quantity=Decimal("1.5")),
    ],
)
def test_a_share_share_quantities_must_be_integer_decimals(build: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match="whole share"):
        build()


def test_large_exact_share_and_price_values_do_not_raise_decimal_context_errors() -> None:
    large_quantity = Decimal("999999999999999999999999999998")
    large_price = Decimal("1234567890123456789012345678.90")
    rule = _rule(
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("3"), maximum=large_quantity
        ),
        price_tick=Decimal("0.05"),
        content_hash="",
    )
    market = _market(
        lower_limit_price=Decimal("0.05"),
        upper_limit_price=large_price,
        reference_price=large_price,
        content_hash="",
    )
    decision = evaluate_execution_order(
        rule,
        market,
        _order(quantity=large_quantity, limit_price=large_price),
        AS_OF,
    )

    assert ExecutionDenyCode.QUANTITY_NOT_ON_STEP in decision.reason_codes
    assert ExecutionDenyCode.LIMIT_PRICE_NOT_ON_TICK not in decision.reason_codes


def test_decimal_wire_bound_uses_canonical_expanded_text_length() -> None:
    expanded = Decimal("1E+128")
    rule = _rule(
        buy_quantity=ExecutionQuantityConstraint(
            minimum=Decimal("1"), step=Decimal("1"), maximum=expanded
        ),
        content_hash="",
    )
    payload = rule.to_payload()
    buy_quantity_payload = payload["buy_quantity"]
    assert isinstance(buy_quantity_payload, dict)
    encoded_maximum = buy_quantity_payload["maximum"]
    assert encoded_maximum == "1" + ("0" * 128)
    assert len(encoded_maximum) == 129

    with pytest.raises(ValueError, match="wire-text length"):
        ExecutionQuantityConstraint(
            minimum=Decimal("1"),
            step=Decimal("1"),
            maximum=Decimal("1E+257"),
        )


def test_evaluator_revalidates_nested_typed_values_hashes_and_position_evidence() -> None:
    rule = _rule()
    object.__setattr__(rule.buy_quantity, "step", Decimal("0"))
    with pytest.raises(ValueError, match="step"):
        evaluate_execution_order(rule, _market(), _order(), AS_OF)

    position = _sell_position()
    sell_order = _order(side=ExecutionSide.SELL, sell_position_evidence=position)
    object.__setattr__(position, "restricted_quantity", Decimal("-1"))
    with pytest.raises(ValueError, match="restricted_quantity"):
        evaluate_execution_order(_rule(), _market(), sell_order, AS_OF)


def test_market_rejects_inconsistent_boundary_modes_and_bad_timezone() -> None:
    with pytest.raises(ValueError, match="UNRESTRICTED"):
        _market(
            price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
            lower_limit_price=Decimal("9"),
            upper_limit_price=None,
        )
    with pytest.raises(ValueError, match="timezone"):
        _market(session_timezone="Missing/Zone")


def test_contracts_and_decisions_are_immutable_and_order_fields_are_typed() -> None:
    rule = _rule()
    decision = evaluate_execution_order(rule, _market(), _order(), AS_OF)

    with pytest.raises(FrozenInstanceError):
        rule.rule_version = "changed"  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError)):
        _order(account_id=True)
    with pytest.raises((TypeError, ValueError)):
        evaluate_execution_order(rule, _market(), _order(), datetime(2026, 10, 16, 1, 45))
    assert decision.to_payload()["status"] == "ALLOWED"


@pytest.mark.parametrize(
    ("status", "reason_codes"),
    [
        (ExecutionDecisionStatus.ALLOWED, (ExecutionDenyCode.SECURITY_SUSPENDED,)),
        (ExecutionDecisionStatus.DENIED, ()),
        (ExecutionDecisionStatus.DENIED, (ExecutionDenyCode.SECURITY_SUSPENDED,) * 2),
        (ExecutionDecisionStatus.DENIED, ("SECURITY_SUSPENDED",)),
    ],
)
def test_decision_rejects_invalid_status_reason_combinations(
    status: ExecutionDecisionStatus,
    reason_codes: tuple[ExecutionDenyCode, ...] | tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        ExecutionTradingDecision(
            status=status,
            reason_codes=reason_codes,  # type: ignore[arg-type]
            order_id="synthetic-order-1",
            rule_content_hash="a" * 64,
            market_evidence_content_hash="b" * 64,
            evaluated_at=AS_OF,
        )


@pytest.mark.parametrize(
    "arguments",
    [
        (None, _market(), _order(), AS_OF),
        (_rule(), None, _order(), AS_OF),
        (_rule(), _market(), None, AS_OF),
    ],
)
def test_evaluator_rejects_wrong_contract_types(
    arguments: tuple[object, object, object, datetime],
) -> None:
    with pytest.raises(ValueError):
        evaluate_execution_order(*arguments)  # type: ignore[arg-type]
