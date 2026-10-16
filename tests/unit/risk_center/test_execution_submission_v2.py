from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionDecisionV2,
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
    ExecutionSubmissionV2ValidationError,
    SubmissionV2DenyCode,
    _cage_reasons,
    _canonical_hash,
    _submission_reason_for_cage,
    evaluate_execution_submission,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionContractValidationError,
    ExecutionDecisionStatus,
    ExecutionDenyCode,
    ExecutionMarketEvidence,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    PriceBoundaryMode,
    SecurityTradingState,
    SellOddLotMode,
    SellPositionCompleteness,
    SellPositionEvidence,
    SessionState,
)
from apps.risk_center.domain.price_submission_range import (
    PriceQuoteSource,
    PriceRoundingMode,
    PriceSubmissionRangeDecision,
    PriceSubmissionRangeReason,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeStatus,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)

AS_OF = datetime(2026, 10, 16, 1, 45, tzinfo=UTC)
TRADING_DATE = date(2026, 10, 16)


def _quantity() -> ExecutionQuantityConstraint:
    return ExecutionQuantityConstraint(
        minimum=Decimal("10"),
        step=Decimal("10"),
        maximum=Decimal("1000"),
    )


def _base_rule(
    *, board: str = "MAIN", price_tick: Decimal = Decimal("0.05")
) -> AShareExecutionRule:
    return AShareExecutionRule(
        rule_id=f"synthetic-rule-{board.lower()}-v1",
        rule_version="fixture-v1",
        security_id="688001.SH" if board == "STAR" else "600000.SH",
        market="SH",
        board=board,
        buy_quantity=_quantity(),
        sell_quantity=_quantity(),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=price_tick,
        rule_source_id="synthetic-rule-source",
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=AS_OF - timedelta(hours=2),
        source_available_at=AS_OF - timedelta(hours=1),
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(hours=1),
    )


def _price_rule(
    *, board: str = "MAIN", price_tick: Decimal = Decimal("0.05")
) -> PriceSubmissionRangeRule:
    is_star = board == "STAR"
    return PriceSubmissionRangeRule(
        market="SH",
        board=board,
        price_tick=price_tick,
        buy_deviation_ratio=Decimal("0.02"),
        sell_deviation_ratio=Decimal("0.02"),
        buy_widening_ticks=0 if is_star else 10,
        sell_widening_ticks=0 if is_star else 10,
        minimum_distance_ticks=1,
        lower_floor_ticks=1,
        rounding_mode=PriceRoundingMode.HALF_UP,
    )


def _rule_v2(
    *,
    board: str = "MAIN",
    price_tick: Decimal = Decimal("0.05"),
    allowed_stages: tuple[PriceSubmissionStage, ...] = (PriceSubmissionStage.CONTINUOUS,),
) -> ExecutionSubmissionRuleV2:
    return ExecutionSubmissionRuleV2(
        execution_rule_v1=_base_rule(board=board, price_tick=price_tick),
        price_submission_range=_price_rule(board=board, price_tick=price_tick),
        allowed_stages=allowed_stages,
    )


def _market_v1(
    *,
    board: str = "MAIN",
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
    lower_limit_price: Decimal | None = Decimal("9.00"),
    upper_limit_price: Decimal | None = Decimal("11.00"),
    market_observed_at: datetime = AS_OF - timedelta(seconds=2),
    market_available_at: datetime = AS_OF - timedelta(seconds=1),
    market_valid_until: datetime = AS_OF + timedelta(minutes=1),
) -> ExecutionMarketEvidence:
    return ExecutionMarketEvidence(
        security_id="688001.SH" if board == "STAR" else "600000.SH",
        market="SH",
        board=board,
        trading_date=TRADING_DATE,
        calendar_id="synthetic-calendar",
        calendar_version="fixture-v1",
        calendar_source_hash="b" * 64,
        calendar_observed_at=AS_OF - timedelta(days=1),
        calendar_available_at=AS_OF - timedelta(hours=1),
        calendar_valid_until=AS_OF + timedelta(days=1),
        session_id="synthetic-day-session",
        session_timezone="Asia/Shanghai",
        session_open_at=AS_OF - timedelta(minutes=30),
        session_close_at=AS_OF + timedelta(hours=2),
        session_state=SessionState.OPEN,
        security_state=SecurityTradingState.TRADING,
        market_source_id="synthetic-quote-source",
        market_source_version="fixture-v1",
        market_source_hash="c" * 64,
        price_boundary_mode=price_boundary_mode,
        lower_limit_price=lower_limit_price,
        upper_limit_price=upper_limit_price,
        reference_price=Decimal("10.00"),
        market_observed_at=market_observed_at,
        market_available_at=market_available_at,
        market_valid_until=market_valid_until,
    )


def _quote(value: str | None) -> QuoteValue:
    if value is None:
        return QuoteValue(state=QuoteValueState.CONFIRMED_ABSENT, value=None)
    return QuoteValue(state=QuoteValueState.PRESENT, value=Decimal(value))


def _unknown_quote() -> QuoteValue:
    return QuoteValue(state=QuoteValueState.UNKNOWN, value=None)


def _market_v2(
    *,
    board: str = "MAIN",
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
    lower_limit_price: Decimal | None = Decimal("9.00"),
    upper_limit_price: Decimal | None = Decimal("11.00"),
    stage: PriceSubmissionStage = PriceSubmissionStage.CONTINUOUS,
    ask: QuoteValue | None = None,
    bid: QuoteValue | None = None,
    latest: QuoteValue | None = None,
    previous_close: QuoteValue | None = None,
    market_observed_at: datetime = AS_OF - timedelta(seconds=2),
    market_available_at: datetime = AS_OF - timedelta(seconds=1),
    market_valid_until: datetime = AS_OF + timedelta(minutes=1),
) -> ExecutionSubmissionMarketV2:
    return ExecutionSubmissionMarketV2(
        market_evidence_v1=_market_v1(
            board=board,
            price_boundary_mode=price_boundary_mode,
            lower_limit_price=lower_limit_price,
            upper_limit_price=upper_limit_price,
            market_observed_at=market_observed_at,
            market_available_at=market_available_at,
            market_valid_until=market_valid_until,
        ),
        stage=stage,
        ask=ask if ask is not None else _quote("10.00"),
        bid=bid if bid is not None else _quote("10.00"),
        latest=latest if latest is not None else _quote(None),
        previous_close=(previous_close if previous_close is not None else _quote(None)),
    )


def _sell_position() -> SellPositionEvidence:
    return SellPositionEvidence(
        security_id="600000.SH",
        account_id=7,
        available_to_sell_quantity=Decimal("100"),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="synthetic-position-source",
        source_version="fixture-v1",
        source_hash="d" * 64,
        observed_at=AS_OF - timedelta(seconds=2),
        available_at=AS_OF - timedelta(seconds=1),
        valid_until=AS_OF + timedelta(minutes=1),
    )


def _order(
    *,
    side: ExecutionSide = ExecutionSide.BUY,
    limit_price: str = "10.00",
) -> ExecutionOrder:
    return ExecutionOrder(
        order_id="synthetic-order-v2",
        account_id=7,
        security_id="600000.SH",
        side=side,
        quantity=Decimal("20"),
        limit_price=Decimal(limit_price),
        sell_position_evidence=_sell_position() if side is ExecutionSide.SELL else None,
    )


@pytest.mark.parametrize(
    ("board", "tick", "buy_boundary"),
    [("MAIN", "0.05", "10.50"), ("STAR", "0.01", "10.20")],
)
def test_v2_board_rules_bind_price_cage_without_changing_v1_hash(
    board: str, tick: str, buy_boundary: str
) -> None:
    v1_rule = _base_rule(board=board, price_tick=Decimal(tick))
    rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=v1_rule,
        price_submission_range=_price_rule(board=board, price_tick=Decimal(tick)),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )
    market = _market_v2(board=board)
    if board == "STAR":
        order = ExecutionOrder(
            order_id="synthetic-order-v2",
            account_id=7,
            security_id="688001.SH",
            side=ExecutionSide.BUY,
            quantity=Decimal("20"),
            limit_price=Decimal(buy_boundary),
            sell_position_evidence=None,
        )
    else:
        order = _order(limit_price=buy_boundary)

    decision = evaluate_execution_submission(rule, market, order, AS_OF)
    payload = rule.to_payload()

    assert rule.execution_rule_v1.content_hash == v1_rule.content_hash
    assert payload["execution_rule_v1"]["content_hash"] == v1_rule.content_hash
    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert decision.rule_content_hash == rule.content_hash
    assert decision.market_evidence_content_hash == market.content_hash


def test_v2_payloads_include_all_fields_and_preserve_nested_v1_hashes() -> None:
    rule = _rule_v2()
    market = _market_v2()
    rule_payload = rule.to_payload()
    market_payload = market.to_payload()

    assert set(rule_payload) == {
        "execution_rule_v1",
        "price_submission_range",
        "allowed_stages",
        "content_hash",
    }
    assert rule_payload["execution_rule_v1"]["content_hash"] == (
        rule.execution_rule_v1.content_hash
    )
    assert set(market_payload) == {
        "market_evidence_v1",
        "stage",
        "ask",
        "bid",
        "latest",
        "previous_close",
        "content_hash",
    }
    assert market_payload["market_evidence_v1"]["content_hash"] == (
        market.market_evidence_v1.content_hash
    )


def test_canonical_hash_rejects_values_outside_json_domain() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        _canonical_hash({"unsupported": object()})


@pytest.mark.parametrize("content_hash", [123, "f" * 64])
def test_v2_rule_rejects_malformed_or_mismatched_supplied_hash(
    content_hash: object,
) -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=_base_rule(),
            price_submission_range=_price_rule(),
            allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
            content_hash=content_hash,  # type: ignore[arg-type]
        )


def test_v2_rule_requires_exact_nested_contract_types() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=object(),  # type: ignore[arg-type]
            price_submission_range=_price_rule(),
            allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
        )
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=_base_rule(),
            price_submission_range=object(),  # type: ignore[arg-type]
            allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
        )


@pytest.mark.parametrize(
    ("price_market", "price_board", "price_tick"),
    [("SZ", "MAIN", "0.05"), ("SH", "STAR", "0.05"), ("SH", "MAIN", "0.01")],
)
def test_v2_rule_rejects_mismatched_market_board_or_tick(
    price_market: str, price_board: str, price_tick: str
) -> None:
    configured = _price_rule(board=price_board, price_tick=Decimal(price_tick))
    object.__setattr__(configured, "market", price_market)
    rule = _base_rule()

    with pytest.raises(ValueError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=rule,
            price_submission_range=configured,
            allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
        )


@pytest.mark.parametrize(
    "stages",
    [
        (PriceSubmissionStage.CONTINUOUS, PriceSubmissionStage.CONTINUOUS),
        (PriceSubmissionStage.OPENING_AUCTION,),
        (PriceSubmissionStage.UNKNOWN,),
    ],
)
def test_v2_rule_rejects_duplicate_or_unsupported_allowed_stages(
    stages: tuple[PriceSubmissionStage, ...],
) -> None:
    with pytest.raises(ValueError):
        _rule_v2(allowed_stages=stages)


def test_v2_rule_requires_tuple_allowed_stages_and_exact_stage_types() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=_base_rule(),
            price_submission_range=_price_rule(),
            allowed_stages=[PriceSubmissionStage.CONTINUOUS],  # type: ignore[arg-type]
        )
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=_base_rule(),
            price_submission_range=_price_rule(),
            allowed_stages=("CONTINUOUS",),  # type: ignore[arg-type]
        )


def test_v2_rule_rejects_nested_contract_mutation_on_revalidation() -> None:
    rule = _rule_v2()
    object.__setattr__(rule.execution_rule_v1, "market", "SZ")

    with pytest.raises(ExecutionContractValidationError):
        rule.__post_init__()


def test_v2_rule_wraps_invalid_price_rule_revalidation() -> None:
    rule = _rule_v2()
    object.__setattr__(rule.price_submission_range, "rounding_mode", "HALF_UP")

    with pytest.raises(ExecutionSubmissionV2ValidationError):
        rule.__post_init__()


@pytest.mark.parametrize(
    "stage",
    [
        PriceSubmissionStage.OPENING_AUCTION,
        PriceSubmissionStage.CLOSING_AUCTION,
        PriceSubmissionStage.HALTED,
        PriceSubmissionStage.UNKNOWN,
    ],
)
def test_noncontinuous_or_unknown_phase_is_denied_even_when_cage_is_not_applicable(
    stage: PriceSubmissionStage,
) -> None:
    decision = evaluate_execution_submission(_rule_v2(), _market_v2(stage=stage), _order(), AS_OF)

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED in decision.reason_codes


def test_empty_allowed_stages_explicitly_disables_submission() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(allowed_stages=()), _market_v2(), _order(), AS_OF
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED in decision.reason_codes


def test_unknown_reference_quote_blocks_fallback() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(ask=_unknown_quote(), bid=_quote("10.00")),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_UNKNOWN in decision.reason_codes


def test_confirmed_missing_reference_quotes_deny_without_inventing_a_price() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(ask=_quote(None), bid=_quote(None)),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_MISSING in decision.reason_codes


def test_reference_quote_not_on_tick_has_a_stable_v2_reason() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(), _market_v2(ask=_quote("10.01")), _order(), AS_OF
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK in decision.reason_codes


@pytest.mark.parametrize(
    ("side", "quote_source", "quote_value", "limit_price"),
    [
        (ExecutionSide.BUY, "ask", "99.00", "10.50"),
        (ExecutionSide.SELL, "bid", "1.00", "9.50"),
    ],
)
def test_selected_cage_reference_must_fit_limited_daily_boundary(
    side: ExecutionSide,
    quote_source: str,
    quote_value: str,
    limit_price: str,
) -> None:
    quote = _quote(quote_value)
    market = _market_v2(
        ask=quote if quote_source == "ask" else _quote("10.00"),
        bid=quote if quote_source == "bid" else _quote("10.00"),
    )
    decision = evaluate_execution_submission(
        _rule_v2(), market, _order(side=side, limit_price=limit_price), AS_OF
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY in decision.reason_codes


def test_unselected_unknown_fallback_quote_does_not_block_valid_reference() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(ask=_quote("10.00"), bid=_unknown_quote()),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert decision.reason_codes == ()


def test_unrestricted_daily_boundary_does_not_invent_a_reference_price_band() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(
            ask=_quote("99.00"),
            price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
            lower_limit_price=None,
            upper_limit_price=None,
        ),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert (
        SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY
        not in decision.reason_codes
    )


def test_unknown_daily_boundary_remains_denied_by_v1() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(
            price_boundary_mode=PriceBoundaryMode.UNKNOWN,
            lower_limit_price=None,
            upper_limit_price=None,
        ),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.PRICE_BOUNDARY_UNKNOWN in decision.reason_codes


@pytest.mark.parametrize(
    ("side", "limit_price"),
    [(ExecutionSide.BUY, "10.50"), (ExecutionSide.SELL, "9.50")],
)
def test_limit_price_may_equal_the_inclusive_submission_boundary(
    side: ExecutionSide, limit_price: str
) -> None:
    decision = evaluate_execution_submission(
        _rule_v2(), _market_v2(), _order(side=side, limit_price=limit_price), AS_OF
    )

    assert decision.status is ExecutionDecisionStatus.ALLOWED
    assert decision.reason_codes == ()


@pytest.mark.parametrize(
    ("side", "limit_price"),
    [(ExecutionSide.BUY, "10.55"), (ExecutionSide.SELL, "9.45")],
)
def test_limit_inside_daily_boundary_but_outside_submission_cage_is_denied(
    side: ExecutionSide, limit_price: str
) -> None:
    decision = evaluate_execution_submission(
        _rule_v2(), _market_v2(), _order(side=side, limit_price=limit_price), AS_OF
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert SubmissionV2DenyCode.LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE in decision.reason_codes
    assert ExecutionDenyCode.LIMIT_PRICE_OUTSIDE_BOUNDARY not in decision.reason_codes


def test_expired_market_quote_source_is_blocked_by_v1_evidence_time_check() -> None:
    decision = evaluate_execution_submission(
        _rule_v2(),
        _market_v2(
            market_observed_at=AS_OF - timedelta(minutes=2),
            market_available_at=AS_OF - timedelta(minutes=1),
            market_valid_until=AS_OF - timedelta(seconds=1),
        ),
        _order(),
        AS_OF,
    )

    assert decision.status is ExecutionDecisionStatus.DENIED
    assert ExecutionDenyCode.MARKET_EVIDENCE_EXPIRED in decision.reason_codes


def test_v2_decision_payload_keeps_v1_five_key_shape_with_outer_hashes() -> None:
    rule = _rule_v2()
    market = _market_v2()
    decision = evaluate_execution_submission(rule, market, _order(), AS_OF)

    assert tuple(decision.to_payload()) == (
        "status",
        "reason_codes",
        "order_id",
        "rule_content_hash",
        "market_evidence_content_hash",
    )
    assert decision.to_payload()["rule_content_hash"] == rule.content_hash
    assert decision.to_payload()["market_evidence_content_hash"] == market.content_hash


def test_rule_market_and_decision_hashes_are_deterministic_and_bind_all_fields() -> None:
    rule = _rule_v2()
    same_rule = _rule_v2()
    disabled_rule = _rule_v2(allowed_stages=())
    market = _market_v2()
    changed_market = _market_v2(latest=_quote("9.95"))

    assert rule.content_hash == same_rule.content_hash
    assert rule.content_hash != disabled_rule.content_hash
    assert market.content_hash != changed_market.content_hash
    assert evaluate_execution_submission(rule, market, _order(), AS_OF).to_payload() == (
        evaluate_execution_submission(same_rule, _market_v2(), _order(), AS_OF).to_payload()
    )


@pytest.mark.parametrize("target", ["rule", "market"])
def test_evaluator_revalidates_content_hash_after_frozen_input_mutation(
    target: str,
) -> None:
    rule = _rule_v2()
    market = _market_v2()
    if target == "rule":
        object.__setattr__(rule, "allowed_stages", ())
    else:
        object.__setattr__(market, "stage", PriceSubmissionStage.HALTED)

    with pytest.raises(ValueError):
        evaluate_execution_submission(rule, market, _order(), AS_OF)


def test_v2_contract_rejects_naive_evaluation_time() -> None:
    with pytest.raises(ValueError):
        evaluate_execution_submission(
            _rule_v2(), _market_v2(), _order(), datetime(2026, 10, 16, 1, 45)
        )


@pytest.mark.parametrize("input_name", ["rule", "market", "order"])
def test_evaluator_requires_exact_public_input_types(input_name: str) -> None:
    rule: object = _rule_v2()
    market: object = _market_v2()
    order: object = _order()
    if input_name == "rule":
        rule = object()
    elif input_name == "market":
        market = object()
    else:
        order = object()

    with pytest.raises(ExecutionSubmissionV2ValidationError):
        evaluate_execution_submission(
            rule,
            market,
            order,
            AS_OF,  # type: ignore[arg-type]
        )


def test_invalid_stage_type_is_rejected_at_market_construction() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        _market_v2(stage="CONTINUOUS")  # type: ignore[arg-type]


def test_market_v2_requires_exact_evidence_and_quote_types() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionMarketV2(
            market_evidence_v1=object(),  # type: ignore[arg-type]
            stage=PriceSubmissionStage.CONTINUOUS,
            ask=_quote("10.00"),
            bid=_quote("10.00"),
            latest=_quote(None),
            previous_close=_quote(None),
        )
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionMarketV2(
            market_evidence_v1=_market_v1(),
            stage=PriceSubmissionStage.CONTINUOUS,
            ask=object(),  # type: ignore[arg-type]
            bid=_quote("10.00"),
            latest=_quote(None),
            previous_close=_quote(None),
        )


def test_market_v2_revalidates_nested_hashes_and_quote_shapes() -> None:
    stale_market = _market_v2()
    object.__setattr__(stale_market.market_evidence_v1, "reference_price", Decimal("10.01"))
    with pytest.raises(ExecutionContractValidationError):
        stale_market.__post_init__()

    invalid_quote_market = _market_v2()
    object.__setattr__(invalid_quote_market.ask, "value", Decimal("0"))
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        invalid_quote_market.__post_init__()


@pytest.mark.parametrize(
    ("cage_reason", "v2_reason"),
    [
        (
            PriceSubmissionRangeReason.PRICE_CAGE_NOT_APPLICABLE,
            SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED,
        ),
        (
            PriceSubmissionRangeReason.STAGE_UNKNOWN,
            SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED,
        ),
        (
            PriceSubmissionRangeReason.INVALID_RULE,
            SubmissionV2DenyCode.PRICE_CAGE_INVALID_RULE,
        ),
        (
            PriceSubmissionRangeReason.INVALID_QUOTE,
            SubmissionV2DenyCode.PRICE_CAGE_INVALID_QUOTE,
        ),
        (
            PriceSubmissionRangeReason.REFERENCE_QUOTE_UNKNOWN,
            SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_UNKNOWN,
        ),
        (
            PriceSubmissionRangeReason.NO_REFERENCE_QUOTE,
            SubmissionV2DenyCode.SUBMISSION_REFERENCE_QUOTE_MISSING,
        ),
        (
            PriceSubmissionRangeReason.REFERENCE_PRICE_NOT_ON_TICK,
            SubmissionV2DenyCode.SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK,
        ),
        (
            PriceSubmissionRangeReason.CALCULATED_BOUNDARY_OUT_OF_RANGE,
            SubmissionV2DenyCode.PRICE_CAGE_BOUNDARY_INVALID,
        ),
    ],
)
def test_every_current_price_cage_reason_has_an_explicit_v2_mapping(
    cage_reason: PriceSubmissionRangeReason,
    v2_reason: SubmissionV2DenyCode,
) -> None:
    assert _submission_reason_for_cage(cage_reason) is v2_reason


def test_cage_reason_adapter_rejects_inconsistent_calculation_results() -> None:
    calculated = PriceSubmissionRangeDecision(
        status=PriceSubmissionRangeStatus.CALCULATED,
        side=ExecutionSide.BUY,
        stage=PriceSubmissionStage.CONTINUOUS,
        reference_source=PriceQuoteSource.ASK,
        reference_price=Decimal("10.00"),
        boundary_price=Decimal("10.50"),
        reason_code=None,
    )
    object.__setattr__(calculated, "boundary_price", None)
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        _cage_reasons(calculated)

    denied = PriceSubmissionRangeDecision(
        status=PriceSubmissionRangeStatus.DENIED,
        side=ExecutionSide.BUY,
        stage=PriceSubmissionStage.CONTINUOUS,
        reference_source=None,
        reference_price=None,
        boundary_price=None,
        reason_code=PriceSubmissionRangeReason.NO_REFERENCE_QUOTE,
    )
    object.__setattr__(denied, "reason_code", None)
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        _cage_reasons(denied)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "ALLOWED"},
        {"reason_codes": [ExecutionDenyCode.SESSION_CLOSED]},
        {"reason_codes": ("UNKNOWN",)},
        {
            "reason_codes": (SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED,),
        },
        {"status": ExecutionDecisionStatus.DENIED, "reason_codes": ()},
        {"order_id": "bad id"},
        {"rule_content_hash": "bad"},
        {"market_evidence_content_hash": "g" * 64},
        {"evaluated_at": datetime(2026, 10, 16, 1, 45)},
    ],
)
def test_v2_decision_rejects_invalid_status_reasons_tokens_hashes_and_time(
    changes: dict[str, object],
) -> None:
    decision = evaluate_execution_submission(_rule_v2(), _market_v2(), _order(), AS_OF)

    with pytest.raises(ExecutionSubmissionV2ValidationError):
        replace(decision, **changes)  # type: ignore[arg-type]


def test_v2_decision_rejects_duplicate_reason_codes() -> None:
    with pytest.raises(ExecutionSubmissionV2ValidationError):
        ExecutionSubmissionDecisionV2(
            status=ExecutionDecisionStatus.DENIED,
            reason_codes=(
                SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED,
                SubmissionV2DenyCode.SUBMISSION_STAGE_NOT_ALLOWED,
            ),
            order_id="order-v2",
            rule_content_hash="a" * 64,
            market_evidence_content_hash="b" * 64,
            evaluated_at=AS_OF,
        )
