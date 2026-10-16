"""Standalone validation of the candidate A-share execution-submission v2 wire.

The outer hashes bind the v2 rule and market snapshots, while the nested v1
projection is revalidated by the existing Agent validator at both the server
cutoff and local submission time. Neither decision is a signature or execution
authorization. This module and its price-range projection have no Django or
application dependencies.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import NoReturn, cast

from .execution_constraints import (
    ExecutionConstraintViolation,
    validate_effective_constraints,
)
from .price_submission_range import (
    ExecutionSide,
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeStatus,
    PriceSubmissionStage,
    QuoteValue,
    QuoteValueState,
    calculate_price_submission_range,
)

_SCHEMA: str = "a-share-execution-constraints.v2"
_V1_SCHEMA: str = "a-share-execution-constraints.v1"
_TOP_KEYS: frozenset[str] = frozenset(
    {"schema", "as_of", "rule", "market_evidence", "order", "decision"}
)
_RULE_KEYS: frozenset[str] = frozenset(
    {"execution_rule_v1", "price_submission_range", "allowed_stages", "content_hash"}
)
_PRICE_RANGE_KEYS: frozenset[str] = frozenset(
    {
        "market",
        "board",
        "price_tick",
        "buy_deviation_ratio",
        "sell_deviation_ratio",
        "buy_widening_ticks",
        "sell_widening_ticks",
        "minimum_distance_ticks",
        "lower_floor_ticks",
        "rounding_mode",
    }
)
_MARKET_KEYS: frozenset[str] = frozenset(
    {
        "market_evidence_v1",
        "stage",
        "ask",
        "bid",
        "latest",
        "previous_close",
        "content_hash",
    }
)
_QUOTE_KEYS: frozenset[str] = frozenset({"state", "value"})
_ORDER_KEYS: frozenset[str] = frozenset(
    {
        "order_id",
        "account_id",
        "security_id",
        "side",
        "quantity",
        "limit_price",
        "sell_position_evidence",
    }
)
_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "reason_codes",
        "order_id",
        "rule_content_hash",
        "market_evidence_content_hash",
    }
)
_V1_RULE_KEYS: frozenset[str] = frozenset(
    {
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
)
_V1_QUANTITY_KEYS: frozenset[str] = frozenset({"minimum", "step", "maximum"})
_V1_MARKET_KEYS: frozenset[str] = frozenset(
    {
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
)
_V1_POSITION_KEYS: frozenset[str] = frozenset(
    {
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
)
_V1_DECISION_REASON_CODES: frozenset[str] = frozenset(
    {
        "RULE_MARKET_SECURITY_MISMATCH",
        "ORDER_SECURITY_MISMATCH",
        "RULE_SOURCE_NOT_YET_AVAILABLE",
        "RULE_NOT_YET_EFFECTIVE",
        "RULE_SOURCE_EXPIRED",
        "RULE_MARKET_MISMATCH",
        "RULE_BOARD_MISMATCH",
        "CALENDAR_EVIDENCE_NOT_YET_AVAILABLE",
        "CALENDAR_EVIDENCE_EXPIRED",
        "MARKET_EVIDENCE_NOT_YET_AVAILABLE",
        "MARKET_EVIDENCE_EXPIRED",
        "SESSION_STATE_UNKNOWN",
        "SESSION_CLOSED",
        "OUTSIDE_TRADING_DATE",
        "OUTSIDE_SESSION",
        "SECURITY_STATE_UNKNOWN",
        "SECURITY_SUSPENDED",
        "SECURITY_DELISTED",
        "PRICE_BOUNDARY_UNKNOWN",
        "REFERENCE_PRICE_NOT_ON_TICK",
        "LIMIT_PRICE_NOT_ON_TICK",
        "REFERENCE_PRICE_OUTSIDE_BOUNDARY",
        "LIMIT_PRICE_OUTSIDE_BOUNDARY",
        "QUANTITY_BELOW_MINIMUM",
        "QUANTITY_NOT_ON_STEP",
        "QUANTITY_ABOVE_MAXIMUM",
        "POSITION_EVIDENCE_MISSING",
        "POSITION_EVIDENCE_INCOMPLETE",
        "POSITION_ACCOUNT_MISMATCH",
        "POSITION_SECURITY_MISMATCH",
        "POSITION_EVIDENCE_NOT_YET_AVAILABLE",
        "POSITION_EVIDENCE_EXPIRED",
        "SELLABLE_BALANCE_INSUFFICIENT",
        "ODD_LOT_HAS_RESTRICTED_BALANCE",
        "ODD_LOT_NOT_FULL_SELLABLE_BALANCE",
    }
)
_V2_DECISION_REASON_CODES: frozenset[str] = frozenset(
    {
        "SUBMISSION_STAGE_NOT_ALLOWED",
        "PRICE_CAGE_INVALID_RULE",
        "PRICE_CAGE_INVALID_QUOTE",
        "SUBMISSION_REFERENCE_QUOTE_UNKNOWN",
        "SUBMISSION_REFERENCE_QUOTE_MISSING",
        "SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK",
        "SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY",
        "PRICE_CAGE_BOUNDARY_INVALID",
        "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE",
    }
)
_ALL_DECISION_REASON_CODES: frozenset[str] = _V1_DECISION_REASON_CODES | _V2_DECISION_REASON_CODES
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[^\s]+")
_DIGEST_PATTERN: re.Pattern[str] = re.compile(r"[0-9a-f]{64}")
_MAX_DECIMAL_WIRE_LENGTH: int = 257
_DECIMAL_PATTERN: re.Pattern[str] = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?")
_CAGE_REASON_CODES: dict[str, str] = {
    "INVALID_RULE": "PRICE_CAGE_INVALID_RULE",
    "INVALID_QUOTE": "PRICE_CAGE_INVALID_QUOTE",
    "REFERENCE_QUOTE_UNKNOWN": "SUBMISSION_REFERENCE_QUOTE_UNKNOWN",
    "NO_REFERENCE_QUOTE": "SUBMISSION_REFERENCE_QUOTE_MISSING",
    "REFERENCE_PRICE_NOT_ON_TICK": "SUBMISSION_REFERENCE_PRICE_NOT_ON_TICK",
    "CALCULATED_BOUNDARY_OUT_OF_RANGE": "PRICE_CAGE_BOUNDARY_INVALID",
    "PRICE_CAGE_NOT_APPLICABLE": "SUBMISSION_STAGE_NOT_ALLOWED",
    "STAGE_UNKNOWN": "SUBMISSION_STAGE_NOT_ALLOWED",
}


def _reject(code: str, message: str) -> NoReturn:
    raise ExecutionConstraintViolation(code, message)


def _object(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _reject("ENVELOPE_INVALID", f"{field_name} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _shape(value: dict[str, object], expected: frozenset[str], field_name: str) -> None:
    if frozenset(value) != expected:
        _reject("WIRE_KEYS_INVALID", f"{field_name} has missing or unknown keys")


def _token(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or _TOKEN_PATTERN.fullmatch(value) is None
    ):
        _reject("TOKEN_INVALID", f"{field_name} must be a bounded canonical token")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _reject("TOKEN_INVALID", f"{field_name} must contain valid UTF-8 text")
    return value


def _digest(value: object, field_name: str) -> str:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        _reject("HASH_INVALID", f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_hash(value: dict[str, object], field_name: str) -> str:
    content = {key: item for key, item in value.items() if key != "content_hash"}
    try:
        encoded = json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _reject("ENVELOPE_INVALID", f"{field_name} is outside the canonical JSON domain")
    return hashlib.sha256(encoded).hexdigest()


def _verify_content_hash(value: dict[str, object], field_name: str) -> str:
    supplied = _digest(value.get("content_hash"), f"{field_name}.content_hash")
    expected = _canonical_hash(value, field_name)
    if supplied != expected:
        _reject("CONTENT_HASH_MISMATCH", f"{field_name} content hash does not match")
    return expected


def _validate_nested_shapes(
    root: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    rule = _object(root["rule"], "rule")
    _shape(rule, _RULE_KEYS, "rule")
    base_rule = _object(rule["execution_rule_v1"], "rule.execution_rule_v1")
    _shape(base_rule, _V1_RULE_KEYS, "rule.execution_rule_v1")
    for field_name in ("buy_quantity", "sell_quantity"):
        quantity = _object(base_rule[field_name], f"execution_rule_v1.{field_name}")
        _shape(quantity, _V1_QUANTITY_KEYS, f"execution_rule_v1.{field_name}")
    price_range = _object(rule["price_submission_range"], "rule.price_submission_range")
    _shape(price_range, _PRICE_RANGE_KEYS, "rule.price_submission_range")

    market = _object(root["market_evidence"], "market_evidence")
    _shape(market, _MARKET_KEYS, "market_evidence")
    base_market = _object(market["market_evidence_v1"], "market_evidence.market_evidence_v1")
    _shape(base_market, _V1_MARKET_KEYS, "market_evidence.market_evidence_v1")
    for field_name in ("ask", "bid", "latest", "previous_close"):
        quote = _object(market[field_name], f"market_evidence.{field_name}")
        _shape(quote, _QUOTE_KEYS, f"market_evidence.{field_name}")

    order = _object(root["order"], "order")
    _shape(order, _ORDER_KEYS, "order")
    position_value = order["sell_position_evidence"]
    if position_value is not None:
        position = _object(position_value, "order.sell_position_evidence")
        _shape(position, _V1_POSITION_KEYS, "order.sell_position_evidence")

    decision = _object(root["decision"], "decision")
    _shape(decision, _DECISION_KEYS, "decision")
    return rule, market, order, decision


def _validate_decision_binding(
    decision: dict[str, object],
    order: dict[str, object],
    rule_hash: str,
    market_hash: str,
) -> None:
    status = _token(decision["status"], "decision.status")
    if status not in {"ALLOWED", "DENIED"}:
        _reject("DECISION_INVALID", "decision status is unsupported")
    reason_value = decision["reason_codes"]
    if type(reason_value) is not list:
        _reject("DECISION_INVALID", "decision.reason_codes must be a JSON array")
    reasons: list[str] = []
    for raw_reason in cast(list[object], reason_value):
        reason = _token(raw_reason, "decision.reason_codes[]")
        if reason not in _ALL_DECISION_REASON_CODES:
            _reject("DECISION_REASON_UNKNOWN", "decision contains an unsupported reason code")
        reasons.append(reason)
    if len(set(reasons)) != len(reasons):
        _reject("DECISION_INVALID", "decision.reason_codes must be unique")
    if (status == "ALLOWED" and reasons) or (status == "DENIED" and not reasons):
        _reject("DECISION_INVALID", "decision status and reason codes disagree")

    order_id = _token(order["order_id"], "order.order_id")
    decision_order_id = _token(decision["order_id"], "decision.order_id")
    decision_rule_hash = _digest(decision["rule_content_hash"], "decision.rule_content_hash")
    decision_market_hash = _digest(
        decision["market_evidence_content_hash"], "decision.market_evidence_content_hash"
    )
    if (
        decision_order_id != order_id
        or decision_rule_hash != rule_hash
        or decision_market_hash != market_hash
    ):
        _reject("DECISION_BINDING_MISMATCH", "decision does not bind this v2 order and evidence")
    if status == "DENIED":
        _reject("SERVER_DECISION_DENIED", "server v2 decision denied the order")


def _decimal(value: object, field_name: str, *, allow_zero: bool) -> Decimal:
    if (
        type(value) is not str
        or len(value) > _MAX_DECIMAL_WIRE_LENGTH
        or _DECIMAL_PATTERN.fullmatch(value) is None
    ):
        _reject("DECIMAL_INVALID", f"{field_name} must use canonical decimal text")
    parsed = Decimal(value)
    if not parsed.is_finite() or (parsed == 0 and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        _reject("DECIMAL_INVALID", f"{field_name} must be finite and {qualifier}")
    return parsed


def _integer(value: object, field_name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "nonnegative"
        _reject("PRICE_CAGE_INVALID_RULE", f"{field_name} must be a {qualifier} integer")
    return value


def _price_range_rule(value: dict[str, object]) -> PriceSubmissionRangeRule:
    market = _token(value["market"], "price_submission_range.market")
    board = _token(value["board"], "price_submission_range.board")
    tick = _decimal(value["price_tick"], "price_submission_range.price_tick", allow_zero=False)
    buy_ratio = _decimal(
        value["buy_deviation_ratio"], "price_submission_range.buy_deviation_ratio", allow_zero=True
    )
    sell_ratio = _decimal(
        value["sell_deviation_ratio"],
        "price_submission_range.sell_deviation_ratio",
        allow_zero=True,
    )
    buy_widening = _integer(value["buy_widening_ticks"], "buy_widening_ticks")
    sell_widening = _integer(value["sell_widening_ticks"], "sell_widening_ticks")
    minimum_distance = _integer(value["minimum_distance_ticks"], "minimum_distance_ticks")
    lower_floor = _integer(value["lower_floor_ticks"], "lower_floor_ticks", positive=True)
    rounding_mode = _token(value["rounding_mode"], "price_submission_range.rounding_mode")
    if rounding_mode != PriceRoundingMode.HALF_UP.value:
        _reject("PRICE_CAGE_INVALID_RULE", "price cage rounding mode is unsupported")
    try:
        return PriceSubmissionRangeRule(
            market=market,
            board=board,
            price_tick=tick,
            buy_deviation_ratio=buy_ratio,
            sell_deviation_ratio=sell_ratio,
            buy_widening_ticks=buy_widening,
            sell_widening_ticks=sell_widening,
            minimum_distance_ticks=minimum_distance,
            lower_floor_ticks=lower_floor,
            rounding_mode=PriceRoundingMode(rounding_mode),
        )
    except (ArithmeticError, TypeError, ValueError):
        _reject("PRICE_CAGE_INVALID_RULE", "price cage rule failed projection validation")


def _quote_value(value: dict[str, object], field_name: str) -> QuoteValue:
    state = _token(value["state"], f"{field_name}.state")
    try:
        quote_state = QuoteValueState(state)
    except ValueError:
        _reject("PRICE_CAGE_INVALID_QUOTE", f"{field_name}.state is unsupported")
    raw_price = value["value"]
    if quote_state is QuoteValueState.PRESENT:
        price = _decimal(raw_price, f"{field_name}.value", allow_zero=False)
    else:
        if raw_price is not None:
            _reject("PRICE_CAGE_INVALID_QUOTE", f"{field_name}.value must be null for this state")
        price = None
    try:
        return QuoteValue(state=quote_state, value=price)
    except (ArithmeticError, TypeError, ValueError):
        _reject("PRICE_CAGE_INVALID_QUOTE", f"{field_name} failed projection validation")


def _stage(value: object) -> PriceSubmissionStage:
    stage_text = _token(value, "market_evidence.stage")
    try:
        return PriceSubmissionStage(stage_text)
    except ValueError:
        _reject("SUBMISSION_STAGE_INVALID", "market stage is unsupported")


def _allowed_stages(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        _reject("SUBMISSION_STAGE_INVALID", "rule.allowed_stages must be a JSON array")
    raw_stages = cast(list[object], value)
    if len(raw_stages) > 1:
        _reject("SUBMISSION_STAGE_INVALID", "rule.allowed_stages is not supported")
    stages: list[str] = []
    for raw_stage in raw_stages:
        stage = _token(raw_stage, "rule.allowed_stages[]")
        if stage != PriceSubmissionStage.CONTINUOUS.value:
            _reject("SUBMISSION_STAGE_INVALID", "only CONTINUOUS may be in allowed_stages")
        stages.append(stage)
    return tuple(stages)


def _validate_price_submission(
    rule: dict[str, object],
    market: dict[str, object],
    order: dict[str, object],
) -> None:
    price_rule_data = _object(rule["price_submission_range"], "rule.price_submission_range")
    price_rule = _price_range_rule(price_rule_data)
    allowed_stages = _allowed_stages(rule["allowed_stages"])
    stage = _stage(market["stage"])

    base_rule = _object(rule["execution_rule_v1"], "rule.execution_rule_v1")
    base_market = _object(market["market_evidence_v1"], "market_evidence.market_evidence_v1")
    base_market_name = _token(base_rule["market"], "execution_rule_v1.market")
    base_board = _token(base_rule["board"], "execution_rule_v1.board")
    base_tick = _decimal(base_rule["price_tick"], "execution_rule_v1.price_tick", allow_zero=False)
    if (
        price_rule.market != base_market_name
        or price_rule.board != base_board
        or price_rule.price_tick != base_tick
    ):
        _reject("PRICE_CAGE_INVALID_RULE", "price cage market, board, or tick differs from v1 rule")
    if stage is not PriceSubmissionStage.CONTINUOUS or stage.value not in allowed_stages:
        _reject("SUBMISSION_STAGE_NOT_ALLOWED", "market stage is not enabled for submission")

    quotes = {
        field_name: _quote_value(
            _object(market[field_name], f"market_evidence.{field_name}"),
            f"market_evidence.{field_name}",
        )
        for field_name in ("ask", "bid", "latest", "previous_close")
    }
    order_side = _token(order["side"], "order.side")
    try:
        side = ExecutionSide(order_side)
    except ValueError:
        _reject("SIDE_INVALID", "order side is unsupported")

    cage = calculate_price_submission_range(
        price_rule,
        side=side,
        stage=stage,
        ask=quotes["ask"],
        bid=quotes["bid"],
        latest=quotes["latest"],
        previous_close=quotes["previous_close"],
    )
    if cage.status is not PriceSubmissionRangeStatus.CALCULATED:
        reason = cage.reason_code.value if cage.reason_code is not None else ""
        code = _CAGE_REASON_CODES.get(reason)
        if code is None:
            _reject("PRICE_CAGE_DENIED", "price cage did not produce a usable boundary")
        _reject(code, "price cage did not produce a usable boundary")
    if cage.boundary_price is None or cage.reference_price is None:
        _reject("PRICE_CAGE_RESULT_INVALID", "calculated price cage has incomplete output")

    boundary_mode = _token(
        base_market["price_boundary_mode"], "market_evidence_v1.price_boundary_mode"
    )
    if boundary_mode == "LIMITED":
        lower_value = _decimal(
            base_market["lower_limit_price"],
            "market_evidence_v1.lower_limit_price",
            allow_zero=False,
        )
        upper_value = _decimal(
            base_market["upper_limit_price"],
            "market_evidence_v1.upper_limit_price",
            allow_zero=False,
        )
        if not lower_value <= cage.reference_price <= upper_value:
            _reject(
                "SUBMISSION_REFERENCE_PRICE_OUTSIDE_BOUNDARY",
                "selected cage reference is outside the limited daily band",
            )

    limit_price = _decimal(order["limit_price"], "order.limit_price", allow_zero=False)
    outside_range = (
        limit_price > cage.boundary_price
        if side is ExecutionSide.BUY
        else limit_price < cage.boundary_price
    )
    if outside_range:
        _reject(
            "LIMIT_PRICE_OUTSIDE_SUBMISSION_RANGE",
            "order limit price is outside the calculated submission range",
        )


def _validate_submitted_at(value: datetime | None) -> datetime:
    submitted_at = datetime.now(UTC) if value is None else value
    if type(submitted_at) is not datetime or submitted_at.tzinfo is None:
        _reject("SUBMISSION_TIME_INVALID", "submitted_at must be timezone-aware")
    try:
        offset = submitted_at.utcoffset()
    except (OverflowError, ValueError):
        _reject("SUBMISSION_TIME_INVALID", "submitted_at timezone could not be read")
    if offset is None:
        _reject("SUBMISSION_TIME_INVALID", "submitted_at must be timezone-aware")
    try:
        submitted_at.astimezone(UTC)
    except (OverflowError, ValueError):
        _reject("SUBMISSION_TIME_INVALID", "submitted_at cannot be normalized to UTC")
    return submitted_at


def validate_execution_submission_v2(
    envelope: object, *, submitted_at: datetime | None = None
) -> None:
    """Validate strict v2 hashes, nested v1 constraints, phase, quotes, and cage.

    ``submitted_at`` is the local time used for the second freshness check. If
    omitted, the current UTC time is captured once. A successful return means
    only that this envelope satisfies the encoded tradability contract; it is
    not cash, risk, approval, livegate, or broker acceptance.
    """

    local_time = _validate_submitted_at(submitted_at)
    root = _object(envelope, "envelope")
    _shape(root, _TOP_KEYS, "envelope")
    if type(root["schema"]) is not str or root["schema"] != _SCHEMA:
        _reject("SCHEMA_UNSUPPORTED", "execution submission schema is not v2")

    rule, market, order, decision = _validate_nested_shapes(root)
    rule_hash = _verify_content_hash(rule, "rule")
    market_hash = _verify_content_hash(market, "market_evidence")
    _validate_decision_binding(decision, order, rule_hash, market_hash)

    # The local ALLOWED projection below is only a structural input to the v1
    # validator. The real v2 server decision was checked above and is never
    # replaced, persisted, or treated as authorization.
    base_rule = _object(rule["execution_rule_v1"], "rule.execution_rule_v1")
    base_market = _object(market["market_evidence_v1"], "market_evidence.market_evidence_v1")
    order_id = _token(order["order_id"], "order.order_id")
    base_decision = {
        "status": "ALLOWED",
        "reason_codes": [],
        "order_id": order_id,
        "rule_content_hash": base_rule["content_hash"],
        "market_evidence_content_hash": base_market["content_hash"],
    }
    derived_v1 = {
        "schema": _V1_SCHEMA,
        "as_of": root["as_of"],
        "rule": base_rule,
        "market_evidence": base_market,
        "order": order,
        "decision": base_decision,
    }
    validate_effective_constraints(derived_v1, submitted_at=local_time)
    _validate_price_submission(rule, market, order)


__all__: tuple[str, ...] = ("validate_execution_submission_v2",)
