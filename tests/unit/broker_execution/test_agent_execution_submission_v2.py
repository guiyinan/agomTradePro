"""Cross-boundary checks for the standalone Agent v2 submission validator."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.risk_center.application.execution_submission_v2 import (
    EvaluateExecutionSubmissionV2UseCase,
)
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionMarketV2,
    ExecutionSubmissionRuleV2,
)
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
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
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
)
from qmt_agent import execution_submission_v2 as agent_submission_v2
from qmt_agent.execution_constraints import ExecutionConstraintViolation
from qmt_agent.execution_submission_v2 import validate_execution_submission_v2

# Import the generated stdlib projection directly so this test also protects
# the Agent boundary from depending on its Django/Risk source implementation.
from qmt_agent.price_submission_range import (
    PriceSubmissionRangeStatus as AgentPriceSubmissionRangeStatus,
)
from qmt_agent.price_submission_range import PriceSubmissionStage as AgentPriceSubmissionStage
from qmt_agent.price_submission_range import QuoteValueState as AgentQuoteValueState

AS_OF = datetime(2026, 10, 16, 1, 45, tzinfo=UTC)


class _RuleProvider:
    def __init__(self, rule: ExecutionSubmissionRuleV2, *, as_of: datetime = AS_OF) -> None:
        self.rule = rule
        self.as_of = as_of

    def get_submission_rule(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionRuleV2:
        assert account_id == 7
        assert security_id == self.rule.execution_rule_v1.security_id
        assert as_of == self.as_of
        return self.rule


class _MarketProvider:
    def __init__(self, market: ExecutionSubmissionMarketV2, *, as_of: datetime = AS_OF) -> None:
        self.market = market
        self.as_of = as_of

    def get_submission_market(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> ExecutionSubmissionMarketV2:
        assert account_id == 7
        assert security_id == self.market.market_evidence_v1.security_id
        assert as_of == self.as_of
        return self.market


class _PositionProvider:
    def __init__(self, position: SellPositionEvidence, *, as_of: datetime) -> None:
        self.position = position
        self.as_of = as_of

    def get_sell_position(
        self, *, account_id: int, security_id: str, as_of: datetime
    ) -> SellPositionEvidence:
        assert account_id == self.position.account_id
        assert security_id == self.position.security_id
        assert as_of == self.as_of
        return self.position


def _quantity() -> ExecutionQuantityConstraint:
    return ExecutionQuantityConstraint(
        minimum=Decimal("10"), step=Decimal("10"), maximum=Decimal("1000")
    )


def _domain_rule(*, board: str, tick: Decimal, as_of: datetime = AS_OF) -> AShareExecutionRule:
    security_id = "688001.SH" if board == "STAR" else "600000.SH"
    return AShareExecutionRule(
        rule_id=f"synthetic-rule-{board.lower()}-v1",
        rule_version="fixture-v1",
        security_id=security_id,
        market="SH",
        board=board,
        buy_quantity=_quantity(),
        sell_quantity=_quantity(),
        sell_odd_lot_mode=SellOddLotMode.FORBID,
        price_tick=tick,
        rule_source_id="synthetic-rule-source",
        rule_source_version="fixture-v1",
        rule_source_hash="a" * 64,
        source_observed_at=as_of - timedelta(hours=2),
        source_available_at=as_of - timedelta(hours=1),
        effective_from=as_of - timedelta(days=1),
        valid_until=as_of + timedelta(hours=1),
    )


def _domain_market(
    *,
    board: str,
    session_state: SessionState = SessionState.OPEN,
    security_state: SecurityTradingState = SecurityTradingState.TRADING,
    market_available_at: datetime | None = None,
    market_valid_until: datetime | None = None,
    as_of: datetime = AS_OF,
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
) -> ExecutionMarketEvidence:
    available_at = market_available_at or as_of - timedelta(seconds=1)
    valid_until = market_valid_until or as_of + timedelta(minutes=1)
    security_id = "688001.SH" if board == "STAR" else "600000.SH"
    return ExecutionMarketEvidence(
        security_id=security_id,
        market="SH",
        board=board,
        trading_date=as_of.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        calendar_id="synthetic-calendar",
        calendar_version="fixture-v1",
        calendar_source_hash="b" * 64,
        calendar_observed_at=as_of - timedelta(days=1),
        calendar_available_at=as_of - timedelta(hours=1),
        calendar_valid_until=as_of + timedelta(days=1),
        session_id="synthetic-day-session",
        session_timezone="Asia/Shanghai",
        session_open_at=as_of - timedelta(minutes=30),
        session_close_at=as_of + timedelta(hours=2),
        session_state=session_state,
        security_state=security_state,
        market_source_id="synthetic-quote-source",
        market_source_version="fixture-v1",
        market_source_hash="c" * 64,
        price_boundary_mode=price_boundary_mode,
        lower_limit_price=(
            Decimal("9.00") if price_boundary_mode is PriceBoundaryMode.LIMITED else None
        ),
        upper_limit_price=(
            Decimal("11.00") if price_boundary_mode is PriceBoundaryMode.LIMITED else None
        ),
        reference_price=Decimal("10.00"),
        market_observed_at=available_at - timedelta(seconds=1),
        market_available_at=available_at,
        market_valid_until=valid_until,
    )


def _position(*, security_id: str, as_of: datetime = AS_OF) -> SellPositionEvidence:
    return SellPositionEvidence(
        security_id=security_id,
        account_id=7,
        available_to_sell_quantity=Decimal("100"),
        restricted_quantity=Decimal("0"),
        completeness=SellPositionCompleteness.COMPLETE,
        source_id="synthetic-position-source",
        source_version="fixture-v1",
        source_hash="d" * 64,
        observed_at=as_of - timedelta(seconds=2),
        available_at=as_of - timedelta(seconds=1),
        valid_until=as_of + timedelta(minutes=1),
    )


def _envelope(
    *,
    board: str = "MAIN",
    side: ExecutionSide = ExecutionSide.BUY,
    limit_price: str | None = None,
    stage: PriceSubmissionStage = PriceSubmissionStage.CONTINUOUS,
    allowed_stages: tuple[PriceSubmissionStage, ...] = (PriceSubmissionStage.CONTINUOUS,),
    ask: QuoteValue | None = None,
    bid: QuoteValue | None = None,
    latest: QuoteValue | None = None,
    previous_close: QuoteValue | None = None,
    session_state: SessionState = SessionState.OPEN,
    security_state: SecurityTradingState = SecurityTradingState.TRADING,
    market_available_at: datetime | None = None,
    market_valid_until: datetime | None = None,
    as_of: datetime = AS_OF,
    price_boundary_mode: PriceBoundaryMode = PriceBoundaryMode.LIMITED,
) -> dict[str, object]:
    tick = Decimal("0.01") if board == "STAR" else Decimal("0.05")
    rule = ExecutionSubmissionRuleV2(
        execution_rule_v1=_domain_rule(board=board, tick=tick, as_of=as_of),
        price_submission_range=PriceSubmissionRangeRule(
            market="SH",
            board=board,
            price_tick=tick,
            buy_deviation_ratio=Decimal("0.02"),
            sell_deviation_ratio=Decimal("0.02"),
            buy_widening_ticks=0 if board == "STAR" else 10,
            sell_widening_ticks=0 if board == "STAR" else 10,
            minimum_distance_ticks=1,
            lower_floor_ticks=1,
            rounding_mode=PriceRoundingMode.HALF_UP,
        ),
        allowed_stages=allowed_stages,
    )
    market = ExecutionSubmissionMarketV2(
        market_evidence_v1=_domain_market(
            board=board,
            session_state=session_state,
            security_state=security_state,
            market_available_at=market_available_at,
            market_valid_until=market_valid_until,
            as_of=as_of,
            price_boundary_mode=price_boundary_mode,
        ),
        stage=stage,
        ask=ask or QuoteValue(QuoteValueState.PRESENT, Decimal("10.00")),
        bid=bid or QuoteValue(QuoteValueState.PRESENT, Decimal("10.00")),
        latest=latest or QuoteValue(QuoteValueState.CONFIRMED_ABSENT, None),
        previous_close=previous_close or QuoteValue(QuoteValueState.CONFIRMED_ABSENT, None),
    )
    security_id = "688001.SH" if board == "STAR" else "600000.SH"
    if limit_price is None:
        limit_price = (
            "10.20"
            if side is ExecutionSide.BUY and board == "STAR"
            else (
                "9.80"
                if side is ExecutionSide.SELL and board == "STAR"
                else "10.50" if side is ExecutionSide.BUY else "9.50"
            )
        )
    order = ExecutionOrder(
        order_id="synthetic-order-v2",
        account_id=7,
        security_id=security_id,
        side=side,
        quantity=Decimal("20"),
        limit_price=Decimal(limit_price),
        sell_position_evidence=None,
    )
    result = EvaluateExecutionSubmissionV2UseCase(
        rule_provider=_RuleProvider(rule, as_of=as_of),
        market_provider=_MarketProvider(market, as_of=as_of),
        position_provider=_PositionProvider(
            _position(security_id=security_id, as_of=as_of), as_of=as_of
        ),
    ).execute(order=order, as_of=as_of)
    return result.to_payload()


def _object(parent: dict[str, object], key: str) -> dict[str, object]:
    value = parent[key]
    assert type(value) is dict
    return cast(dict[str, object], value)


def _seal(value: dict[str, object]) -> None:
    content = {key: item for key, item in value.items() if key != "content_hash"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    value["content_hash"] = hashlib.sha256(encoded).hexdigest()


def _bind_decision(envelope: dict[str, object]) -> None:
    rule = _object(envelope, "rule")
    market = _object(envelope, "market_evidence")
    decision = _object(envelope, "decision")
    decision["rule_content_hash"] = rule["content_hash"]
    decision["market_evidence_content_hash"] = market["content_hash"]


def _reseal(envelope: dict[str, object], *, rule: bool = True, market: bool = True) -> None:
    if rule:
        _seal(_object(envelope, "rule"))
    if market:
        _seal(_object(envelope, "market_evidence"))
    _bind_decision(envelope)


def _claim_allowed(envelope: dict[str, object]) -> None:
    decision = _object(envelope, "decision")
    decision["status"] = "ALLOWED"
    decision["reason_codes"] = []
    _bind_decision(envelope)


def test_domain_application_envelope_is_accepted_for_main_and_star_fixtures() -> None:
    assert AgentPriceSubmissionStage.CONTINUOUS.value == "CONTINUOUS"
    assert AgentQuoteValueState.UNKNOWN.value == "UNKNOWN"
    for board in ("MAIN", "STAR"):
        for side in (ExecutionSide.BUY, ExecutionSide.SELL):
            envelope = _envelope(board=board, side=side)
            assert envelope["schema"] == "a-share-execution-constraints.v2"
            validate_execution_submission_v2(envelope, submitted_at=AS_OF)


def test_default_submission_clock_and_unrestricted_market_boundary_are_supported() -> None:
    current_cutoff = datetime.now(UTC)
    envelope = _envelope(
        as_of=current_cutoff,
        price_boundary_mode=PriceBoundaryMode.UNRESTRICTED,
    )

    validate_execution_submission_v2(envelope)


@pytest.mark.parametrize(
    ("side", "limit_price"),
    [(ExecutionSide.BUY, "10.60"), (ExecutionSide.SELL, "9.40")],
)
def test_forged_allowed_price_outside_cage_is_rejected_inside_daily_band(
    side: ExecutionSide, limit_price: str
) -> None:
    envelope = _envelope(side=side, limit_price=limit_price)
    assert _object(envelope, "decision")["status"] == "DENIED"
    _claim_allowed(envelope)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE"


def test_server_denied_decision_is_never_overridden() -> None:
    envelope = _envelope(limit_price="10.60")
    assert _object(envelope, "decision")["status"] == "DENIED"

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SERVER_DECISION_DENIED"


def test_noncontinuous_stage_is_rejected_even_if_server_claims_allowed() -> None:
    envelope = _envelope(stage=PriceSubmissionStage.OPENING_AUCTION)
    assert _object(envelope, "decision")["status"] == "DENIED"
    _claim_allowed(envelope)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SUBMISSION_STAGE_NOT_ALLOWED"


def test_empty_stage_allowlist_remains_disabled_even_if_server_claims_allowed() -> None:
    envelope = _envelope(allowed_stages=())
    assert _object(envelope, "decision")["status"] == "DENIED"
    _claim_allowed(envelope)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SUBMISSION_STAGE_NOT_ALLOWED"


def test_unknown_selected_quote_blocks_fallback_but_confirmed_absence_allows_it() -> None:
    unknown = _envelope(ask=QuoteValue(QuoteValueState.UNKNOWN, None))
    assert _object(unknown, "decision")["status"] == "DENIED"
    _claim_allowed(unknown)
    _reseal(unknown, rule=False)
    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(unknown, submitted_at=AS_OF)
    assert error.value.code == "SUBMISSION_REFERENCE_QUOTE_UNKNOWN"

    absent = _envelope(ask=QuoteValue(QuoteValueState.CONFIRMED_ABSENT, None))
    _reseal(absent, rule=False)
    validate_execution_submission_v2(absent, submitted_at=AS_OF)


def test_unselected_unknown_quote_does_not_block_a_valid_reference() -> None:
    envelope = _envelope(latest=QuoteValue(QuoteValueState.UNKNOWN, None))
    _reseal(envelope, rule=False)

    validate_execution_submission_v2(envelope, submitted_at=AS_OF)


def test_v1_evidence_and_both_clocks_are_revalidated() -> None:
    envelope = _envelope(market_valid_until=AS_OF + timedelta(seconds=5))

    with pytest.raises(ExecutionConstraintViolation) as stale:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF + timedelta(seconds=6))
    assert stale.value.code == "EVIDENCE_EXPIRED"

    with pytest.raises(ExecutionConstraintViolation) as future:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF - timedelta(seconds=1))
    assert future.value.code == "SUBMISSION_BEFORE_AS_OF"


@pytest.mark.parametrize(
    ("session_state", "security_state", "reason"),
    [
        (SessionState.CLOSED, SecurityTradingState.TRADING, "SESSION_NOT_OPEN"),
        (SessionState.OPEN, SecurityTradingState.SUSPENDED, "SECURITY_NOT_TRADING"),
    ],
)
def test_closed_session_or_nontrading_security_is_rejected(
    session_state: SessionState,
    security_state: SecurityTradingState,
    reason: str,
) -> None:
    envelope = _envelope(session_state=session_state, security_state=security_state)
    _claim_allowed(envelope)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == reason


def test_wrong_security_is_rejected_by_the_reused_v1_validator() -> None:
    envelope = _envelope()
    _object(envelope, "order")["security_id"] = "000001.SZ"

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SECURITY_MISMATCH"


def test_outer_hash_base_hash_and_order_binding_are_checked() -> None:
    bad_outer_hash = _envelope()
    _object(bad_outer_hash, "rule")["content_hash"] = "0" * 64
    with pytest.raises(ExecutionConstraintViolation) as outer_error:
        validate_execution_submission_v2(bad_outer_hash, submitted_at=AS_OF)
    assert outer_error.value.code == "CONTENT_HASH_MISMATCH"

    bad_base_hash = _envelope()
    nested_rule = _object(_object(bad_base_hash, "rule"), "execution_rule_v1")
    nested_rule["content_hash"] = "0" * 64
    _reseal(bad_base_hash)
    with pytest.raises(ExecutionConstraintViolation) as base_error:
        validate_execution_submission_v2(bad_base_hash, submitted_at=AS_OF)
    assert base_error.value.code == "CONTENT_HASH_MISMATCH"

    wrong_order = _envelope()
    _object(wrong_order, "decision")["order_id"] = "other-order"
    with pytest.raises(ExecutionConstraintViolation) as order_error:
        validate_execution_submission_v2(wrong_order, submitted_at=AS_OF)
    assert order_error.value.code == "DECISION_BINDING_MISMATCH"


def test_quote_tampering_without_resealing_is_rejected() -> None:
    envelope = _envelope()
    _object(_object(envelope, "market_evidence"), "ask")["value"] = "10.50"

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "CONTENT_HASH_MISMATCH"


def test_forged_allowed_selected_reference_outside_daily_band_is_rejected() -> None:
    envelope = _envelope(ask=QuoteValue(QuoteValueState.PRESENT, Decimal("12")))
    assert _object(envelope, "decision")["status"] == "DENIED"
    _claim_allowed(envelope)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("market", "SZ"),
        ("price_tick", "0.01"),
    ],
)
def test_resealed_price_rule_must_match_base_market_and_tick(field: str, value: str) -> None:
    envelope = _envelope()
    price_rule = _object(_object(envelope, "rule"), "price_submission_range")
    price_rule[field] = value
    _reseal(envelope, market=False)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "PRICE_CAGE_INVALID_RULE"


def test_unknown_decision_reason_is_rejected_before_server_denial() -> None:
    envelope = _envelope(limit_price="10.60")
    decision = _object(envelope, "decision")
    decision["status"] = "DENIED"
    decision["reason_codes"] = ["UNRECOGNIZED_FUTURE_REASON"]

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "DECISION_REASON_UNKNOWN"


def test_unknown_top_level_or_nested_fields_are_rejected() -> None:
    unknown_top = _envelope()
    unknown_top["future"] = True
    with pytest.raises(ExecutionConstraintViolation) as top_error:
        validate_execution_submission_v2(unknown_top, submitted_at=AS_OF)
    assert top_error.value.code == "WIRE_KEYS_INVALID"

    unknown_nested = _envelope()
    _object(_object(unknown_nested, "rule"), "price_submission_range")["future"] = 1
    with pytest.raises(ExecutionConstraintViolation) as nested_error:
        validate_execution_submission_v2(unknown_nested, submitted_at=AS_OF)
    assert nested_error.value.code == "WIRE_KEYS_INVALID"


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("range", "price_tick", 0.05),
        ("range", "buy_widening_ticks", True),
        ("range", "price_tick", "1E-2"),
        ("quote", "value", 10.0),
    ],
)
def test_wire_numbers_and_noncanonical_decimals_are_rejected(
    section: str, field: str, value: object
) -> None:
    envelope = _envelope()
    if section == "range":
        _object(_object(envelope, "rule"), "price_submission_range")[field] = value
        _reseal(envelope, market=False)
    else:
        _object(_object(envelope, "market_evidence"), "ask")[field] = value
        _reseal(envelope, rule=False)

    with pytest.raises(ExecutionConstraintViolation):
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)


def test_nonfinite_wire_number_is_rejected() -> None:
    envelope = _envelope()
    _object(_object(envelope, "rule"), "price_submission_range")["price_tick"] = float("nan")

    with pytest.raises(ExecutionConstraintViolation):
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)


def test_naive_local_submission_time_is_rejected() -> None:
    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(_envelope(), submitted_at=datetime(2026, 10, 16))

    assert error.value.code == "SUBMISSION_TIME_INVALID"


def test_malformed_root_and_schema_are_rejected() -> None:
    for malformed in (None, {1: "non-string-key"}):
        with pytest.raises(ExecutionConstraintViolation) as error:
            validate_execution_submission_v2(malformed, submitted_at=AS_OF)
        assert error.value.code == "ENVELOPE_INVALID"

    unsupported = _envelope()
    unsupported["schema"] = "a-share-execution-constraints.v1"
    with pytest.raises(ExecutionConstraintViolation) as schema_error:
        validate_execution_submission_v2(unsupported, submitted_at=AS_OF)
    assert schema_error.value.code == "SCHEMA_UNSUPPORTED"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("status", "", "TOKEN_INVALID"),
        ("status", "PENDING", "DECISION_INVALID"),
        ("reason_codes", None, "DECISION_INVALID"),
        ("reason_codes", ["SESSION_CLOSED", "SESSION_CLOSED"], "DECISION_INVALID"),
        ("reason_codes", ["SESSION_CLOSED"], "SERVER_DECISION_DENIED"),
        ("rule_content_hash", "bad-hash", "HASH_INVALID"),
        ("status", "\ud800", "TOKEN_INVALID"),
    ],
)
def test_decision_status_reason_and_hash_shapes_are_strict(
    field: str, value: object, expected_code: str
) -> None:
    envelope = _envelope()
    decision = _object(envelope, "decision")
    decision[field] = value
    if field == "reason_codes" and value != []:
        decision["status"] = "DENIED"

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == expected_code


def test_allowed_decision_with_a_reason_is_invalid() -> None:
    envelope = _envelope()
    decision = _object(envelope, "decision")
    decision["reason_codes"] = ["SESSION_CLOSED"]

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "DECISION_INVALID"


def test_outer_hash_rejects_a_noncanonical_digest() -> None:
    envelope = _envelope()
    _object(envelope, "market_evidence")["content_hash"] = None

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "HASH_INVALID"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("rounding_mode", "HALF_DOWN", "PRICE_CAGE_INVALID_RULE"),
        ("sell_deviation_ratio", "1", "PRICE_CAGE_INVALID_RULE"),
        ("price_tick", "0", "DECIMAL_INVALID"),
        ("buy_widening_ticks", -1, "PRICE_CAGE_INVALID_RULE"),
    ],
)
def test_invalid_resealed_price_range_configuration_is_rejected(
    field: str, value: object, expected_code: str
) -> None:
    envelope = _envelope()
    _object(_object(envelope, "rule"), "price_submission_range")[field] = value
    _reseal(envelope, market=False)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == expected_code


def test_zero_ratio_and_decimal_wire_length_are_checked_explicitly() -> None:
    zero_ratio = _envelope()
    _object(_object(zero_ratio, "rule"), "price_submission_range")["buy_deviation_ratio"] = "0"
    _reseal(zero_ratio, market=False)
    validate_execution_submission_v2(zero_ratio, submitted_at=AS_OF)

    too_long = _envelope()
    _object(_object(too_long, "rule"), "price_submission_range")["price_tick"] = "1" + "0" * 257
    _reseal(too_long, market=False)
    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(too_long, submitted_at=AS_OF)
    assert error.value.code == "DECIMAL_INVALID"


def test_invalid_quote_states_and_non_null_unknown_values_are_rejected() -> None:
    invalid_state = _envelope()
    _object(_object(invalid_state, "market_evidence"), "ask")["state"] = "MAYBE"
    _reseal(invalid_state, rule=False)
    with pytest.raises(ExecutionConstraintViolation) as state_error:
        validate_execution_submission_v2(invalid_state, submitted_at=AS_OF)
    assert state_error.value.code == "PRICE_CAGE_INVALID_QUOTE"

    non_null_unknown = _envelope()
    ask = _object(_object(non_null_unknown, "market_evidence"), "ask")
    ask["state"] = "UNKNOWN"
    ask["value"] = "10"
    _reseal(non_null_unknown, rule=False)
    with pytest.raises(ExecutionConstraintViolation) as value_error:
        validate_execution_submission_v2(non_null_unknown, submitted_at=AS_OF)
    assert value_error.value.code == "PRICE_CAGE_INVALID_QUOTE"


@pytest.mark.parametrize(
    ("replacement", "expected_code"),
    [
        (None, "SUBMISSION_STAGE_INVALID"),
        (["CONTINUOUS", "CONTINUOUS"], "SUBMISSION_STAGE_INVALID"),
        (["OPENING_AUCTION"], "SUBMISSION_STAGE_INVALID"),
    ],
)
def test_allowed_stage_wire_is_a_narrow_list(replacement: object, expected_code: str) -> None:
    envelope = _envelope()
    _object(envelope, "rule")["allowed_stages"] = replacement
    _reseal(envelope, market=False)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == expected_code


def test_unknown_market_stage_is_rejected_after_hash_verification() -> None:
    envelope = _envelope()
    _object(envelope, "market_evidence")["stage"] = "PREOPEN"
    _reseal(envelope, rule=False)

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SUBMISSION_STAGE_INVALID"


def test_projection_exceptions_and_unknown_result_reasons_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _envelope()

    def _invalid_projection_quote(**kwargs: object) -> QuoteValue:
        raise ValueError("projection quote constructor failed")

    monkeypatch.setattr(agent_submission_v2, "QuoteValue", _invalid_projection_quote)
    with pytest.raises(ExecutionConstraintViolation) as quote_error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)
    assert quote_error.value.code == "PRICE_CAGE_INVALID_QUOTE"


def test_unmapped_price_cage_reason_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    result = SimpleNamespace(
        status=AgentPriceSubmissionRangeStatus.DENIED,
        reason_code=SimpleNamespace(value="UNMAPPED_FUTURE_REASON"),
    )
    monkeypatch.setattr(
        agent_submission_v2, "calculate_price_submission_range", lambda *a, **k: result
    )

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "PRICE_CAGE_DENIED"


def test_incomplete_calculated_price_cage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    result = SimpleNamespace(
        status=AgentPriceSubmissionRangeStatus.CALCULATED,
        boundary_price=None,
        reference_price=Decimal("10"),
        reason_code=None,
    )
    monkeypatch.setattr(
        agent_submission_v2, "calculate_price_submission_range", lambda *a, **k: result
    )

    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "PRICE_CAGE_RESULT_INVALID"


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "no-offset"


class _RaisingTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        raise ValueError("timezone offset unavailable")

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "raising"


def test_submission_clock_requires_a_valid_aware_timezone() -> None:
    cases = (
        ("invalid type", cast(datetime, "2026-10-16T01:45:00Z"), "SUBMISSION_TIME_INVALID"),
        (
            "missing offset",
            datetime(2026, 10, 16, tzinfo=_NoOffsetTimezone()),
            "SUBMISSION_TIME_INVALID",
        ),
        (
            "raising offset",
            datetime(2026, 10, 16, tzinfo=_RaisingTimezone()),
            "SUBMISSION_TIME_INVALID",
        ),
        (
            "UTC conversion overflow",
            datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
            "SUBMISSION_TIME_INVALID",
        ),
    )
    for _name, submitted_at, expected_code in cases:
        with pytest.raises(ExecutionConstraintViolation) as error:
            validate_execution_submission_v2(_envelope(), submitted_at=submitted_at)
        assert error.value.code == expected_code


def test_order_side_conversion_failure_uses_a_stable_constraint_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _envelope()

    def _invalid_side(value: str) -> None:
        raise ValueError("projection side constructor failed")

    monkeypatch.setattr(agent_submission_v2, "ExecutionSide", _invalid_side)
    with pytest.raises(ExecutionConstraintViolation) as error:
        validate_execution_submission_v2(envelope, submitted_at=AS_OF)

    assert error.value.code == "SIDE_INVALID"
