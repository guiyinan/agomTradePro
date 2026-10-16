from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from typing import cast

import pytest

from apps.risk_center.domain.execution_trading_constraints import ExecutionSide
from apps.risk_center.domain.price_submission_range import (
    PriceQuoteSource,
    PriceRoundingMode,
    PriceSubmissionRangeReason,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeStatus,
    PriceSubmissionRangeValidationError,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
    calculate_price_submission_range,
)


def _rule(**changes: object) -> PriceSubmissionRangeRule:
    values: dict[str, object] = {
        "market": "SSE",
        "board": "MAIN",
        "price_tick": Decimal("0.05"),
        "buy_deviation_ratio": Decimal("0.02"),
        "sell_deviation_ratio": Decimal("0.02"),
        "buy_widening_ticks": 10,
        "sell_widening_ticks": 10,
        "minimum_distance_ticks": 1,
        "lower_floor_ticks": 1,
        "rounding_mode": PriceRoundingMode.HALF_UP,
    }
    values.update(changes)
    return PriceSubmissionRangeRule(**values)  # type: ignore[arg-type]


def _present(value: str) -> QuoteValue:
    return QuoteValue(state=QuoteValueState.PRESENT, value=Decimal(value))


def _absent() -> QuoteValue:
    return QuoteValue(state=QuoteValueState.CONFIRMED_ABSENT, value=None)


def _unknown() -> QuoteValue:
    return QuoteValue(state=QuoteValueState.UNKNOWN, value=None)


def _quotes(**changes: QuoteValue) -> dict[str, QuoteValue]:
    values = {
        "ask": _absent(),
        "bid": _absent(),
        "latest": _absent(),
        "previous_close": _absent(),
    }
    values.update(changes)
    return values


def _calculate(
    *,
    side: ExecutionSide,
    quotes: dict[str, QuoteValue],
    rule: PriceSubmissionRangeRule | None = None,
    stage: PriceSubmissionStage = PriceSubmissionStage.CONTINUOUS,
):
    return calculate_price_submission_range(
        rule or _rule(),
        side=side,
        stage=stage,
        ask=quotes["ask"],
        bid=quotes["bid"],
        latest=quotes["latest"],
        previous_close=quotes["previous_close"],
    )


def test_main_board_parameters_use_the_wider_of_ratio_and_tick_boundaries() -> None:
    quotes = _quotes(ask=_present("10.00"), bid=_present("10.00"))

    buy = _calculate(side=ExecutionSide.BUY, quotes=quotes)
    sell = _calculate(side=ExecutionSide.SELL, quotes=quotes)

    assert buy.status is PriceSubmissionRangeStatus.CALCULATED
    assert buy.boundary_price == Decimal("10.50")
    assert sell.status is PriceSubmissionRangeStatus.CALCULATED
    assert sell.boundary_price == Decimal("9.50")


def test_star_parameters_are_explicit_and_do_not_inherit_main_board_widening() -> None:
    rule = _rule(
        market="SSE",
        board="STAR",
        price_tick=Decimal("0.01"),
        buy_widening_ticks=0,
        sell_widening_ticks=0,
    )
    quotes = _quotes(ask=_present("10.00"), bid=_present("10.00"))

    buy = _calculate(side=ExecutionSide.BUY, quotes=quotes, rule=rule)
    sell = _calculate(side=ExecutionSide.SELL, quotes=quotes, rule=rule)

    assert buy.boundary_price == Decimal("10.20")
    assert sell.boundary_price == Decimal("9.80")


@pytest.mark.parametrize(
    ("side", "quotes", "expected_source"),
    [
        (ExecutionSide.BUY, {"ask": _present("10.00")}, PriceQuoteSource.ASK),
        (
            ExecutionSide.BUY,
            {"ask": _absent(), "bid": _present("10.00")},
            PriceQuoteSource.BID,
        ),
        (
            ExecutionSide.BUY,
            {"ask": _absent(), "bid": _absent(), "latest": _present("10.00")},
            PriceQuoteSource.LATEST,
        ),
        (
            ExecutionSide.BUY,
            {
                "ask": _absent(),
                "bid": _absent(),
                "latest": _absent(),
                "previous_close": _present("10.00"),
            },
            PriceQuoteSource.PREVIOUS_CLOSE,
        ),
        (ExecutionSide.SELL, {"bid": _present("10.00")}, PriceQuoteSource.BID),
        (
            ExecutionSide.SELL,
            {"bid": _absent(), "ask": _present("10.00")},
            PriceQuoteSource.ASK,
        ),
        (
            ExecutionSide.SELL,
            {"bid": _absent(), "ask": _absent(), "latest": _present("10.00")},
            PriceQuoteSource.LATEST,
        ),
        (
            ExecutionSide.SELL,
            {
                "bid": _absent(),
                "ask": _absent(),
                "latest": _absent(),
                "previous_close": _present("10.00"),
            },
            PriceQuoteSource.PREVIOUS_CLOSE,
        ),
    ],
)
def test_quote_fallback_is_directional_and_uses_first_present(
    side: ExecutionSide,
    quotes: dict[str, QuoteValue],
    expected_source: PriceQuoteSource,
) -> None:
    values = _quotes(**quotes)
    decision = _calculate(side=side, quotes=values)

    assert decision.status is PriceSubmissionRangeStatus.CALCULATED
    assert decision.reference_source is expected_source
    assert decision.reference_price == Decimal("10.00")


@pytest.mark.parametrize(
    ("side", "source_order"),
    [
        (
            ExecutionSide.BUY,
            ("ask", "bid", "latest", "previous_close"),
        ),
        (
            ExecutionSide.SELL,
            ("bid", "ask", "latest", "previous_close"),
        ),
    ],
)
@pytest.mark.parametrize("unknown_index", range(4))
def test_unknown_quote_at_each_fallback_level_blocks_instead_of_skipping(
    side: ExecutionSide,
    source_order: tuple[str, ...],
    unknown_index: int,
) -> None:
    changes = {source: _absent() for source in source_order[:unknown_index]}
    changes[source_order[unknown_index]] = _unknown()
    if unknown_index < len(source_order) - 1:
        changes[source_order[unknown_index + 1]] = _present("10.00")
    decision = _calculate(side=side, quotes=_quotes(**changes))

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.REFERENCE_QUOTE_UNKNOWN
    assert decision.reference_source is PriceQuoteSource(source_order[unknown_index].upper())


def test_first_present_quote_ignores_unknown_values_after_it() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00"), bid=_unknown()),
    )

    assert decision.status is PriceSubmissionRangeStatus.CALCULATED
    assert decision.reference_source is PriceQuoteSource.ASK


def test_first_present_does_not_hide_structurally_invalid_unused_quote() -> None:
    malformed_bid = _unknown()
    object.__setattr__(malformed_bid, "value", Decimal("10.00"))
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00"), bid=malformed_bid),
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.INVALID_QUOTE
    assert decision.reference_source is PriceQuoteSource.BID


def test_all_confirmed_absent_quotes_deny_without_inventing_a_reference() -> None:
    decision = _calculate(side=ExecutionSide.BUY, quotes=_quotes())

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.NO_REFERENCE_QUOTE
    assert decision.reference_price is None
    assert decision.boundary_price is None


@pytest.mark.parametrize(
    ("state", "value"),
    [
        (QuoteValueState.PRESENT, None),
        (QuoteValueState.CONFIRMED_ABSENT, Decimal("10")),
        (QuoteValueState.UNKNOWN, Decimal("10")),
        (QuoteValueState.PRESENT, Decimal("0")),
        (QuoteValueState.PRESENT, Decimal("-0.01")),
    ],
)
def test_quote_value_state_requires_the_matching_price_shape(
    state: QuoteValueState, value: Decimal | None
) -> None:
    with pytest.raises(ValueError):
        QuoteValue(state=state, value=value)


@pytest.mark.parametrize("value", (Decimal("NaN"), Decimal("Infinity")))
def test_quote_value_rejects_nonfinite_decimal_prices(value: Decimal) -> None:
    with pytest.raises(PriceSubmissionRangeValidationError):
        QuoteValue(state=QuoteValueState.PRESENT, value=value)


@pytest.mark.parametrize(
    "stage",
    (
        PriceSubmissionStage.OPENING_AUCTION,
        PriceSubmissionStage.CLOSING_AUCTION,
        PriceSubmissionStage.HALTED,
    ),
)
def test_noncontinuous_stages_are_not_applicable_not_allowed(
    stage: PriceSubmissionStage,
) -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_unknown()),
        stage=stage,
    )

    assert decision.status is PriceSubmissionRangeStatus.NOT_APPLICABLE
    assert decision.reason_code is PriceSubmissionRangeReason.PRICE_CAGE_NOT_APPLICABLE
    assert decision.boundary_price is None


def test_noncontinuous_stage_still_rejects_malformed_quote_structure() -> None:
    malformed_ask = _present("10.00")
    object.__setattr__(malformed_ask, "value", None)
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=malformed_ask),
        stage=PriceSubmissionStage.HALTED,
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.INVALID_QUOTE


def test_unknown_stage_denies_and_does_not_compute_a_boundary() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
        stage=PriceSubmissionStage.UNKNOWN,
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.STAGE_UNKNOWN
    assert decision.boundary_price is None


@pytest.mark.parametrize(
    ("side", "ratio", "expected"),
    [
        (ExecutionSide.BUY, "0.0125", "10.15"),
        (ExecutionSide.SELL, "0.0125", "9.90"),
    ],
)
def test_half_up_rounds_exact_half_tick_away_from_zero(
    side: ExecutionSide, ratio: str, expected: str
) -> None:
    rule = _rule(
        buy_deviation_ratio=Decimal(ratio),
        sell_deviation_ratio=Decimal(ratio),
        buy_widening_ticks=0,
        sell_widening_ticks=0,
        minimum_distance_ticks=0,
    )
    quotes = _quotes(ask=_present("10.00"), bid=_present("10.00"))

    decision = _calculate(side=side, quotes=quotes, rule=rule)

    assert decision.boundary_price == Decimal(expected)


@pytest.mark.parametrize(
    ("side", "expected"),
    [(ExecutionSide.BUY, "10.05"), (ExecutionSide.SELL, "9.95")],
)
def test_minimum_distance_moves_rounded_boundary_one_configured_tick(
    side: ExecutionSide, expected: str
) -> None:
    rule = _rule(
        buy_deviation_ratio=Decimal("0.001"),
        sell_deviation_ratio=Decimal("0.001"),
        buy_widening_ticks=0,
        sell_widening_ticks=0,
        minimum_distance_ticks=1,
    )
    quotes = _quotes(ask=_present("10.00"), bid=_present("10.00"))

    decision = _calculate(side=side, quotes=quotes, rule=rule)

    assert decision.boundary_price == Decimal(expected)


def test_low_sell_boundary_is_floored_after_minimum_distance_adjustment() -> None:
    rule = _rule(
        price_tick=Decimal("0.05"),
        sell_deviation_ratio=Decimal("0.02"),
        sell_widening_ticks=10,
        minimum_distance_ticks=1,
        lower_floor_ticks=1,
    )
    decision = _calculate(
        side=ExecutionSide.SELL,
        quotes=_quotes(bid=_present("0.05")),
        rule=rule,
    )

    assert decision.boundary_price == Decimal("0.05")


def test_reference_price_must_be_on_configured_tick() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.01")),
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.REFERENCE_PRICE_NOT_ON_TICK
    assert decision.reference_price == Decimal("10.01")


def test_large_decimal_values_calculate_without_context_rounding() -> None:
    rule = _rule(
        price_tick=Decimal("0.01"),
        buy_deviation_ratio=Decimal("0.01"),
        buy_widening_ticks=0,
        minimum_distance_ticks=0,
    )
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("123456789012345678901234567890.00")),
        rule=rule,
    )

    assert decision.boundary_price == Decimal("124691356902469135690246913568.90")


def test_rule_requires_all_explicit_positive_and_typed_parameters() -> None:
    with pytest.raises(ValueError):
        _rule(price_tick=Decimal("0"))
    with pytest.raises(ValueError):
        _rule(buy_widening_ticks=-1)
    with pytest.raises(ValueError):
        _rule(rounding_mode="HALF_UP")


def test_rule_payload_contains_all_fields_with_canonical_decimal_strings() -> None:
    rule = _rule(
        price_tick=Decimal("0.0500"),
        buy_deviation_ratio=Decimal("0.000"),
        sell_deviation_ratio=Decimal("0.0200"),
    )

    assert rule.to_payload() == {
        "market": "SSE",
        "board": "MAIN",
        "price_tick": "0.05",
        "buy_deviation_ratio": "0",
        "sell_deviation_ratio": "0.02",
        "buy_widening_ticks": 10,
        "sell_widening_ticks": 10,
        "minimum_distance_ticks": 1,
        "lower_floor_ticks": 1,
        "rounding_mode": "HALF_UP",
    }


def test_quote_payload_preserves_each_explicit_state_and_canonical_price() -> None:
    assert _present("1.2300").to_payload() == {"state": "PRESENT", "value": "1.23"}
    assert _absent().to_payload() == {"state": "CONFIRMED_ABSENT", "value": None}
    assert _unknown().to_payload() == {"state": "UNKNOWN", "value": None}


def test_rule_and_quote_payloads_support_bounded_large_decimal_precision() -> None:
    large = Decimal("123456789012345678901234567890.000")
    rule = _rule(price_tick=large)
    quote = _present("123456789012345678901234567890.000")

    assert rule.to_payload()["price_tick"] == "123456789012345678901234567890"
    assert quote.to_payload()["value"] == "123456789012345678901234567890"


def test_canonical_payload_expansion_accepts_128_exponent_and_rejects_overlong_value() -> None:
    assert _rule(price_tick=Decimal("1E+128")).to_payload()["price_tick"] == "1" + "0" * 128

    with pytest.raises(PriceSubmissionRangeValidationError):
        _rule(buy_deviation_ratio=Decimal("1E-256"))


@pytest.mark.parametrize(
    "changes",
    [
        {"market": ""},
        {"board": " MAIN"},
        {"buy_deviation_ratio": Decimal("-0.01")},
        {"sell_deviation_ratio": Decimal("1")},
        {"buy_widening_ticks": True},
        {"minimum_distance_ticks": -1},
        {"lower_floor_ticks": 0},
    ],
)
def test_rule_rejects_noncanonical_or_unsafe_parameters(changes: dict[str, object]) -> None:
    with pytest.raises(PriceSubmissionRangeValidationError):
        _rule(**changes)


def test_rule_rejects_negative_tick_and_overlong_integer_configuration() -> None:
    with pytest.raises(PriceSubmissionRangeValidationError):
        _rule(price_tick=Decimal("-0.01"))
    with pytest.raises(PriceSubmissionRangeValidationError):
        _rule(buy_widening_ticks=10**257)


def test_rule_payload_revalidates_tampered_frozen_value() -> None:
    rule = _rule()
    object.__setattr__(rule, "market", "SSE MAIN")

    with pytest.raises(PriceSubmissionRangeValidationError):
        rule.to_payload()


def test_evaluation_denies_a_tampered_rule_with_a_stable_reason() -> None:
    rule = _rule()
    object.__setattr__(rule, "price_tick", Decimal("0"))

    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
        rule=rule,
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.INVALID_RULE


def test_evaluation_denies_a_rule_argument_with_the_wrong_runtime_type() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
        rule=cast(PriceSubmissionRangeRule, object()),
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.INVALID_RULE


def test_evaluation_denies_a_malformed_quote_with_a_stable_reason() -> None:
    malformed_quote = _unknown()
    object.__setattr__(malformed_quote, "value", Decimal("10"))
    quotes = _quotes(ask=malformed_quote)

    decision = _calculate(side=ExecutionSide.BUY, quotes=quotes)

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.INVALID_QUOTE
    assert decision.reference_source is PriceQuoteSource.ASK


def test_evaluation_denies_quote_arguments_with_wrong_type_or_state() -> None:
    wrong_type_decision = calculate_price_submission_range(
        _rule(),
        side=ExecutionSide.BUY,
        stage=PriceSubmissionStage.CONTINUOUS,
        ask=cast(QuoteValue, object()),
        bid=_absent(),
        latest=_absent(),
        previous_close=_absent(),
    )
    wrong_state = _unknown()
    object.__setattr__(wrong_state, "state", "UNKNOWN")
    wrong_state_decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=wrong_state),
    )

    assert wrong_type_decision.reason_code is PriceSubmissionRangeReason.INVALID_QUOTE
    assert wrong_state_decision.reason_code is PriceSubmissionRangeReason.INVALID_QUOTE


def test_evaluation_rejects_untyped_side_and_stage() -> None:
    quotes = _quotes(ask=_present("10.00"))
    args = {
        "rule": _rule(),
        "stage": PriceSubmissionStage.CONTINUOUS,
        "ask": quotes["ask"],
        "bid": quotes["bid"],
        "latest": quotes["latest"],
        "previous_close": quotes["previous_close"],
    }

    with pytest.raises(PriceSubmissionRangeValidationError):
        calculate_price_submission_range(
            side=cast(ExecutionSide, "BUY"), **args  # type: ignore[arg-type]
        )
    with pytest.raises(PriceSubmissionRangeValidationError):
        calculate_price_submission_range(
            side=ExecutionSide.BUY,
            stage=cast(PriceSubmissionStage, "CONTINUOUS"),
            **{key: value for key, value in args.items() if key != "stage"},  # type: ignore[arg-type]
        )


def test_calculated_boundary_over_wire_bound_is_denied() -> None:
    rule = _rule(
        price_tick=Decimal("1"),
        buy_deviation_ratio=Decimal("1E+256"),
        buy_widening_ticks=0,
        minimum_distance_ticks=0,
    )
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("1E+256")),
        rule=rule,
    )

    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.CALCULATED_BOUNDARY_OUT_OF_RANGE


def test_decision_rejects_inconsistent_public_shapes() -> None:
    calculated = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
    )
    not_applicable = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(),
        stage=PriceSubmissionStage.HALTED,
    )

    with pytest.raises(PriceSubmissionRangeValidationError):
        replace(calculated, stage=PriceSubmissionStage.HALTED)
    with pytest.raises(PriceSubmissionRangeValidationError):
        replace(not_applicable, stage=PriceSubmissionStage.CONTINUOUS)
    with pytest.raises(PriceSubmissionRangeValidationError):
        replace(calculated, reason_code=PriceSubmissionRangeReason.STAGE_UNKNOWN)


def test_decision_rejects_untyped_fields_and_incomplete_denials() -> None:
    calculated = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
    )
    denied = _calculate(side=ExecutionSide.BUY, quotes=_quotes())
    invalid_values: tuple[dict[str, object], ...] = (
        {"status": "CALCULATED"},
        {"side": "BUY"},
        {"stage": "CONTINUOUS"},
        {"reason_code": "STAGE_UNKNOWN"},
        {"reference_source": "ASK"},
        {"reference_price": Decimal("0")},
        {"reference_price": Decimal("-10")},
        {"boundary_price": Decimal("-9.95")},
    )

    for changes in invalid_values:
        with pytest.raises(PriceSubmissionRangeValidationError):
            replace(calculated, **changes)  # type: ignore[arg-type]
    with pytest.raises(PriceSubmissionRangeValidationError):
        replace(denied, reason_code=None)


def test_decision_is_immutable() -> None:
    decision = _calculate(
        side=ExecutionSide.BUY,
        quotes=_quotes(ask=_present("10.00")),
    )

    with pytest.raises(FrozenInstanceError):
        decision.boundary_price = Decimal("0")  # type: ignore[misc]
