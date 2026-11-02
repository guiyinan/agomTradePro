"""Financial-risk counterexamples for source-bound local simulated markets."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from apps.risk_center.application.local_simulated_market import (
    LocalSimulatedMarketBundle,
    LocalSimulatedMarketProvider,
    build_submission_market,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionRuleV2,
    ExecutionSubmissionV2ValidationError,
)
from apps.risk_center.domain.execution_trading_constraints import ExecutionSide
from apps.risk_center.domain.local_simulated_market_policy import LocalSimulatedMarketPolicy
from apps.risk_center.domain.price_submission_range import (
    PriceSubmissionRangeReason,
    PriceSubmissionRangeStatus,
    PriceSubmissionStage,
    QuoteValueState,
    calculate_price_submission_range,
)
from tests.unit.risk_center.test_local_simulated_market_provider import (
    AS_OF,
    SHANGHAI,
    _calendar,
    _capture,
    _policy,
    _rule,
)


def test_quote_ttl_is_exclusive_at_the_exact_expiry_in_builder_and_provider() -> None:
    capture = _capture()
    assert capture.quote is not None
    assert capture.quote.source_observed_at is not None
    policy = _policy()
    expiry = capture.quote.source_observed_at + timedelta(seconds=policy.quote_ttl_seconds)

    just_before_expiry = build_submission_market(
        policy=policy,
        capture=capture,
        calendar=_calendar(),
        rule=_rule(),
        as_of=expiry - timedelta(microseconds=1),
    )
    assert isinstance(just_before_expiry, LocalSimulatedMarketBundle)
    provider = LocalSimulatedMarketProvider(bundle=just_before_expiry)
    assert (
        provider.get_submission_market(
            account_id=1,
            security_id="600000.SH",
            as_of=expiry,
        )
        is None
    )

    assert (
        build_submission_market(
            policy=policy,
            capture=capture,
            calendar=_calendar(),
            rule=_rule(),
            as_of=expiry,
        )
        is None
    )


def test_a_morning_quote_cannot_be_reused_in_the_afternoon_even_when_ttl_spans_lunch() -> None:
    morning_quote = _capture(
        source_time="11:29:00",
        completed_at=datetime(2026, 11, 2, 11, 29, 5, tzinfo=SHANGHAI),
    )
    afternoon_as_of = datetime(2026, 11, 2, 13, 1, tzinfo=SHANGHAI)
    policy = replace(_policy(), quote_ttl_seconds=7_200, content_hash="")

    assert morning_quote.quote is not None
    assert morning_quote.quote.source_observed_at.time() < datetime(2026, 11, 2, 12, 0).time()
    assert (
        build_submission_market(
            policy=policy,
            capture=morning_quote,
            calendar=_calendar(),
            rule=_rule(),
            as_of=afternoon_as_of,
        )
        is None
    )


def test_fetch_completion_never_substitutes_for_missing_or_wrong_trading_day_source_clock() -> None:
    missing_clock = _capture(
        source_date="",
        source_time="",
        completed_at=AS_OF - timedelta(seconds=1),
    )
    next_day_row = _capture(source_date="2026-11-03", source_time="09:59:00")

    assert missing_clock.quote is not None
    assert missing_clock.quote.source_observed_at is None
    assert next_day_row.quote is not None
    assert next_day_row.quote.source_observed_at is not None
    assert next_day_row.quote.source_observed_at.date() == date(2026, 11, 3)
    for capture in (missing_clock, next_day_row):
        assert (
            build_submission_market(
                policy=_policy(),
                capture=capture,
                calendar=_calendar(),
                rule=_rule(),
                as_of=AS_OF,
            )
            is None
        )


def test_allowlisting_an_unknown_vendor_code_does_not_make_its_state_trading() -> None:
    unknown_status = _capture(status="98")
    assert unknown_status.quote is not None
    policy = replace(
        _policy(),
        trusted_vendor_status_codes=("98",),
        content_hash="",
    )

    assert (
        build_submission_market(
            policy=policy,
            capture=unknown_status,
            calendar=_calendar(),
            rule=_rule(),
            as_of=AS_OF,
        )
        is None
    )


def test_unknown_missing_bid_blocks_sell_reference_fallback_to_other_quotes() -> None:
    bundle = build_submission_market(
        policy=_policy(),
        capture=_capture(bid="0", ask="0"),
        calendar=_calendar(),
        rule=_rule(),
        as_of=AS_OF,
    )
    assert isinstance(bundle, LocalSimulatedMarketBundle)
    assert bundle.purpose == "local_simulation_only"
    assert bundle.market.bid.state is QuoteValueState.UNKNOWN
    assert bundle.market.ask.state is QuoteValueState.UNKNOWN

    decision = calculate_price_submission_range(
        _rule().price_submission_range,
        side=ExecutionSide.SELL,
        stage=PriceSubmissionStage.CONTINUOUS,
        ask=bundle.market.ask,
        bid=bundle.market.bid,
        latest=bundle.market.latest,
        previous_close=bundle.market.previous_close,
    )
    assert decision.status is PriceSubmissionRangeStatus.DENIED
    assert decision.reason_code is PriceSubmissionRangeReason.REFERENCE_QUOTE_UNKNOWN


def test_policy_and_execution_rule_must_share_the_exact_security_scope() -> None:
    mismatched_policy = replace(_policy(), security_id="000001.SZ", content_hash="")
    mismatched_execution = replace(
        _rule().execution_rule_v1,
        security_id="000001.SZ",
        content_hash="",
    )
    mismatched_rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=mismatched_execution,
        price_submission_range=_rule().price_submission_range,
        allowed_stages=_rule().allowed_stages,
    )

    for policy, rule in (
        (mismatched_policy, _rule()),
        (_policy(), mismatched_rule),
        (replace(_policy(), board="STAR", content_hash=""), _rule()),
    ):
        assert (
            build_submission_market(
                policy=policy,
                capture=_capture(),
                calendar=_calendar(),
                rule=rule,
                as_of=AS_OF,
            )
            is None
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("market", "SZ"),
        ("board", "STAR"),
        ("price_tick", Decimal("0.01")),
    ],
)
def test_v1_and_price_cage_cannot_be_composed_with_a_market_board_or_tick_mismatch(
    field_name: str,
    replacement: str | Decimal,
) -> None:
    rule = _rule()
    mismatched_cage = replace(rule.price_submission_range, **{field_name: replacement})

    with pytest.raises(ExecutionSubmissionV2ValidationError, match="must match exactly"):
        ExecutionSubmissionRuleV2(
            execution_rule_v1=rule.execution_rule_v1,
            price_submission_range=mismatched_cage,
            allowed_stages=rule.allowed_stages,
        )


def test_paper_boundary_half_up_quantization_is_exact_under_low_decimal_precision() -> None:
    policy: LocalSimulatedMarketPolicy = replace(
        _policy(),
        lower_boundary_factor=Decimal("0.9025"),
        upper_boundary_factor=Decimal("1.1025"),
        content_hash="",
    )

    with localcontext() as context:
        context.prec = 2
        assert policy.derive_price_boundaries(
            previous_close=Decimal("10.00"),
            price_tick=Decimal("0.05"),
        ) == (Decimal("9.05"), Decimal("11.05"))
