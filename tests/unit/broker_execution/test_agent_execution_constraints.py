from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from qmt_agent.execution_constraints import (
    ExecutionConstraintViolation,
    validate_effective_constraints,
)

# Synthetic test fixtures only. These values are not official or production rules.
TEST_FIXTURE_ONLY_MAIN = {
    "as_of": "2026-10-16T01:45:00Z",
    "rule": {
        "rule_id": "synthetic-main-rule",
        "rule_version": "fixture-v1",
        "security_id": "600000.SH",
        "market": "SH",
        "board": "MAIN",
        "buy_quantity": {"minimum": "10", "step": "10", "maximum": "1000"},
        "sell_quantity": {"minimum": "10", "step": "10", "maximum": "1000"},
        "sell_odd_lot_mode": "FORBID",
        "price_tick": "0.05",
        "rule_source_id": "synthetic-rule-source",
        "rule_source_version": "fixture-v1",
        "rule_source_hash": "a" * 64,
        "source_observed_at": "2026-10-15T23:45:00Z",
        "source_available_at": "2026-10-16T00:45:00Z",
        "effective_from": "2026-10-15T01:45:00Z",
        "valid_until": "2026-10-16T02:45:00Z",
    },
    "market_evidence": {
        "security_id": "600000.SH",
        "market": "SH",
        "board": "MAIN",
        "trading_date": "2026-10-16",
        "calendar_id": "synthetic-calendar",
        "calendar_version": "fixture-v1",
        "calendar_source_hash": "b" * 64,
        "calendar_observed_at": "2026-10-15T01:45:00Z",
        "calendar_available_at": "2026-10-16T00:45:00Z",
        "calendar_valid_until": "2026-10-17T01:45:00Z",
        "session_id": "synthetic-day-session",
        "session_timezone": "Asia/Shanghai",
        "session_open_at": "2026-10-16T01:30:00Z",
        "session_close_at": "2026-10-16T03:30:00Z",
        "session_state": "OPEN",
        "security_state": "TRADING",
        "market_source_id": "synthetic-quote-source",
        "market_source_version": "fixture-v1",
        "market_source_hash": "c" * 64,
        "price_boundary_mode": "LIMITED",
        "lower_limit_price": "9",
        "upper_limit_price": "11",
        "reference_price": "10",
        "market_observed_at": "2026-10-16T01:44:58Z",
        "market_available_at": "2026-10-16T01:44:59Z",
        "market_valid_until": "2026-10-16T02:00:00Z",
    },
    "order": {
        "order_id": "synthetic-order-1",
        "account_id": 7,
        "security_id": "600000.SH",
        "side": "BUY",
        "quantity": "20",
        "limit_price": "10",
        "sell_position_evidence": None,
    },
    "decision": {
        "status": "ALLOWED",
        "reason_codes": [],
        "order_id": "synthetic-order-1",
    },
}


def _content_hash(value: dict[str, object]) -> str:
    content = {key: item for key, item in value.items() if key != "content_hash"}
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _envelope() -> dict[str, object]:
    envelope = deepcopy(TEST_FIXTURE_ONLY_MAIN)
    envelope["schema"] = "a-share-execution-constraints.v1"
    rule = envelope["rule"]
    market = envelope["market_evidence"]
    assert isinstance(rule, dict)
    assert isinstance(market, dict)
    rule["content_hash"] = _content_hash(rule)
    market["content_hash"] = _content_hash(market)
    decision = envelope["decision"]
    assert isinstance(decision, dict)
    decision["rule_content_hash"] = rule["content_hash"]
    decision["market_evidence_content_hash"] = market["content_hash"]
    return envelope


def _reseal(envelope: dict[str, object]) -> dict[str, object]:
    rule = envelope["rule"]
    market = envelope["market_evidence"]
    decision = envelope["decision"]
    assert isinstance(rule, dict)
    assert isinstance(market, dict)
    assert isinstance(decision, dict)
    rule["content_hash"] = _content_hash(rule)
    market["content_hash"] = _content_hash(market)
    decision["rule_content_hash"] = rule["content_hash"]
    decision["market_evidence_content_hash"] = market["content_hash"]
    order = envelope["order"]
    assert isinstance(order, dict)
    decision["order_id"] = order["order_id"]
    return envelope


def _nested(envelope: dict[str, object], key: str) -> dict[str, object]:
    value = envelope[key]
    assert isinstance(value, dict)
    return value


def _assert_code(
    envelope: object,
    code: str,
    *,
    submitted_at: datetime = datetime(2026, 10, 16, 1, 45, tzinfo=UTC),
) -> None:
    with pytest.raises(ExecutionConstraintViolation) as captured:
        validate_effective_constraints(envelope, submitted_at=submitted_at)
    assert captured.value.code == code


def test_synthetic_mainboard_fixture_allows_exact_current_order() -> None:
    validate_effective_constraints(
        _envelope(), submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC)
    )


@pytest.mark.parametrize(
    ("field_name", "value", "code"),
    (
        ("market", "SZ", "RULE_MARKET_MISMATCH"),
        ("board", "STAR", "RULE_BOARD_MISMATCH"),
    ),
)
def test_market_evidence_identity_must_match_rule(field_name: str, value: str, code: str) -> None:
    envelope = _envelope()
    _nested(envelope, "market_evidence")[field_name] = value
    _reseal(envelope)

    _assert_code(envelope, code)


def test_synthetic_star_fixture_uses_its_explicit_rule_and_tick() -> None:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    market = _nested(envelope, "market_evidence")
    order = _nested(envelope, "order")
    rule.update(
        {
            "security_id": "688001.SH",
            "board": "STAR",
            "buy_quantity": {"minimum": "3", "step": "1", "maximum": "700"},
            "sell_quantity": {"minimum": "2", "step": "2", "maximum": "800"},
            "price_tick": "0.01",
        }
    )
    market.update(
        {
            "security_id": "688001.SH",
            "board": "STAR",
            "lower_limit_price": "8",
            "upper_limit_price": "12",
            "reference_price": "10.01",
        }
    )
    order.update({"security_id": "688001.SH", "quantity": "3", "limit_price": "10.02"})
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        ("schema", "a-share-execution-constraints.v2", "SCHEMA_UNSUPPORTED"),
        ("side", "SHORT", "SIDE_INVALID"),
        ("session_state", "UNKNOWN", "SESSION_NOT_OPEN"),
        ("security_state", "SUSPENDED", "SECURITY_NOT_TRADING"),
        ("price_boundary_mode", "UNKNOWN", "PRICE_BOUNDARY_UNKNOWN"),
    ],
)
def test_explicit_unsupported_states_fail_closed(path: str, value: str, code: str) -> None:
    envelope = _envelope()
    if path == "schema":
        envelope[path] = value
    elif path == "side":
        _nested(envelope, "order")[path] = value
    elif path in {"session_state", "security_state", "price_boundary_mode"}:
        _nested(envelope, "market_evidence")[path] = value
        if path == "price_boundary_mode" and value == "UNKNOWN":
            _nested(envelope, "market_evidence")["lower_limit_price"] = None
            _nested(envelope, "market_evidence")["upper_limit_price"] = None
    _reseal(envelope)

    _assert_code(envelope, code)


@pytest.mark.parametrize(
    ("container", "key"),
    [
        ("envelope", "unexpected"),
        ("rule", "unexpected"),
        ("market_evidence", "unexpected"),
        ("order", "unexpected"),
        ("decision", "unexpected"),
        ("buy_quantity", "unexpected"),
    ],
)
def test_unknown_wire_keys_are_rejected(container: str, key: str) -> None:
    envelope = _envelope()
    if container == "envelope":
        envelope[key] = "ignored"
    elif container in {"rule", "market_evidence", "order", "decision"}:
        _nested(envelope, container)[key] = "ignored"
    else:
        _nested(envelope, "rule")[container][key] = "ignored"  # type: ignore[index]

    _assert_code(envelope, "WIRE_KEYS_INVALID")


@pytest.mark.parametrize(
    ("container", "key"),
    [
        ("envelope", "as_of"),
        ("rule", "rule_version"),
        ("market_evidence", "calendar_version"),
        ("order", "quantity"),
        ("decision", "status"),
        ("buy_quantity", "step"),
    ],
)
def test_missing_wire_keys_are_rejected(container: str, key: str) -> None:
    envelope = _envelope()
    if container == "envelope":
        del envelope[key]
    elif container in {"rule", "market_evidence", "order", "decision"}:
        del _nested(envelope, container)[key]
    else:
        del _nested(envelope, "rule")[container][key]  # type: ignore[index]

    _assert_code(envelope, "WIRE_KEYS_INVALID")


def test_hashes_bind_complete_rule_and_market_objects_and_are_not_authority() -> None:
    envelope = _envelope()
    # Re-sealing after a semantic change proves a hash is integrity binding only;
    # the validator still applies all local constraints independently.
    _nested(envelope, "order")["quantity"] = "15"
    _reseal(envelope)

    _assert_code(envelope, "QUANTITY_NOT_ON_STEP")


@pytest.mark.parametrize("container", ["rule", "market_evidence"])
def test_hash_tampering_is_rejected(container: str) -> None:
    envelope = _envelope()
    _nested(envelope, container)["content_hash"] = "0" * 64

    _assert_code(envelope, "CONTENT_HASH_MISMATCH")


def test_decision_hash_binding_and_order_binding_are_required() -> None:
    envelope = _envelope()
    _nested(envelope, "decision")["rule_content_hash"] = "0" * 64
    _assert_code(envelope, "DECISION_BINDING_MISMATCH")

    envelope = _envelope()
    _nested(envelope, "decision")["order_id"] = "other-order"
    _assert_code(envelope, "DECISION_BINDING_MISMATCH")


def test_server_denial_fails_closed_and_status_reasons_must_agree() -> None:
    envelope = _envelope()
    decision = _nested(envelope, "decision")
    decision.update({"status": "DENIED", "reason_codes": ["LOCAL_RULE_DENIED"]})
    _assert_code(envelope, "SERVER_DECISION_DENIED")

    envelope = _envelope()
    _nested(envelope, "decision")["reason_codes"] = ["SHOULD_BE_EMPTY"]
    _assert_code(envelope, "DECISION_INVALID")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("security_id", "000001.SZ", "SECURITY_MISMATCH"),
        ("account_id", True, "ORDER_INVALID"),
        ("account_id", 0, "ORDER_INVALID"),
        ("quantity", 20, "DECIMAL_INVALID"),
        ("quantity", "2e1", "DECIMAL_INVALID"),
        ("quantity", "20.0", "DECIMAL_INVALID"),
        ("quantity", "-0", "DECIMAL_INVALID"),
        ("limit_price", "NaN", "DECIMAL_INVALID"),
    ],
)
def test_order_identity_and_decimal_wire_are_narrowed(field: str, value: object, code: str) -> None:
    envelope = _envelope()
    _nested(envelope, "order")[field] = value
    _reseal(envelope)

    _assert_code(envelope, code)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("source_available_at", "2026-10-16T01:46:00Z", "EVIDENCE_NOT_AVAILABLE"),
        ("source_observed_at", "2026-10-16T01:46:00Z", "EVIDENCE_NOT_AVAILABLE"),
        ("valid_until", "2026-10-16T01:45:00Z", "EVIDENCE_EXPIRED"),
        ("effective_from", "2026-10-16T01:46:00Z", "RULE_NOT_EFFECTIVE"),
    ],
)
def test_rule_time_windows_are_checked_at_server_evaluation(
    field: str, value: str, code: str
) -> None:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    rule[field] = value
    if field == "source_observed_at":
        rule["source_available_at"] = value
    _reseal(envelope)

    _assert_code(envelope, code)


@pytest.mark.parametrize(
    ("container", "field", "value"),
    [
        ("market_evidence", "calendar_available_at", "2026-10-16T01:46:00Z"),
        ("market_evidence", "calendar_valid_until", "2026-10-16T01:45:00Z"),
        ("market_evidence", "market_available_at", "2026-10-16T01:46:00Z"),
        ("market_evidence", "market_valid_until", "2026-10-16T01:45:00Z"),
    ],
)
def test_calendar_and_market_evidence_must_be_available_and_fresh(
    container: str, field: str, value: str
) -> None:
    envelope = _envelope()
    _nested(envelope, container)[field] = value
    _reseal(envelope)

    expected = "EVIDENCE_NOT_AVAILABLE" if "available" in field else "EVIDENCE_EXPIRED"
    _assert_code(envelope, expected)


def test_local_submit_clock_rechecks_expiry_and_ordering() -> None:
    envelope = _envelope()
    _assert_code(
        envelope,
        "EVIDENCE_EXPIRED",
        submitted_at=datetime(2026, 10, 16, 2, 1, tzinfo=UTC),
    )
    _assert_code(
        envelope,
        "SUBMISSION_BEFORE_AS_OF",
        submitted_at=datetime(2026, 10, 16, 1, 44, tzinfo=UTC),
    )


def test_naive_or_noncanonical_wire_datetimes_are_rejected() -> None:
    envelope = _envelope()
    _assert_code(envelope, "SUBMISSION_TIME_INVALID", submitted_at=datetime(2026, 10, 16, 1, 45))

    envelope = _envelope()
    envelope["as_of"] = "2026-10-16T01:45:00+00:00"
    _assert_code(envelope, "TIMESTAMP_INVALID")

    envelope = _envelope()
    envelope["as_of"] = "2026-13-16T01:45:00Z"
    _assert_code(envelope, "TIMESTAMP_INVALID")


class _NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


class _InvalidOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        raise ValueError("invalid offset")

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


def test_submitted_at_rejects_timezone_without_a_valid_offset() -> None:
    envelope = _envelope()
    _assert_code(
        envelope,
        "SUBMISSION_TIME_INVALID",
        submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=_NoOffset()),
    )
    _assert_code(
        envelope,
        "SUBMISSION_TIME_INVALID",
        submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=_InvalidOffset()),
    )


@pytest.mark.parametrize("value", ["", "invalid token", "x" * 193])
def test_noncanonical_tokens_are_rejected(value: str) -> None:
    envelope = _envelope()
    _nested(envelope, "rule")["board"] = value
    _reseal(envelope)

    _assert_code(envelope, "TOKEN_INVALID")


def test_malformed_digest_and_non_utf8_token_are_rejected() -> None:
    envelope = _envelope()
    _nested(envelope, "rule")["rule_source_hash"] = "G" * 64
    _reseal(envelope)
    _assert_code(envelope, "HASH_INVALID")

    envelope = _envelope()
    _nested(envelope, "rule")["board"] = "\ud800"
    _assert_code(envelope, "TOKEN_INVALID")


@pytest.mark.parametrize("value", ["-1", "0", "1" * 258, "0." + "0" * 257 + "1"])
def test_decimal_sign_zero_and_protocol_bounds_are_rejected(value: str) -> None:
    envelope = _envelope()
    _nested(envelope, "order")["quantity"] = value
    _reseal(envelope)

    _assert_code(envelope, "DECIMAL_INVALID")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("session_state", "CLOSED", "SESSION_NOT_OPEN"),
        ("security_state", "DELISTED", "SECURITY_NOT_TRADING"),
        ("session_timezone", "Not/AZone", "TIMEZONE_INVALID"),
        ("trading_date", "2026-10-15", "OUTSIDE_TRADING_DATE"),
        ("session_close_at", "2026-10-16T01:40:00Z", "OUTSIDE_SESSION"),
    ],
)
def test_calendar_session_and_security_status_are_enforced(
    field: str, value: str, code: str
) -> None:
    envelope = _envelope()
    _nested(envelope, "market_evidence")[field] = value
    _reseal(envelope)

    _assert_code(envelope, code)


def test_session_local_date_is_checked_at_submission_time() -> None:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    market = _nested(envelope, "market_evidence")
    market.update(
        {
            "session_timezone": "Pacific/Kiritimati",
            "session_close_at": "2026-10-16T12:00:00Z",
            "calendar_valid_until": "2026-10-16T12:00:00Z",
            "market_valid_until": "2026-10-16T12:00:00Z",
        }
    )
    rule["valid_until"] = "2026-10-16T12:00:00Z"
    _reseal(envelope)
    _assert_code(
        envelope,
        "OUTSIDE_TRADING_DATE",
        submitted_at=datetime(2026, 10, 16, 10, 0, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("reference_price", "10.01", "REFERENCE_PRICE_NOT_ON_TICK"),
        ("lower_limit_price", "12", "BOUNDARY_INVALID"),
        ("price_boundary_mode", "UNRESTRICTED", "BOUNDARY_INVALID"),
    ],
)
def test_prices_and_explicit_boundary_shapes_are_enforced(
    field: str, value: str, code: str
) -> None:
    envelope = _envelope()
    _nested(envelope, "market_evidence")[field] = value
    _reseal(envelope)

    _assert_code(envelope, code)


def test_limit_price_must_be_on_tick_and_inside_limited_band() -> None:
    envelope = _envelope()
    _nested(envelope, "order")["limit_price"] = "10.01"
    _reseal(envelope)
    _assert_code(envelope, "LIMIT_PRICE_NOT_ON_TICK")

    envelope = _envelope()
    _nested(envelope, "order")["limit_price"] = "11.05"
    _reseal(envelope)
    _assert_code(envelope, "LIMIT_PRICE_OUTSIDE_BOUNDARY")


def test_unrestricted_boundary_is_explicit_and_still_checks_tick() -> None:
    envelope = _envelope()
    market = _nested(envelope, "market_evidence")
    market.update(
        {
            "price_boundary_mode": "UNRESTRICTED",
            "lower_limit_price": None,
            "upper_limit_price": None,
        }
    )
    _reseal(envelope)
    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


@pytest.mark.parametrize(
    ("side", "quantity", "code"),
    [
        ("BUY", "5", "QUANTITY_BELOW_MINIMUM"),
        ("BUY", "15", "QUANTITY_NOT_ON_STEP"),
        ("BUY", "1010", "QUANTITY_ABOVE_MAXIMUM"),
        ("SELL", "15", "QUANTITY_NOT_ON_STEP"),
    ],
)
def test_side_specific_quantity_minimum_step_and_maximum_are_checked(
    side: str, quantity: str, code: str
) -> None:
    envelope = _envelope()
    _nested(envelope, "order").update({"side": side, "quantity": quantity})
    if side == "SELL":
        _nested(envelope, "order")["sell_position_evidence"] = _sell_position(
            quantity="30", restricted_quantity="5"
        )
    _reseal(envelope)

    _assert_code(envelope, code)


def _sell_position(
    *,
    quantity: str = "15",
    security_id: str = "600000.SH",
    account_id: int = 7,
    completeness: str = "COMPLETE",
    restricted_quantity: str = "0",
    available_at: str = "2026-10-16T01:44:59Z",
    valid_until: str = "2026-10-16T02:00:00Z",
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "account_id": account_id,
        "available_to_sell_quantity": quantity,
        "restricted_quantity": restricted_quantity,
        "completeness": completeness,
        "source_id": "synthetic-position-source",
        "source_version": "fixture-v1",
        "source_hash": "d" * 64,
        "observed_at": "2026-10-16T01:44:58Z",
        "available_at": available_at,
        "valid_until": valid_until,
    }


def _odd_lot_sell_envelope() -> dict[str, object]:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    rule["sell_odd_lot_mode"] = "SELLABLE_BALANCE_TO_ZERO"
    _nested(envelope, "order").update(
        {
            "side": "SELL",
            "quantity": "15",
            "sell_position_evidence": _sell_position(),
        }
    )
    return _reseal(envelope)


def _odd_remainder_once_sell_envelope(
    *,
    available_quantity: str = "29",
    quantity: str = "9",
    restricted_quantity: str = "0",
    maximum: str = "1000",
) -> dict[str, object]:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    rule["sell_odd_lot_mode"] = "SELL_ODD_REMAINDER_ONCE"
    rule["sell_quantity"] = {"minimum": "10", "step": "10", "maximum": maximum}
    _nested(envelope, "order").update(
        {
            "side": "SELL",
            "quantity": quantity,
            "sell_position_evidence": _sell_position(
                quantity=available_quantity,
                restricted_quantity=restricted_quantity,
            ),
        }
    )
    return _reseal(envelope)


def _regular_sell_envelope(
    *,
    quantity: str = "20",
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    envelope = _envelope()
    _nested(envelope, "order").update(
        {
            "side": "SELL",
            "quantity": quantity,
            "sell_position_evidence": (
                evidence
                if evidence is not None
                else _sell_position(quantity="30", restricted_quantity="5")
            ),
        }
    )
    return _reseal(envelope)


def test_every_sell_requires_fresh_complete_evidence_and_available_balance() -> None:
    envelope = _regular_sell_envelope()
    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))

    invalid_cases: tuple[tuple[dict[str, object] | None, str], ...] = (
        (None, "POSITION_EVIDENCE_MISSING"),
        (_sell_position(completeness="INCOMPLETE"), "POSITION_EVIDENCE_INCOMPLETE"),
        (_sell_position(completeness="UNKNOWN"), "POSITION_EVIDENCE_INCOMPLETE"),
        (_sell_position(security_id="000001.SZ"), "POSITION_SECURITY_MISMATCH"),
        (_sell_position(account_id=8), "POSITION_ACCOUNT_MISMATCH"),
        (_sell_position(quantity="10", restricted_quantity="5"), "QUANTITY_EXCEEDS_AVAILABLE"),
        (_sell_position(valid_until="2026-10-16T01:45:00Z"), "EVIDENCE_EXPIRED"),
    )
    for evidence, code in invalid_cases:
        candidate = _regular_sell_envelope(evidence=evidence)
        if evidence is None:
            _nested(candidate, "order")["sell_position_evidence"] = None
            _reseal(candidate)
        _assert_code(candidate, code)


def test_sell_position_evidence_must_match_order_account() -> None:
    envelope = _regular_sell_envelope(evidence=_sell_position(account_id=8))

    _assert_code(envelope, "POSITION_ACCOUNT_MISMATCH")


def test_buy_does_not_consume_optional_sell_position_freshness_or_security() -> None:
    envelope = _envelope()
    _nested(envelope, "order")["sell_position_evidence"] = _sell_position(
        security_id="000001.SZ",
        available_at="2026-10-16T01:44:58Z",
        valid_until="2026-10-16T01:44:59Z",
    )
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_position_evidence_rejects_unknown_completeness_and_inconsistent_windows() -> None:
    envelope = _regular_sell_envelope(evidence=_sell_position(completeness="PARTIAL"))
    _assert_code(envelope, "POSITION_EVIDENCE_INVALID")

    envelope = _regular_sell_envelope(evidence=_sell_position(completeness="COMPLETE"))
    position = _nested(envelope, "order")["sell_position_evidence"]
    assert isinstance(position, dict)
    position["available_to_sell_quantity"] = None
    _reseal(envelope)
    _assert_code(envelope, "POSITION_EVIDENCE_INVALID")

    incomplete = _sell_position(completeness="INCOMPLETE")
    incomplete["available_to_sell_quantity"] = None
    incomplete["restricted_quantity"] = None
    _assert_code(_regular_sell_envelope(evidence=incomplete), "POSITION_EVIDENCE_INCOMPLETE")

    invalid_window = _sell_position(valid_until="2026-10-16T01:44:57Z")
    _assert_code(_regular_sell_envelope(evidence=invalid_window), "EVIDENCE_WINDOW_INVALID")

    fractional_restricted = _sell_position(restricted_quantity="0.5")
    _assert_code(
        _regular_sell_envelope(evidence=fractional_restricted),
        "POSITION_EVIDENCE_INVALID",
    )


@pytest.mark.parametrize(
    ("container", "field", "value", "code"),
    [
        ("order", "quantity", "20.5", "QUANTITY_INVALID"),
        ("buy_quantity", "minimum", "10.5", "QUANTITY_CONSTRAINT_INVALID"),
    ],
)
def test_share_quantities_must_be_whole_decimal_values(
    container: str, field: str, value: str, code: str
) -> None:
    envelope = _envelope()
    if container == "order":
        _nested(envelope, "order")[field] = value
    else:
        _nested(envelope, "rule")[container][field] = value  # type: ignore[index]
    _reseal(envelope)

    _assert_code(envelope, code)


def test_position_quantities_must_be_whole_shares() -> None:
    envelope = _regular_sell_envelope(evidence=_sell_position(quantity="30.5"))

    _assert_code(envelope, "POSITION_EVIDENCE_INVALID")


def test_sellable_restricted_balance_may_not_be_mistaken_for_available_shares() -> None:
    envelope = _regular_sell_envelope()
    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))

    _assert_code(
        _regular_sell_envelope(quantity="31"),
        "QUANTITY_EXCEEDS_AVAILABLE",
    )


def test_sellable_balance_to_zero_requires_full_fresh_complete_unrestricted_evidence() -> None:
    envelope = _odd_lot_sell_envelope()
    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))

    cases: tuple[tuple[dict[str, object] | None, str], ...] = (
        (None, "POSITION_EVIDENCE_MISSING"),
        (_sell_position(completeness="INCOMPLETE"), "POSITION_EVIDENCE_INCOMPLETE"),
        (_sell_position(security_id="000001.SZ"), "POSITION_SECURITY_MISMATCH"),
        (_sell_position(restricted_quantity="1"), "POSITION_HAS_RESTRICTED_BALANCE"),
        (_sell_position(quantity="20"), "POSITION_NOT_FULL_BALANCE"),
        (_sell_position(valid_until="2026-10-16T01:45:00Z"), "EVIDENCE_EXPIRED"),
    )
    for evidence, expected_code in cases:
        candidate = _odd_lot_sell_envelope()
        _nested(candidate, "order")["sell_position_evidence"] = evidence
        _reseal(candidate)
        _assert_code(candidate, expected_code)


def test_sellable_balance_exception_covers_on_step_balance_below_minimum() -> None:
    envelope = _odd_lot_sell_envelope()
    rule = _nested(envelope, "rule")
    rule["sell_quantity"] = {"minimum": "200", "step": "1", "maximum": "1000"}
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_forbidden_sell_below_minimum_still_fails_when_quantity_is_on_step() -> None:
    envelope = _regular_sell_envelope(
        quantity="10",
        evidence=_sell_position(quantity="30", restricted_quantity="0"),
    )
    _nested(envelope, "rule")["sell_quantity"] = {
        "minimum": "20",
        "step": "10",
        "maximum": "1000",
    }
    _reseal(envelope)

    _assert_code(envelope, "QUANTITY_BELOW_MINIMUM")


@pytest.mark.parametrize(("available_quantity", "quantity"), (("29", "9"), ("29", "19")))
def test_odd_remainder_once_allows_remainder_that_leaves_a_whole_step(
    available_quantity: str, quantity: str
) -> None:
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity=available_quantity,
        quantity=quantity,
    )

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_odd_remainder_once_uses_exact_large_integer_share_arithmetic() -> None:
    step = "1000000000000000000000000000000"
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity=f"{step}9",
        quantity="9",
    )
    _nested(envelope, "rule")["sell_quantity"] = {
        "minimum": step,
        "step": step,
        "maximum": "2000000000000000000000000000000",
    }
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_odd_remainder_once_allows_regular_step_sell_with_restricted_position() -> None:
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity="30",
        quantity="20",
        restricted_quantity="5",
    )

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_odd_remainder_once_rejects_remainder_that_is_not_a_whole_step() -> None:
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity="29",
        quantity="18",
    )

    _assert_code(envelope, "QUANTITY_NOT_ON_STEP")


def test_odd_remainder_once_requires_zero_restricted_position() -> None:
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity="29",
        quantity="9",
        restricted_quantity="1",
    )

    _assert_code(envelope, "POSITION_HAS_RESTRICTED_BALANCE")


def test_odd_remainder_once_does_not_bypass_maximum() -> None:
    envelope = _odd_remainder_once_sell_envelope(
        available_quantity="29",
        quantity="19",
        maximum="10",
    )

    _assert_code(envelope, "QUANTITY_ABOVE_MAXIMUM")


def test_odd_remainder_once_requires_equal_minimum_and_step() -> None:
    envelope = _odd_remainder_once_sell_envelope()
    _nested(envelope, "rule")["sell_quantity"] = {
        "minimum": "10",
        "step": "5",
        "maximum": "1000",
    }
    _reseal(envelope)

    _assert_code(envelope, "RULE_INVALID")


def test_sell_position_evidence_must_be_available_before_the_evaluation_clock() -> None:
    envelope = _odd_lot_sell_envelope()
    _nested(envelope, "order")["sell_position_evidence"] = _sell_position(
        available_at="2026-10-16T01:46:00Z"
    )
    _reseal(envelope)

    _assert_code(envelope, "EVIDENCE_NOT_AVAILABLE")


def test_zero_lot_policy_does_not_change_maximum_or_allow_wrong_sell_balance() -> None:
    envelope = _odd_lot_sell_envelope()
    rule = _nested(envelope, "rule")
    rule["sell_quantity"] = {"minimum": "20", "step": "20", "maximum": "10"}
    _reseal(envelope)

    _assert_code(envelope, "QUANTITY_CONSTRAINT_INVALID")

    envelope = _odd_lot_sell_envelope()
    rule = _nested(envelope, "rule")
    rule["sell_quantity"] = {"minimum": "10", "step": "20", "maximum": "14"}
    _reseal(envelope)
    _assert_code(envelope, "QUANTITY_ABOVE_MAXIMUM")


def test_non_json_nan_and_non_object_inputs_are_rejected() -> None:
    envelope = _envelope()
    _nested(envelope, "order")["quantity"] = float("nan")
    _assert_code(envelope, "DECIMAL_INVALID")
    _assert_code(["not", "an", "object"], "ENVELOPE_INVALID")


def test_non_string_object_keys_are_rejected_at_json_boundary() -> None:
    envelope = _envelope()
    envelope[1] = "not a JSON key"  # type: ignore[index]

    _assert_code(envelope, "ENVELOPE_INVALID")


def test_source_observation_must_not_follow_availability() -> None:
    envelope = _envelope()
    _nested(envelope, "rule").update(
        {
            "source_observed_at": "2026-10-16T01:00:00Z",
            "source_available_at": "2026-10-16T00:45:00Z",
        }
    )
    _reseal(envelope)

    _assert_code(envelope, "EVIDENCE_WINDOW_INVALID")


def test_invalid_date_shape_and_noncanonical_date_are_rejected() -> None:
    envelope = _envelope()
    _nested(envelope, "market_evidence")["trading_date"] = None
    _reseal(envelope)
    _assert_code(envelope, "DATE_INVALID")

    envelope = _envelope()
    _nested(envelope, "market_evidence")["trading_date"] = "20261016"
    _reseal(envelope)
    _assert_code(envelope, "DATE_INVALID")

    envelope = _envelope()
    _nested(envelope, "market_evidence")["trading_date"] = "not-a-date"
    _reseal(envelope)
    _assert_code(envelope, "DATE_INVALID")


@pytest.mark.parametrize(
    ("container", "field", "value", "code"),
    [
        ("rule", "effective_from", "2026-10-16T02:45:00Z", "RULE_WINDOW_INVALID"),
        ("market_evidence", "session_close_at", "2026-10-16T01:00:00Z", "SESSION_INTERVAL_INVALID"),
        ("market_evidence", "session_state", "HOLIDAY", "SESSION_INVALID"),
        ("market_evidence", "security_state", "UNKNOWN_VALUE", "SECURITY_STATE_INVALID"),
        ("market_evidence", "price_boundary_mode", "FLOATING", "BOUNDARY_INVALID"),
        ("decision", "status", "PENDING", "DECISION_INVALID"),
    ],
)
def test_unsupported_states_and_invalid_windows_are_rejected(
    container: str, field: str, value: str, code: str
) -> None:
    envelope = _envelope()
    _nested(envelope, container)[field] = value
    _reseal(envelope)

    _assert_code(envelope, code)


def test_limited_boundary_requires_both_prices_and_checks_reference_price() -> None:
    envelope = _envelope()
    market = _nested(envelope, "market_evidence")
    market["lower_limit_price"] = None
    _reseal(envelope)
    _assert_code(envelope, "BOUNDARY_INVALID")

    envelope = _envelope()
    market = _nested(envelope, "market_evidence")
    market.update({"lower_limit_price": "10.5", "upper_limit_price": "11"})
    _reseal(envelope)
    _assert_code(envelope, "REFERENCE_PRICE_OUTSIDE_BOUNDARY")


def test_reason_codes_are_an_exact_unique_json_array() -> None:
    envelope = _envelope()
    _nested(envelope, "decision")["reason_codes"] = "DENIED"
    _assert_code(envelope, "DECISION_INVALID")

    envelope = _envelope()
    _nested(envelope, "decision")["reason_codes"] = ["DUPLICATE", "DUPLICATE"]
    _assert_code(envelope, "DECISION_INVALID")


def test_exact_integer_scaling_handles_large_share_and_price_values() -> None:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    market = _nested(envelope, "market_evidence")
    order = _nested(envelope, "order")
    large_quantity = "999999999999999999999999999999"
    precise_price = "1000000000000000000000000000000.0000000000000000000000000000001"
    rule.update(
        {
            "buy_quantity": {"minimum": "1", "step": "1", "maximum": large_quantity},
            "sell_quantity": {"minimum": "1", "step": "1", "maximum": large_quantity},
            "price_tick": "0.0000000000000000000000000000001",
        }
    )
    market.update(
        {
            "lower_limit_price": "999999999999999999999999999999",
            "upper_limit_price": "1000000000000000000000000000001",
            "reference_price": precise_price,
        }
    )
    order.update({"quantity": large_quantity, "limit_price": precise_price})
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_plain_decimal_wire_bound_accepts_values_above_default_context_precision() -> None:
    envelope = _envelope()
    rule = _nested(envelope, "rule")
    expanded_maximum = "1" + "0" * 129
    rule["buy_quantity"] = {"minimum": "10", "step": "10", "maximum": expanded_maximum}
    rule["sell_quantity"] = {"minimum": "10", "step": "10", "maximum": expanded_maximum}
    _reseal(envelope)

    validate_effective_constraints(envelope, submitted_at=datetime(2026, 10, 16, 1, 45, tzinfo=UTC))


def test_local_clock_normalization_overflow_is_rejected() -> None:
    class _PositiveOffset(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta:
            return timedelta(hours=1)

        def dst(self, dt: datetime | None) -> timedelta:
            return timedelta(0)

        def tzname(self, dt: datetime | None) -> str:
            return "TEST+01"

    _assert_code(
        _envelope(),
        "SUBMISSION_TIME_INVALID",
        submitted_at=datetime(1, 1, 1, tzinfo=_PositiveOffset()),
    )
