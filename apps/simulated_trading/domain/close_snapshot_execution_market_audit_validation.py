"""Strict validators and wire constants for close-snapshot execution audits."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import cast
from zoneinfo import ZoneInfo

from apps.data_center.domain.sina_quote_capture import (
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteCapture,
)

from .execution_settlement_plan_binding import (
    SettlementPlanBindingValidationError,
    _canonical_hash,
)

_AUDIT_SCHEMA = "close-snapshot-execution-market-audit.v1"
_EVIDENCE_SCHEMA = "close-snapshot-simulated-market-audit.v1"
_PURPOSE = "close_snapshot_simulation"
_MARKET_AVAILABLE_AT_BASIS = "local_response_completed_at_not_vendor_published_at"
_MARKET_PRICE_KIND = "vendor_last_quote_after_close_not_official_close"
_PAPER_BOUNDARY_BASIS = "policy_derived_paper_bounds_not_exchange_limits"
_SECURITY_STATE_BASIS = "vendor_reported_sina_status_mapping_not_exchange_confirmation"
_PRICE_RULE = "exact_vendor_last_after_close.v1"
_SOURCE_SCHEMA = "sina-quote-capture.v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SHA256_LENGTH = 64


def _validate_market_bundle(
    bundle: dict[str, object],
) -> tuple[SinaQuoteCapture, dict[str, object], dict[str, object], dict[str, object], str]:
    """Validate exact close bundle structure and return its typed payload parts."""

    if frozenset(bundle) != _BUNDLE_KEYS:
        raise SettlementPlanBindingValidationError("close market bundle fields are invalid")
    if (
        bundle.get("schema") != "close-snapshot-simulation-bundle.v1"
        or bundle.get("purpose") != _PURPOSE
    ):
        raise SettlementPlanBindingValidationError("close market bundle schema is invalid")
    if bundle.get("market_available_at_basis") != _MARKET_AVAILABLE_AT_BASIS:
        raise SettlementPlanBindingValidationError("close availability clock basis is invalid")
    capture = _object(bundle.get("capture"), "bundle capture")
    policy = _object(bundle.get("policy"), "bundle policy")
    calendar = _object(bundle.get("calendar"), "bundle calendar")
    market = _object(bundle.get("market"), "bundle market")
    _verify_object_hash(policy, _POLICY_KEYS, "policy")
    _verify_object_hash(calendar, _CALENDAR_KEYS, "calendar")
    _verify_object_hash(market, _CLOSE_MARKET_KEYS, "market")
    _verify_object_hash(bundle, _BUNDLE_KEYS, "market bundle")
    rule_hash = _digest(bundle.get("execution_rule_content_hash"), "execution_rule_content_hash")
    parsed_capture = _validate_capture(capture)
    _validate_policy(policy)
    _validate_calendar(calendar)
    _validate_close_market(market, parsed_capture, policy)
    return parsed_capture, policy, calendar, market, rule_hash


def _validate_capture(capture: dict[str, object]) -> SinaQuoteCapture:
    """Reparse exact retained bytes into the trusted source capture type."""

    if frozenset(capture) != _CAPTURE_KEYS or capture.get("schema") != _SOURCE_SCHEMA:
        raise SettlementPlanBindingValidationError("close raw capture fields are invalid")
    try:
        parsed = SinaQuoteCapture.from_payload(capture)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError("close source capture is invalid") from error
    if not parsed.usable_parse or parsed.quote is None:
        raise SettlementPlanBindingValidationError("close source capture has no usable quote")
    return parsed


def _validate_policy(policy: dict[str, object]) -> None:
    """Require explicit close-only Sina policy and verify its nested hash."""

    if frozenset(policy) != _POLICY_KEYS or policy.get("purpose") != _PURPOSE:
        raise SettlementPlanBindingValidationError("close market policy fields or purpose differ")
    if (
        policy.get("source_id") != "sina_public_quote"
        or policy.get("price_rule") != _PRICE_RULE
        or policy.get("price_boundary_mode") not in {"LIMITED", "UNRESTRICTED"}
    ):
        raise SettlementPlanBindingValidationError("close market policy source or rule is invalid")
    if _digest(policy.get("status_mapping_sha256"), "status_mapping_sha256") != (
        SINA_VENDOR_STATUS_MAPPING_SHA256
    ):
        raise SettlementPlanBindingValidationError("close status mapping hash is unsupported")
    codes = policy.get("trusted_vendor_status_codes")
    if type(codes) is not list or not codes or any(type(code) is not str for code in codes):
        raise SettlementPlanBindingValidationError("close trusted status codes are invalid")
    if len(set(codes)) != len(codes):
        raise SettlementPlanBindingValidationError("close trusted status codes are duplicated")
    if type(policy.get("usage_ttl_seconds")) is not int or not (
        0 < cast(int, policy.get("usage_ttl_seconds")) < 86_400
    ):
        raise SettlementPlanBindingValidationError("close usage TTL is invalid")
    _parse_date(policy.get("trading_date"), "policy trading_date")
    starts = _parse_utc(policy.get("available_from"), "policy available_from")
    ends = _parse_utc(policy.get("available_until"), "policy available_until")
    if starts >= ends:
        raise SettlementPlanBindingValidationError("close policy availability window is invalid")
    _digest(policy.get("price_rule_source_hash"), "price_rule_source_hash")
    _digest(policy.get("boundary_rule_source_hash"), "boundary_rule_source_hash")
    if policy.get("price_boundary_mode") == "LIMITED":
        _positive_price(
            _decimal_value(policy.get("lower_boundary_factor"), "lower factor"), "lower"
        )
        _positive_price(
            _decimal_value(policy.get("upper_boundary_factor"), "upper factor"), "upper"
        )
        if _decimal_value(policy.get("lower_boundary_factor"), "lower factor") >= _decimal_value(
            policy.get("upper_boundary_factor"), "upper factor"
        ):
            raise SettlementPlanBindingValidationError("close paper boundary factors are reversed")


def _validate_calendar(calendar: dict[str, object]) -> None:
    """Require exact typed CLOSED calendar clocks and its content seal."""

    if frozenset(calendar) != _CALENDAR_KEYS:
        raise SettlementPlanBindingValidationError("close calendar fields are invalid")
    if (
        calendar.get("session_state") != "CLOSED"
        or calendar.get("session_timezone") != "Asia/Shanghai"
    ):
        raise SettlementPlanBindingValidationError(
            "close calendar is not actual CLOSED session evidence"
        )
    trading_date = _parse_date(calendar.get("trading_date"), "calendar trading_date")
    opened = _parse_utc(calendar.get("session_open_at"), "calendar open")
    closed = _parse_utc(calendar.get("session_close_at"), "calendar close")
    observed = _parse_utc(calendar.get("calendar_observed_at"), "calendar observation")
    available = _parse_utc(calendar.get("calendar_available_at"), "calendar availability")
    valid_until = _parse_utc(calendar.get("calendar_valid_until"), "calendar validity")
    if (
        opened >= closed
        or opened.astimezone(_SHANGHAI).date() != trading_date
        or closed.astimezone(_SHANGHAI).date() != trading_date
        or not observed <= available < valid_until
    ):
        raise SettlementPlanBindingValidationError("close calendar clocks are invalid")
    _digest(calendar.get("calendar_source_hash"), "calendar_source_hash")
    _digest(calendar.get("content_hash"), "calendar.content_hash")


def _validate_close_market(
    market: dict[str, object], capture: SinaQuoteCapture, policy: dict[str, object]
) -> None:
    """Validate no-stage market type, vendor-last label, and closed V1 evidence."""

    if frozenset(market) != _CLOSE_MARKET_KEYS:
        raise SettlementPlanBindingValidationError("close market fields are invalid")
    if (
        market.get("price_observation_kind") != _MARKET_PRICE_KIND
        or market.get("price_boundary_basis") != _PAPER_BOUNDARY_BASIS
        or market.get("security_state_basis") != _SECURITY_STATE_BASIS
    ):
        raise SettlementPlanBindingValidationError("close market source meaning is invalid")
    evidence = _object(market.get("market_evidence_v1"), "close execution market evidence")
    if frozenset(evidence) != _EXECUTION_MARKET_KEYS:
        raise SettlementPlanBindingValidationError(
            "close execution market evidence fields are invalid"
        )
    if evidence.get("session_state") != "CLOSED" or evidence.get("security_state") != "TRADING":
        raise SettlementPlanBindingValidationError("close market session/security state is invalid")
    quote = capture.quote
    if quote is None:
        raise SettlementPlanBindingValidationError("close market has no parsed source quote")
    latest = _quote_value(market.get("latest"), "market latest")
    previous_payload = _object(market.get("previous_close"), "market previous_close")
    if (
        latest != _decimal_value(evidence.get("reference_price"), "market reference_price")
        or latest != quote.last_price
    ):
        raise SettlementPlanBindingValidationError("close market prices do not match evidence")
    if quote.previous_close is None:
        if policy.get("price_boundary_mode") != "UNRESTRICTED" or previous_payload != {
            "state": "MISSING",
            "value": None,
        }:
            raise SettlementPlanBindingValidationError("close previous price is unavailable")
    elif _quote_value(previous_payload, "market previous_close") != quote.previous_close:
        raise SettlementPlanBindingValidationError("close previous price differs from source")
    _digest(evidence.get("calendar_source_hash"), "market calendar hash")
    _digest(evidence.get("market_source_hash"), "market source hash")
    for key in (
        "calendar_observed_at",
        "calendar_available_at",
        "calendar_valid_until",
        "session_open_at",
        "session_close_at",
        "market_observed_at",
        "market_available_at",
        "market_valid_until",
    ):
        _parse_utc(evidence.get(key), key)


def _validate_close_decision(decision: dict[str, object]) -> dict[str, object]:
    """Require a hashed QUALIFIED close-purpose order decision, never Risk ALLOWED."""

    if frozenset(decision) != _CLOSE_DECISION_KEYS:
        raise SettlementPlanBindingValidationError("close qualification fields are invalid")
    if decision.get("schema") != "close-snapshot-simulation-decision.v1":
        raise SettlementPlanBindingValidationError("close qualification schema is invalid")
    if decision.get("purpose") != _PURPOSE or decision.get("status") != "QUALIFIED":
        raise SettlementPlanBindingValidationError("close qualification is not QUALIFIED")
    if decision.get("reason_codes") != []:
        raise SettlementPlanBindingValidationError("qualified close decision has blocking reasons")
    if decision.get("order_id") is None or decision.get("order_content_hash") is None:
        raise SettlementPlanBindingValidationError("close qualification is not order-bound")
    _digest(decision.get("order_content_hash"), "close order content hash")
    _parse_date(decision.get("trading_date"), "close decision trading_date")
    _positive_price(
        _decimal_value(decision.get("requested_price"), "close requested price"), "requested price"
    )
    _parse_utc(decision.get("evaluated_at"), "close decision evaluation")
    for key in (
        "capture_body_sha256",
        "policy_content_hash",
        "calendar_content_hash",
        "execution_rule_content_hash",
        "market_content_hash",
        "content_hash",
    ):
        _digest(decision.get(key), key)
    return decision


def _validate_locked_position(
    payload: dict[str, object],
    *,
    account_id: int,
    security_id: str,
    execution_price: Decimal,
    close_evaluated_at: datetime,
) -> None:
    """Bind the stop-loss trigger evidence to the locked ledger position."""

    expected = frozenset(
        {
            "account_id",
            "security_id",
            "total_quantity",
            "cost_basis_known",
            "total_cost",
            "derived_average_cost",
            "account_stop_loss_pct",
            "market_price",
            "calculated_pnl_pct",
            "threshold_crossed",
            "available_before_holds",
            "active_held_shares",
            "available_to_sell_quantity",
            "observed_at",
        }
    )
    if frozenset(payload) != expected:
        raise SettlementPlanBindingValidationError("close locked-position fields are invalid")
    if (
        payload.get("account_id") != account_id
        or payload.get("security_id") != security_id
        or payload.get("cost_basis_known") is not True
        or payload.get("threshold_crossed") is not True
        or _decimal_value(payload.get("market_price"), "locked market_price") != execution_price
        or _parse_iso_datetime(payload.get("observed_at"), "locked position observation")
        != close_evaluated_at
    ):
        raise SettlementPlanBindingValidationError("close stop-loss position binding differs")
    _positive_decimal_text(payload.get("total_quantity"), "total_quantity")
    _positive_decimal_text(payload.get("total_cost"), "total_cost")
    _positive_decimal_text(payload.get("derived_average_cost"), "derived_average_cost")
    _positive_decimal_text(payload.get("account_stop_loss_pct"), "stop loss threshold")
    pnl = _decimal_value(payload.get("calculated_pnl_pct"), "calculated_pnl_pct")
    before_holds = _positive_decimal_text(
        payload.get("available_before_holds"), "available_before_holds"
    )
    held = _nonnegative_decimal_text(payload.get("active_held_shares"), "active_held_shares")
    available = _nonnegative_decimal_text(
        payload.get("available_to_sell_quantity"), "available_to_sell_quantity"
    )
    if before_holds - held != available:
        raise SettlementPlanBindingValidationError("close locked-position arithmetic differs")
    if pnl >= 0:
        raise SettlementPlanBindingValidationError("close stop-loss trigger is not a loss")


def _verify_nested_hashes(
    *,
    market_bundle: dict[str, object],
    policy: dict[str, object],
    calendar: dict[str, object],
    market: dict[str, object],
    qualification: dict[str, object],
) -> None:
    """Recompute each nested object hash and source decision digest."""

    for payload, keys, name in (
        (policy, _POLICY_KEYS, "policy"),
        (calendar, _CALENDAR_KEYS, "calendar"),
        (market, _CLOSE_MARKET_KEYS, "market"),
        (market_bundle, _BUNDLE_KEYS, "market bundle"),
        (qualification, _CLOSE_DECISION_KEYS, "close qualification"),
    ):
        _verify_object_hash(payload, keys, name)


def _verify_object_hash(payload: dict[str, object], keys: frozenset[str], name: str) -> None:
    """Recompute one nested object's self-excluding SHA-256 content hash."""

    if frozenset(payload) != keys:
        raise SettlementPlanBindingValidationError(f"{name} hash envelope fields are invalid")
    digest = _digest(payload.get("content_hash"), f"{name}.content_hash")
    content = {key: value for key, value in payload.items() if key != "content_hash"}
    if _canonical_hash(content) != digest:
        raise SettlementPlanBindingValidationError(f"{name} content hash differs")


def _quote_value(value: object, name: str) -> Decimal:
    """Validate one canonical present quote value and return its price."""

    fields = _object(value, name)
    if frozenset(fields) != frozenset({"state", "value"}):
        raise SettlementPlanBindingValidationError(f"{name} fields are invalid")
    if fields.get("state") != "PRESENT":
        raise SettlementPlanBindingValidationError(f"{name} must be explicitly present")
    price = _positive_price(_decimal_value(fields.get("value"), f"{name}.value"), name)
    return price


def _validate_runtime_identity(runtime: dict[str, object]) -> None:
    """Retain and validate the exact ConfigCenter profile/snapshot identity tuple."""

    expected = frozenset(
        {
            "profile_id",
            "profile_version",
            "profile_hash",
            "snapshot_id",
            "snapshot_hash",
            "activated_at",
            "snapshot_generated_at",
        }
    )
    if frozenset(runtime) != expected:
        raise SettlementPlanBindingValidationError("close runtime identity fields are invalid")
    _token(runtime.get("profile_id"), "runtime profile_id")
    _token(runtime.get("snapshot_id"), "runtime snapshot_id")
    if (
        type(runtime.get("profile_version")) is not int
        or cast(int, runtime.get("profile_version")) <= 0
    ):
        raise SettlementPlanBindingValidationError("close runtime profile version is invalid")
    _digest(runtime.get("profile_hash"), "runtime profile_hash")
    _digest(runtime.get("snapshot_hash"), "runtime snapshot_hash")
    _parse_iso_datetime(runtime.get("activated_at"), "runtime activated_at")
    _parse_iso_datetime(runtime.get("snapshot_generated_at"), "runtime snapshot_generated_at")


def _positive_database_id(value: object, name: str) -> int:
    """Require one positive signed-64-bit database identity."""

    if type(value) is not int or not 0 < value <= 9_223_372_036_854_775_807:
        raise SettlementPlanBindingValidationError(f"close audit {name} is invalid")
    return value


def _token(value: object, name: str) -> str:
    """Require one bounded nonempty canonical token without whitespace."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise SettlementPlanBindingValidationError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    """Require one bare lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SettlementPlanBindingValidationError(f"{name} must be SHA-256")
    return value


def _utc_datetime(value: object, name: str) -> datetime:
    """Require one aware datetime and normalize without inferring a clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SettlementPlanBindingValidationError(f"{name} must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(f"{name} is invalid") from error


def _utc_text(value: datetime) -> str:
    """Render one normalized UTC instant in the settlement audit format."""

    return _utc_datetime(value, "audit datetime").isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, name: str) -> datetime:
    """Accept the source contracts' automatic or fixed-microsecond UTC Z format."""

    if type(value) is not str or not value.endswith("Z"):
        raise SettlementPlanBindingValidationError(f"{name} must use canonical UTC text")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SettlementPlanBindingValidationError(f"{name} is invalid") from error
    canonical_source_text = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value not in {_utc_text(parsed), canonical_source_text}:
        raise SettlementPlanBindingValidationError(f"{name} is not canonical")
    return parsed


def _parse_iso_datetime(value: object, name: str) -> datetime:
    """Parse one aware identity timestamp while retaining accepted source format."""

    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{name} must be timestamp text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SettlementPlanBindingValidationError(f"{name} is invalid") from error
    return _utc_datetime(parsed, name)


def _parse_date(value: object, name: str) -> date:
    """Parse canonical ISO date text without accepting datetimes."""

    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{name} must be date text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise SettlementPlanBindingValidationError(f"{name} is invalid") from error
    if parsed.isoformat() != value:
        raise SettlementPlanBindingValidationError(f"{name} is not canonical")
    return parsed


def _decimal_value(value: object, name: str) -> Decimal:
    """Parse a finite canonical decimal string from the retained evidence."""

    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{name} must be decimal text")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise SettlementPlanBindingValidationError(f"{name} is invalid") from error
    if not parsed.is_finite() or format(parsed, "f") != value:
        raise SettlementPlanBindingValidationError(f"{name} is not canonical finite decimal")
    return parsed


def _positive_price(value: Decimal, name: str) -> Decimal:
    """Require a positive exact finite Decimal value."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise SettlementPlanBindingValidationError(f"{name} must be positive finite Decimal")
    return value


def _positive_decimal_text(value: object, name: str) -> Decimal:
    """Parse one positive canonical decimal string."""

    return _positive_price(_decimal_value(value, name), name)


def _nonnegative_decimal_text(value: object, name: str) -> Decimal:
    """Parse one nonnegative canonical decimal string."""

    parsed = _decimal_value(value, name)
    if parsed < 0:
        raise SettlementPlanBindingValidationError(f"{name} must be nonnegative")
    return parsed


def _string(value: object, name: str) -> str:
    """Narrow one JSON string field."""

    if type(value) is not str:
        raise SettlementPlanBindingValidationError(f"{name} must be text")
    return value


def _object(value: object, name: str) -> dict[str, object]:
    """Narrow one plain nested JSON object."""

    if type(value) is not dict:
        raise SettlementPlanBindingValidationError(f"{name} must be an object")
    return cast(dict[str, object], value)


def _exact_object(payload: object, keys: frozenset[str], name: str) -> dict[str, object]:
    """Require one exact outer wire shape."""

    fields = _object(payload, name)
    if frozenset(fields) != keys:
        raise SettlementPlanBindingValidationError(f"{name} fields are invalid")
    return fields


def _parse_json_object(value: str, name: str) -> dict[str, object]:
    """Decode one JSON object and reject malformed or non-object data."""

    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as error:
        raise SettlementPlanBindingValidationError(f"{name} is malformed") from error
    return _object(parsed, name)


def _canonical_json_text(value: object) -> str:
    """Return one canonical JSON string for mutable nested evidence."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise SettlementPlanBindingValidationError(
            "close evidence is not canonical JSON"
        ) from error


def _json_hash(value: object) -> str:
    """Hash JSON evidence with the established canonical UTF-8 representation."""

    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


_AUDIT_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "account_id",
        "user_id",
        "idempotency_key",
        "request_payload_hash",
        "security_id",
        "asset_code",
        "side",
        "execution_price",
        "source_id",
        "source_version",
        "source_hash",
        "source_observed_at",
        "source_available_at",
        "source_valid_until",
        "policy_id",
        "policy_version",
        "policy_hash",
        "market_hash",
        "market_bundle_hash",
        "rule_hash",
        "calendar_hash",
        "close_qualification_hash",
        "close_evaluated_at",
        "evidence",
        "evidence_hash",
        "content_hash",
    }
)
_AUDIT_TEXT_FIELDS = frozenset(
    _AUDIT_KEYS - {"schema", "purpose", "account_id", "user_id", "evidence", "side"}
)
_POLICY_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "policy_id",
        "policy_version",
        "account_id",
        "security_id",
        "asset_code",
        "market",
        "board",
        "trading_date",
        "source_id",
        "source_name",
        "usage_ttl_seconds",
        "status_mapping_sha256",
        "trusted_vendor_status_codes",
        "available_from",
        "available_until",
        "price_rule",
        "price_rule_source_hash",
        "price_boundary_mode",
        "lower_boundary_factor",
        "upper_boundary_factor",
        "boundary_rule_source_id",
        "boundary_rule_version",
        "boundary_rule_source_hash",
        "unrestricted_reason_code",
        "content_hash",
    }
)
_CALENDAR_KEYS = frozenset(
    {
        "calendar_id",
        "calendar_version",
        "calendar_source_hash",
        "calendar_observed_at",
        "calendar_available_at",
        "calendar_valid_until",
        "trading_date",
        "session_id",
        "session_timezone",
        "session_open_at",
        "session_close_at",
        "session_state",
        "content_hash",
    }
)
_CAPTURE_KEYS = frozenset(
    {
        "schema",
        "asset_code",
        "requested_url",
        "final_url",
        "request_started_at",
        "response_completed_at",
        "http_status",
        "http_date",
        "content_type",
        "charset",
        "content_encoding",
        "body_base64",
        "body_size_bytes",
        "body_sha256",
        "parse_issue",
    }
)
_CLOSE_MARKET_KEYS = frozenset(
    {
        "market_evidence_v1",
        "latest",
        "previous_close",
        "price_observation_kind",
        "price_boundary_basis",
        "security_state_basis",
        "content_hash",
    }
)
_EXECUTION_MARKET_KEYS = frozenset(
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
_BUNDLE_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "capture",
        "policy",
        "calendar",
        "execution_rule_content_hash",
        "market",
        "market_available_at_basis",
        "content_hash",
    }
)
_CLOSE_DECISION_KEYS = frozenset(
    {
        "schema",
        "purpose",
        "status",
        "reason_codes",
        "account_id",
        "security_id",
        "asset_code",
        "trading_date",
        "requested_price",
        "evaluated_at",
        "capture_body_sha256",
        "policy_content_hash",
        "calendar_content_hash",
        "execution_rule_content_hash",
        "market_content_hash",
        "order_id",
        "order_content_hash",
        "content_hash",
    }
)
