"""Standalone validation of the current A-share execution constraint envelope.

The content hashes in this wire contract detect accidental changes and bind the
decision to its rule and market projection. They are not signatures and do not
authorize an order. This module deliberately has no broker, Django, or provider
dependencies and never supplies missing market or trading-rule defaults. An
ALLOWED result covers only these constraints and sellable-balance evidence; it
is not account-wide, portfolio, cash, risk, or broker-acceptance approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import NoReturn, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_SCHEMA: str = "a-share-execution-constraints.v1"
_TOP_KEYS: frozenset[str] = frozenset(
    {"schema", "as_of", "rule", "market_evidence", "order", "decision"}
)
_RULE_KEYS: frozenset[str] = frozenset(
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
_QUANTITY_KEYS: frozenset[str] = frozenset({"minimum", "step", "maximum"})
_MARKET_KEYS: frozenset[str] = frozenset(
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
_POSITION_KEYS: frozenset[str] = frozenset(
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
_DECISION_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "reason_codes",
        "order_id",
        "rule_content_hash",
        "market_evidence_content_hash",
    }
)
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[^\s]+")
_DIGEST_PATTERN: re.Pattern[str] = re.compile(r"[0-9a-f]{64}")
_MAX_DECIMAL_WIRE_LENGTH: int = 257
_DECIMAL_PATTERN: re.Pattern[str] = re.compile(
    r"(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?|-[1-9][0-9]*(?:\.[0-9]*[1-9])?"
)
_TIMESTAMP_PATTERN: re.Pattern[str] = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?Z"
)


class ExecutionConstraintViolation(ValueError):
    """A malformed, stale, or locally disallowed execution contract."""

    def __init__(self, code: str, message: str) -> None:
        """Retain the stable rejection code alongside its diagnostic message."""

        super().__init__(message)
        self.code: str = code


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


def _decimal(value: object, field_name: str, *, allow_zero: bool = False) -> Decimal:
    if (
        type(value) is not str
        or len(value) > _MAX_DECIMAL_WIRE_LENGTH
        or _DECIMAL_PATTERN.fullmatch(value) is None
    ):
        _reject("DECIMAL_INVALID", f"{field_name} must use canonical decimal text")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero):
        qualifier = "nonnegative" if allow_zero else "positive"
        _reject("DECIMAL_INVALID", f"{field_name} must be finite and {qualifier}")
    return parsed


def _is_whole_number(value: Decimal) -> bool:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        _reject("DECIMAL_INVALID", "decimal exponent must be finite")
    return exponent >= 0


def _scaled_integer(value: Decimal, scale: int) -> int:
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        _reject("DECIMAL_INVALID", "decimal exponent must be finite")
    digits = "".join(str(digit) for digit in parts.digits)
    coefficient = int(digits or "0")
    validated_exponent = int(exponent)
    result: int = cast(int, coefficient * (10 ** (validated_exponent + scale)))
    return result


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    value_exponent = _decimal_exponent(value)
    step_exponent = _decimal_exponent(step)
    scale = max(0, -value_exponent, -step_exponent)
    return _scaled_integer(value, scale) % _scaled_integer(step, scale) == 0


def _decimal_exponent(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        _reject("DECIMAL_INVALID", "decimal exponent must be finite")
    return exponent


def _instant(value: object, field_name: str) -> datetime:
    if type(value) is not str or _TIMESTAMP_PATTERN.fullmatch(value) is None:
        _reject("TIMESTAMP_INVALID", f"{field_name} must be a UTC RFC3339 Z instant")
    text = value
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _reject("TIMESTAMP_INVALID", f"{field_name} is not a valid UTC instant")
    return parsed.astimezone(UTC)


def _iso_date(value: object, field_name: str) -> date:
    if type(value) is not str:
        _reject("DATE_INVALID", f"{field_name} must be an ISO date")
    text = value
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        _reject("DATE_INVALID", f"{field_name} must be an ISO date")
    if parsed.isoformat() != text:
        _reject("DATE_INVALID", f"{field_name} must use canonical ISO format")
    return parsed


def _canonical_content_hash(value: dict[str, object], field_name: str) -> str:
    supplied = _digest(value.get("content_hash"), f"{field_name}.content_hash")
    content = {key: item for key, item in value.items() if key != "content_hash"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected = hashlib.sha256(encoded).hexdigest()
    if supplied != expected:
        _reject("CONTENT_HASH_MISMATCH", f"{field_name} content hash does not match")
    return expected


def _validate_evidence_window(
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    clock: datetime,
    field_name: str,
) -> None:
    if observed_at > available_at:
        _reject("EVIDENCE_WINDOW_INVALID", f"{field_name} observation follows availability")
    if observed_at > clock or available_at > clock:
        _reject("EVIDENCE_NOT_AVAILABLE", f"{field_name} was not available at the evaluation time")
    if clock >= valid_until:
        _reject("EVIDENCE_EXPIRED", f"{field_name} is expired at the evaluation time")


def _quantity_constraint(value: object, field_name: str) -> tuple[Decimal, Decimal, Decimal]:
    quantity = _object(value, field_name)
    _shape(quantity, _QUANTITY_KEYS, field_name)
    minimum = _decimal(quantity["minimum"], f"{field_name}.minimum")
    step = _decimal(quantity["step"], f"{field_name}.step")
    maximum = _decimal(quantity["maximum"], f"{field_name}.maximum")
    if any(not _is_whole_number(amount) for amount in (minimum, step, maximum)):
        _reject("QUANTITY_CONSTRAINT_INVALID", f"{field_name} values must be whole shares")
    if maximum < minimum:
        _reject("QUANTITY_CONSTRAINT_INVALID", f"{field_name} maximum is below minimum")
    return minimum, step, maximum


def _parse_position_evidence(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    position = _object(value, "order.sell_position_evidence")
    _shape(position, _POSITION_KEYS, "order.sell_position_evidence")
    _token(position["security_id"], "sell_position_evidence.security_id")
    account_id = position["account_id"]
    if type(account_id) is not int or account_id <= 0:
        _reject(
            "POSITION_EVIDENCE_INVALID",
            "sell_position_evidence.account_id must be a positive integer",
        )
    for field_name in ("source_id", "source_version"):
        _token(position[field_name], f"sell_position_evidence.{field_name}")
    _digest(position["source_hash"], "sell_position_evidence.source_hash")
    completeness = _token(position["completeness"], "sell_position_evidence.completeness")
    if completeness not in {"COMPLETE", "INCOMPLETE", "UNKNOWN"}:
        _reject("POSITION_EVIDENCE_INVALID", "sell position completeness is unsupported")
    available_value = position["available_to_sell_quantity"]
    restricted_value = position["restricted_quantity"]
    if completeness == "COMPLETE" and (available_value is None or restricted_value is None):
        _reject("POSITION_EVIDENCE_INVALID", "complete position evidence requires both quantities")
    if available_value is not None:
        available_quantity = _decimal(
            available_value, "sell_position_evidence.available_to_sell_quantity", allow_zero=True
        )
        if not _is_whole_number(available_quantity):
            _reject("POSITION_EVIDENCE_INVALID", "available sell quantity must be whole shares")
    if restricted_value is not None:
        restricted_quantity = _decimal(
            restricted_value, "sell_position_evidence.restricted_quantity", allow_zero=True
        )
        if not _is_whole_number(restricted_quantity):
            _reject("POSITION_EVIDENCE_INVALID", "restricted quantity must be whole shares")
    observed_at = _instant(position["observed_at"], "sell_position_evidence.observed_at")
    available_at = _instant(position["available_at"], "sell_position_evidence.available_at")
    valid_until = _instant(position["valid_until"], "sell_position_evidence.valid_until")
    if observed_at > available_at or available_at >= valid_until:
        _reject("EVIDENCE_WINDOW_INVALID", "sell position evidence window is invalid")
    return position


def _parse_reason_codes(value: object) -> list[str]:
    if type(value) is not list:
        _reject("DECISION_INVALID", "decision.reason_codes must be a JSON array")
    reasons: list[str] = []
    for item in cast(list[object], value):
        reasons.append(_token(item, "decision.reason_codes[]"))
    if len(set(reasons)) != len(reasons):
        _reject("DECISION_INVALID", "decision.reason_codes must be unique")
    return reasons


def _validate_submitted_at(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        _reject("SUBMISSION_TIME_INVALID", "submitted_at must be timezone-aware")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError):
        _reject("SUBMISSION_TIME_INVALID", "submitted_at timezone could not be read")
    if offset is None:
        _reject("SUBMISSION_TIME_INVALID", "submitted_at must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        _reject("SUBMISSION_TIME_INVALID", "submitted_at cannot be normalized to UTC")


def validate_effective_constraints(envelope: object, *, submitted_at: datetime) -> None:
    """Validate one current same-source projection at server and local submit time.

    The explicit ``submitted_at`` clock avoids hidden system-time behavior. The
    function raises :class:`ExecutionConstraintViolation` with a stable ``code``
    for malformed, stale, unsupported, or locally denied envelopes. A server
    ALLOWED decision is only an evaluation result; it cannot override a local
    denial.
    """

    root = _object(envelope, "envelope")
    _shape(root, _TOP_KEYS, "envelope")
    if root["schema"] != _SCHEMA:
        _reject("SCHEMA_UNSUPPORTED", "execution constraint schema is unsupported")

    as_of = _instant(root["as_of"], "as_of")
    local_time = _validate_submitted_at(submitted_at)
    if local_time < as_of:
        _reject("SUBMISSION_BEFORE_AS_OF", "local submission time precedes server evaluation time")

    rule = _object(root["rule"], "rule")
    market = _object(root["market_evidence"], "market_evidence")
    order = _object(root["order"], "order")
    decision = _object(root["decision"], "decision")
    _shape(rule, _RULE_KEYS, "rule")
    _shape(market, _MARKET_KEYS, "market_evidence")
    _shape(order, _ORDER_KEYS, "order")
    _shape(decision, _DECISION_KEYS, "decision")

    for field_name in (
        "rule_id",
        "rule_version",
        "security_id",
        "market",
        "board",
        "rule_source_id",
        "rule_source_version",
    ):
        _token(rule[field_name], f"rule.{field_name}")
    buy_min, buy_step, buy_max = _quantity_constraint(rule["buy_quantity"], "rule.buy_quantity")
    sell_min, sell_step, sell_max = _quantity_constraint(
        rule["sell_quantity"], "rule.sell_quantity"
    )
    odd_lot_mode = _token(rule["sell_odd_lot_mode"], "rule.sell_odd_lot_mode")
    if odd_lot_mode not in {
        "FORBID",
        "SELLABLE_BALANCE_TO_ZERO",
        "SELL_ODD_REMAINDER_ONCE",
    }:
        _reject("RULE_INVALID", "rule sell odd-lot mode is unsupported")
    if odd_lot_mode == "SELL_ODD_REMAINDER_ONCE" and sell_min != sell_step:
        _reject(
            "RULE_INVALID",
            "SELL_ODD_REMAINDER_ONCE requires sell minimum and step to match",
        )
    price_tick = _decimal(rule["price_tick"], "rule.price_tick")
    _digest(rule["rule_source_hash"], "rule.rule_source_hash")
    rule_observed = _instant(rule["source_observed_at"], "rule.source_observed_at")
    rule_available = _instant(rule["source_available_at"], "rule.source_available_at")
    effective_from = _instant(rule["effective_from"], "rule.effective_from")
    rule_valid_until = _instant(rule["valid_until"], "rule.valid_until")
    if effective_from >= rule_valid_until:
        _reject("RULE_WINDOW_INVALID", "rule effective window is invalid")

    for field_name in (
        "security_id",
        "market",
        "board",
        "calendar_id",
        "calendar_version",
        "session_id",
        "session_timezone",
        "market_source_id",
        "market_source_version",
    ):
        _token(market[field_name], f"market_evidence.{field_name}")
    trading_date = _iso_date(market["trading_date"], "market_evidence.trading_date")
    _digest(market["calendar_source_hash"], "market_evidence.calendar_source_hash")
    _digest(market["market_source_hash"], "market_evidence.market_source_hash")
    calendar_observed = _instant(market["calendar_observed_at"], "calendar_observed_at")
    calendar_available = _instant(market["calendar_available_at"], "calendar_available_at")
    calendar_valid_until = _instant(market["calendar_valid_until"], "calendar_valid_until")
    market_observed = _instant(market["market_observed_at"], "market_observed_at")
    market_available = _instant(market["market_available_at"], "market_available_at")
    market_valid_until = _instant(market["market_valid_until"], "market_valid_until")
    session_open = _instant(market["session_open_at"], "session_open_at")
    session_close = _instant(market["session_close_at"], "session_close_at")
    if session_open >= session_close:
        _reject("SESSION_INTERVAL_INVALID", "session opening must precede closing")
    timezone_name = cast(str, market["session_timezone"])
    try:
        session_zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        _reject("TIMEZONE_INVALID", "session timezone is unknown")
    session_state = _token(market["session_state"], "market_evidence.session_state")
    if session_state not in {"OPEN", "CLOSED", "UNKNOWN"}:
        _reject("SESSION_INVALID", "session state is unsupported")
    security_state = _token(market["security_state"], "market_evidence.security_state")
    if security_state not in {"TRADING", "SUSPENDED", "DELISTED", "UNKNOWN"}:
        _reject("SECURITY_STATE_INVALID", "security state is unsupported")
    boundary_mode = _token(market["price_boundary_mode"], "market_evidence.price_boundary_mode")
    if boundary_mode not in {"LIMITED", "UNRESTRICTED", "UNKNOWN"}:
        _reject("BOUNDARY_INVALID", "price boundary mode is unsupported")
    reference_price = _decimal(market["reference_price"], "reference_price")
    lower_value = market["lower_limit_price"]
    upper_value = market["upper_limit_price"]
    lower_limit: Decimal | None = None
    upper_limit: Decimal | None = None
    if boundary_mode == "LIMITED":
        if lower_value is None or upper_value is None:
            _reject("BOUNDARY_INVALID", "LIMITED boundary requires both prices")
        lower_limit = _decimal(lower_value, "lower_limit_price")
        upper_limit = _decimal(upper_value, "upper_limit_price")
        if lower_limit > upper_limit:
            _reject("BOUNDARY_INVALID", "LIMITED boundary prices are reversed")
    elif lower_value is not None or upper_value is not None:
        _reject("BOUNDARY_INVALID", "non-LIMITED boundary requires null prices")

    order_id = _token(order["order_id"], "order.order_id")
    account_id = order["account_id"]
    if type(account_id) is not int or account_id <= 0:
        _reject("ORDER_INVALID", "order.account_id must be a positive integer")
    order_security = _token(order["security_id"], "order.security_id")
    side = _token(order["side"], "order.side")
    if side not in {"BUY", "SELL"}:
        _reject("SIDE_INVALID", "order side is unsupported")
    quantity = _decimal(order["quantity"], "order.quantity")
    if not _is_whole_number(quantity):
        _reject("QUANTITY_INVALID", "order quantity must be a whole number of shares")
    limit_price = _decimal(order["limit_price"], "order.limit_price")
    position = _parse_position_evidence(order["sell_position_evidence"])
    if position is not None:
        position_security = cast(str, position["security_id"])
        if side == "SELL" and position_security != order_security:
            _reject("POSITION_SECURITY_MISMATCH", "position evidence security differs from order")
        if side == "SELL" and position["account_id"] != account_id:
            _reject("POSITION_ACCOUNT_MISMATCH", "position evidence account differs from order")
        position_observed = _instant(position["observed_at"], "sell_position_evidence.observed_at")
        position_available = _instant(
            position["available_at"], "sell_position_evidence.available_at"
        )
        position_valid = _instant(position["valid_until"], "sell_position_evidence.valid_until")
    else:
        position_observed = None
        position_available = None
        position_valid = None

    status = _token(decision["status"], "decision.status")
    if status not in {"ALLOWED", "DENIED"}:
        _reject("DECISION_INVALID", "decision status is unsupported")
    reason_codes = _parse_reason_codes(decision["reason_codes"])
    decision_order_id = _token(decision["order_id"], "decision.order_id")
    decision_rule_hash = _digest(decision["rule_content_hash"], "decision.rule_content_hash")
    decision_market_hash = _digest(
        decision["market_evidence_content_hash"], "decision.market_evidence_content_hash"
    )
    if (status == "ALLOWED" and reason_codes) or (status == "DENIED" and not reason_codes):
        _reject("DECISION_INVALID", "decision status and reason codes disagree")

    rule_hash = _canonical_content_hash(rule, "rule")
    market_hash = _canonical_content_hash(market, "market_evidence")
    if (
        decision_order_id != order_id
        or decision_rule_hash != rule_hash
        or decision_market_hash != market_hash
    ):
        _reject("DECISION_BINDING_MISMATCH", "decision is not bound to this order and evidence")
    if status == "DENIED":
        _reject("SERVER_DECISION_DENIED", "server decision denied the order")

    if side == "SELL":
        if position is None:
            _reject("POSITION_EVIDENCE_MISSING", "sell orders require sell-position evidence")
        if cast(str, position["completeness"]) != "COMPLETE":
            _reject(
                "POSITION_EVIDENCE_INCOMPLETE", "sell orders require complete position evidence"
            )

    rule_security = cast(str, rule["security_id"])
    market_security = cast(str, market["security_id"])
    if rule_security != market_security or rule_security != order_security:
        _reject("SECURITY_MISMATCH", "rule, market, and order security ids must match exactly")
    if rule["market"] != market["market"]:
        _reject("RULE_MARKET_MISMATCH", "rule and market evidence market must match exactly")
    if rule["board"] != market["board"]:
        _reject("RULE_BOARD_MISMATCH", "rule and market evidence board must match exactly")

    for clock in (as_of, local_time):
        _validate_evidence_window(
            rule_observed, rule_available, rule_valid_until, clock, "rule source"
        )
        if clock < effective_from:
            _reject("RULE_NOT_EFFECTIVE", "rule is not effective at the evaluation time")
        _validate_evidence_window(
            calendar_observed,
            calendar_available,
            calendar_valid_until,
            clock,
            "calendar evidence",
        )
        _validate_evidence_window(
            market_observed, market_available, market_valid_until, clock, "market evidence"
        )
        if position is not None and side == "SELL":
            assert position_observed is not None
            assert position_available is not None
            assert position_valid is not None
            _validate_evidence_window(
                position_observed,
                position_available,
                position_valid,
                clock,
                "sell position evidence",
            )
        local_date = clock.astimezone(session_zone).date()
        if local_date != trading_date:
            _reject("OUTSIDE_TRADING_DATE", "evaluation time is outside the evidence trading date")
        if not session_open <= clock < session_close:
            _reject("OUTSIDE_SESSION", "evaluation time is outside the evidenced session")

    if session_state != "OPEN":
        _reject("SESSION_NOT_OPEN", "session evidence is not OPEN")
    if security_state != "TRADING":
        _reject("SECURITY_NOT_TRADING", "security state is not TRADING")
    if boundary_mode == "UNKNOWN":
        _reject("PRICE_BOUNDARY_UNKNOWN", "price boundary is explicitly unknown")

    if not _is_multiple(reference_price, price_tick):
        _reject("REFERENCE_PRICE_NOT_ON_TICK", "reference price is not on the rule tick")
    if not _is_multiple(limit_price, price_tick):
        _reject("LIMIT_PRICE_NOT_ON_TICK", "limit price is not on the rule tick")
    if boundary_mode == "LIMITED":
        assert lower_limit is not None
        assert upper_limit is not None
        if not lower_limit <= reference_price <= upper_limit:
            _reject("REFERENCE_PRICE_OUTSIDE_BOUNDARY", "reference price is outside the limit band")
        if not lower_limit <= limit_price <= upper_limit:
            _reject("LIMIT_PRICE_OUTSIDE_BOUNDARY", "limit price is outside the limit band")

    if side == "BUY":
        minimum, step, maximum = buy_min, buy_step, buy_max
    else:
        minimum, step, maximum = sell_min, sell_step, sell_max
    if quantity > maximum:
        _reject("QUANTITY_ABOVE_MAXIMUM", "order quantity exceeds the side-specific maximum")
    if side == "SELL":
        assert position is not None
        available_quantity = _decimal(
            position["available_to_sell_quantity"],
            "sell_position_evidence.available_to_sell_quantity",
            allow_zero=True,
        )
        if quantity > available_quantity:
            _reject(
                "QUANTITY_EXCEEDS_AVAILABLE", "sell quantity exceeds evidenced available balance"
            )
    on_step = _is_multiple(quantity, step)
    below_minimum = quantity < minimum
    odd_lot_exception = side == "SELL" and (not on_step or below_minimum)
    if odd_lot_exception:
        if odd_lot_mode == "SELLABLE_BALANCE_TO_ZERO":
            assert position is not None
            available_quantity = _decimal(
                position["available_to_sell_quantity"],
                "sell_position_evidence.available_to_sell_quantity",
                allow_zero=True,
            )
            restricted_quantity = _decimal(
                position["restricted_quantity"],
                "sell_position_evidence.restricted_quantity",
                allow_zero=True,
            )
            if restricted_quantity != 0:
                _reject(
                    "POSITION_HAS_RESTRICTED_BALANCE",
                    "odd-lot evidence includes restricted shares",
                )
            if quantity != available_quantity:
                _reject(
                    "POSITION_NOT_FULL_BALANCE",
                    "odd-lot sell must equal evidenced sellable balance",
                )
        elif odd_lot_mode == "SELL_ODD_REMAINDER_ONCE" and not on_step:
            assert position is not None
            restricted_quantity = _decimal(
                position["restricted_quantity"],
                "sell_position_evidence.restricted_quantity",
                allow_zero=True,
            )
            if restricted_quantity != 0:
                _reject(
                    "POSITION_HAS_RESTRICTED_BALANCE",
                    "odd-lot evidence includes restricted shares",
                )
            available_share_count = _scaled_integer(available_quantity, 0)
            order_share_count = _scaled_integer(quantity, 0)
            step_share_count = _scaled_integer(step, 0)
            if (available_share_count - order_share_count) % step_share_count != 0:
                _reject(
                    "QUANTITY_NOT_ON_STEP",
                    "odd-lot sell must leave a whole-step remainder",
                )
        elif not on_step:
            _reject(
                "QUANTITY_NOT_ON_STEP",
                "sell quantity is not on step and odd lots are forbidden",
            )
        else:
            _reject(
                "QUANTITY_BELOW_MINIMUM",
                "sell quantity is below minimum and odd lots are forbidden",
            )
    elif below_minimum:
        _reject("QUANTITY_BELOW_MINIMUM", "order quantity is below the side-specific minimum")
    elif not on_step:
        _reject("QUANTITY_NOT_ON_STEP", "order quantity is not on the side-specific step")


__all__: tuple[str, ...] = (
    "ExecutionConstraintViolation",
    "validate_effective_constraints",
)
