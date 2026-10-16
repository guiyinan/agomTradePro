"""Exchange-clause examples with synthetic market, calendar and account evidence.

Numeric examples follow the 2026 SSE 3.3.8/9/14 and 6.7/8, SZSE 3.3.8/9/16,
and BSE 3.3.8/9/13 clauses linked in the A-share plan. They are test inputs,
not an activated catalog or a claim of broker support. BSE rounding edge cases
and odd-lot interpretation are deliberately outside these examples.
"""

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.application.execution_submission_v2 import ExecutionSubmissionV2Evaluation
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
    evaluate_execution_submission,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionDecisionStatus,
    ExecutionOrder,
    ExecutionQuantityConstraint,
    ExecutionSide,
    SellPositionCompleteness,
    SellPositionEvidence,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)
from qmt_agent.execution_constraints import ExecutionConstraintViolation
from qmt_agent.execution_submission_v2 import validate_execution_submission_v2
from tests.unit.risk_center.execution_constraints_factories import (
    AS_OF,
    execution_market,
    execution_rule,
)


@dataclass(frozen=True)
class _ClauseExample:
    venue: str
    board: str
    minimum: int
    step: int
    maximum: int
    deviation: str
    widening_ticks: int


_EXAMPLES = (
    _ClauseExample("SSE", "MAIN", 100, 100, 1_000_000, "0.02", 10),
    _ClauseExample("SSE", "STAR", 200, 1, 100_000, "0.02", 0),
    _ClauseExample("SZSE", "MAIN", 100, 100, 1_000_000, "0.02", 10),
    _ClauseExample("SZSE", "CHINEXT", 100, 100, 300_000, "0.02", 10),
    _ClauseExample("BSE", "MAIN", 100, 1, 1_000_000, "0.05", 10),
)


def _evaluate(
    example: _ClauseExample,
    *,
    quantity: int,
    side: ExecutionSide = ExecutionSide.BUY,
    price: str = "10",
    reference: str = "10",
) -> ExecutionSubmissionV2Evaluation:
    """Assemble the reviewed numerical terms with explicitly synthetic facts."""

    quantity_rule = ExecutionQuantityConstraint(
        minimum=Decimal(example.minimum),
        step=Decimal(example.step),
        maximum=Decimal(example.maximum),
    )
    base_rule = replace(
        execution_rule(),
        market=example.venue,
        board=example.board,
        buy_quantity=quantity_rule,
        sell_quantity=quantity_rule,
        content_hash="",
    )
    rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=base_rule,
        price_submission_range=PriceSubmissionRangeRule(
            market=example.venue,
            board=example.board,
            price_tick=Decimal("0.01"),
            buy_deviation_ratio=Decimal(example.deviation),
            sell_deviation_ratio=Decimal(example.deviation),
            buy_widening_ticks=example.widening_ticks,
            sell_widening_ticks=example.widening_ticks,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=(PriceSubmissionStage.CONTINUOUS,),
    )
    base_market = replace(
        execution_market(),
        market=example.venue,
        board=example.board,
        lower_limit_price=Decimal("0.50"),
        upper_limit_price=Decimal("20"),
        reference_price=Decimal(reference),
        content_hash="",
    )
    market = ExecutionSubmissionMarketV2(
        market_evidence_v1=base_market,
        stage=PriceSubmissionStage.CONTINUOUS,
        ask=QuoteValue(QuoteValueState.PRESENT, Decimal(reference)),
        bid=QuoteValue(QuoteValueState.PRESENT, Decimal(reference)),
        latest=QuoteValue(QuoteValueState.UNKNOWN, None),
        previous_close=QuoteValue(QuoteValueState.UNKNOWN, None),
    )
    position = (
        SellPositionEvidence(
            security_id=base_rule.security_id,
            account_id=7,
            available_to_sell_quantity=Decimal(example.maximum),
            restricted_quantity=Decimal("0"),
            completeness=SellPositionCompleteness.COMPLETE,
            source_id="fixture-only-position",
            source_version="fixture-only",
            source_hash="d" * 64,
            observed_at=AS_OF - timedelta(seconds=2),
            available_at=AS_OF - timedelta(seconds=1),
            valid_until=AS_OF + timedelta(seconds=30),
        )
        if side is ExecutionSide.SELL
        else None
    )
    order = ExecutionOrder(
        order_id="fixture-only-exchange-example",
        account_id=7,
        security_id=base_rule.security_id,
        side=side,
        quantity=Decimal(quantity),
        limit_price=Decimal(price),
        sell_position_evidence=position,
    )
    decision = evaluate_execution_submission(rule, market, order, AS_OF)
    return ExecutionSubmissionV2Evaluation(rule, market, order, AS_OF, decision)


def _assert_same_result(evaluation: ExecutionSubmissionV2Evaluation, *, allowed: bool) -> None:
    assert (evaluation.decision.status is ExecutionDecisionStatus.ALLOWED) is allowed
    envelope = evaluation.to_payload()
    if allowed:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)
        return
    # Prove the local Agent independently rejects the terms even if ALLOWED is forged.
    forged = deepcopy(envelope)
    decision = cast(dict[str, object], forged["decision"])
    decision.update(status="ALLOWED", reason_codes=[])
    with pytest.raises(ExecutionConstraintViolation):
        validate_execution_submission_v2(forged, submitted_at=AS_OF)


@pytest.mark.parametrize("example", _EXAMPLES, ids=lambda item: f"{item.venue}-{item.board}")
def test_exchange_buy_quantity_examples_match_both_validators(example: _ClauseExample) -> None:
    for quantity, allowed in (
        (example.minimum - 1, False),
        (example.minimum, True),
        (example.minimum + 1, example.step == 1),
        (example.maximum, True),
        (example.maximum + example.step, False),
    ):
        _assert_same_result(_evaluate(example, quantity=quantity), allowed=allowed)


@pytest.mark.parametrize("example", _EXAMPLES, ids=lambda item: f"{item.venue}-{item.board}")
@pytest.mark.parametrize("side", (ExecutionSide.BUY, ExecutionSide.SELL))
def test_exchange_continuous_price_examples_match_both_validators(
    example: _ClauseExample, side: ExecutionSide
) -> None:
    # Exact-tick cases avoid assuming unverified BSE tie-rounding semantics.
    boundary = {
        ("0.02", 0, ExecutionSide.BUY): "10.20",
        ("0.02", 0, ExecutionSide.SELL): "9.80",
        ("0.02", 10, ExecutionSide.BUY): "10.20",
        ("0.02", 10, ExecutionSide.SELL): "9.80",
        ("0.05", 10, ExecutionSide.BUY): "10.50",
        ("0.05", 10, ExecutionSide.SELL): "9.50",
    }[(example.deviation, example.widening_ticks, side)]
    _assert_same_result(_evaluate(example, quantity=200, side=side, price=boundary), allowed=True)
    outside = Decimal(boundary) + (
        Decimal("0.01") if side is ExecutionSide.BUY else Decimal("-0.01")
    )
    _assert_same_result(
        _evaluate(example, quantity=200, side=side, price=str(outside)), allowed=False
    )


@pytest.mark.parametrize("example", _EXAMPLES, ids=lambda item: f"{item.venue}-{item.board}")
@pytest.mark.parametrize("side", (ExecutionSide.BUY, ExecutionSide.SELL))
def test_exchange_low_price_examples_apply_the_tick_widening_term(
    example: _ClauseExample, side: ExecutionSide
) -> None:
    boundary = (
        ("1.02" if side is ExecutionSide.BUY else "0.98")
        if example.widening_ticks == 0
        else ("1.10" if side is ExecutionSide.BUY else "0.90")
    )
    _assert_same_result(
        _evaluate(example, quantity=200, side=side, price=boundary, reference="1"), allowed=True
    )
    outside = Decimal(boundary) + (
        Decimal("0.01") if side is ExecutionSide.BUY else Decimal("-0.01")
    )
    _assert_same_result(
        _evaluate(example, quantity=200, side=side, price=str(outside), reference="1"),
        allowed=False,
    )
