"""Strict JSON codec for canonical A-share execution rule configuration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import NoReturn, cast

from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)

ASHARE_EXECUTION_RULES_SCHEMA: str = "a-share-execution-rules.v1"
_MAX_CANONICAL_DECIMAL_CHARS = 257


class AShareExecutionRuleCodecError(ValueError):
    """Rule manifest or canonical payload is malformed or noncanonical."""


_RULE_FIELDS = frozenset(
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


def encode_a_share_execution_rule(rule: AShareExecutionRule) -> dict[str, object]:
    """Return the domain rule's complete canonical payload."""

    if type(rule) is not AShareExecutionRule:
        raise AShareExecutionRuleCodecError("expected an exact AShareExecutionRule")
    try:
        AShareExecutionRule.__post_init__(rule)
    except (TypeError, ValueError) as error:
        raise AShareExecutionRuleCodecError("A-share execution rule is invalid") from error
    return rule.to_payload()


def decode_a_share_execution_rule(payload: object) -> AShareExecutionRule:
    """Decode one exact canonical rule payload and revalidate its content hash."""

    data = _mapping(payload, _RULE_FIELDS, "rule")
    try:
        rule = AShareExecutionRule(
            rule_id=_string(data["rule_id"], "rule_id"),
            rule_version=_string(data["rule_version"], "rule_version"),
            security_id=_string(data["security_id"], "security_id"),
            market=_string(data["market"], "market"),
            board=_string(data["board"], "board"),
            buy_quantity=_decode_quantity(data["buy_quantity"], "buy_quantity"),
            sell_quantity=_decode_quantity(data["sell_quantity"], "sell_quantity"),
            sell_odd_lot_mode=SellOddLotMode(
                _string(data["sell_odd_lot_mode"], "sell_odd_lot_mode")
            ),
            price_tick=_decimal(data["price_tick"], "price_tick"),
            rule_source_id=_string(data["rule_source_id"], "rule_source_id"),
            rule_source_version=_string(data["rule_source_version"], "rule_source_version"),
            rule_source_hash=_string(data["rule_source_hash"], "rule_source_hash"),
            source_observed_at=_datetime(data["source_observed_at"], "source_observed_at"),
            source_available_at=_datetime(data["source_available_at"], "source_available_at"),
            effective_from=_datetime(data["effective_from"], "effective_from"),
            valid_until=_datetime(data["valid_until"], "valid_until"),
            content_hash=_string(data["content_hash"], "content_hash"),
        )
    except (AShareExecutionRuleCodecError, TypeError, ValueError) as error:
        raise AShareExecutionRuleCodecError(
            f"A-share execution rule is invalid: {error}"
        ) from error
    _require_canonical(payload, encode_a_share_execution_rule(rule))
    return rule


def parse_a_share_execution_rule_manifest(text: str) -> tuple[AShareExecutionRule, ...]:
    """Parse a strict operator manifest, rejecting duplicate keys and non-finite JSON."""

    if type(text) is not str:
        raise AShareExecutionRuleCodecError("manifest must be text")
    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_nonfinite,
        )
    except AShareExecutionRuleCodecError as error:
        raise AShareExecutionRuleCodecError(f"manifest JSON is invalid: {error}") from error
    except json.JSONDecodeError as error:
        raise AShareExecutionRuleCodecError("manifest JSON is invalid") from error
    manifest = _mapping(raw, frozenset({"schema", "rules"}), "manifest")
    if manifest["schema"] != ASHARE_EXECUTION_RULES_SCHEMA:
        raise AShareExecutionRuleCodecError("manifest schema is unsupported")
    rules_value = manifest["rules"]
    if type(rules_value) is not list:
        raise AShareExecutionRuleCodecError("manifest rules must be an array")
    rules = tuple(decode_a_share_execution_rule(item) for item in cast(list[object], rules_value))
    _require_canonical(
        raw, {"schema": manifest["schema"], "rules": [rule.to_payload() for rule in rules]}
    )
    return rules


def _decode_quantity(value: object, field_name: str) -> ExecutionQuantityConstraint:
    data = _mapping(value, frozenset({"minimum", "step", "maximum"}), field_name)
    try:
        return ExecutionQuantityConstraint(
            minimum=_decimal(data["minimum"], f"{field_name}.minimum"),
            step=_decimal(data["step"], f"{field_name}.step"),
            maximum=_decimal(data["maximum"], f"{field_name}.maximum"),
        )
    except (TypeError, ValueError) as error:
        raise AShareExecutionRuleCodecError(f"{field_name} is invalid") from error


def _mapping(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise AShareExecutionRuleCodecError(f"{field_name} must be an object")
    data = cast(dict[str, object], value)
    if frozenset(data) != expected:
        raise AShareExecutionRuleCodecError(f"{field_name} has missing or unknown fields")
    return data


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise AShareExecutionRuleCodecError(f"{field_name} must be a string")
    return value


def _decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not str:
        raise AShareExecutionRuleCodecError(f"{field_name} must be canonical decimal text")
    if len(value) > _MAX_CANONICAL_DECIMAL_CHARS:
        raise AShareExecutionRuleCodecError(f"{field_name} exceeds the canonical text bound")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise AShareExecutionRuleCodecError(f"{field_name} is not a decimal") from error
    if not parsed.is_finite():
        raise AShareExecutionRuleCodecError(f"{field_name} must be finite")
    return parsed


def _datetime(value: object, field_name: str) -> datetime:
    text = _string(value, field_name)
    if not text.endswith("Z"):
        raise AShareExecutionRuleCodecError(f"{field_name} must use canonical UTC Z notation")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AShareExecutionRuleCodecError(f"{field_name} is not an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AShareExecutionRuleCodecError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AShareExecutionRuleCodecError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    raise AShareExecutionRuleCodecError(f"non-finite JSON number is forbidden: {value}")


def _require_canonical(actual: object, expected: object) -> None:
    if actual != expected:
        raise AShareExecutionRuleCodecError("payload differs from canonical domain encoding")
