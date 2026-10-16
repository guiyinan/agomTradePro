"""Strict JSON codec for canonical version-two A-share execution rules."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import NoReturn, cast

from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionRuleV2,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeValidationError,
    PriceSubmissionStage,
)
from apps.risk_center.infrastructure.ashare_execution_rule_codec import (
    AShareExecutionRuleCodecError,
    decode_a_share_execution_rule,
)

ASHARE_EXECUTION_RULES_V2_SCHEMA: str = "a-share-execution-rules.v2"
_MAX_CANONICAL_DECIMAL_CHARS: int = 257
_MAX_CANONICAL_INTEGER_CHARS: int = 257
_PRICE_RULE_FIELDS = frozenset(
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
_RULE_FIELDS = frozenset(
    {"execution_rule_v1", "price_submission_range", "allowed_stages", "content_hash"}
)


class AShareExecutionRuleV2CodecError(ValueError):
    """A v2 manifest or canonical payload is malformed or noncanonical."""


def encode_a_share_execution_submission_rule(
    rule: ExecutionSubmissionRuleV2,
) -> dict[str, object]:
    """Return one exact v2 payload after revalidating the sealed domain object."""

    if type(rule) is not ExecutionSubmissionRuleV2:
        raise AShareExecutionRuleV2CodecError("expected an exact ExecutionSubmissionRuleV2")
    try:
        ExecutionSubmissionRuleV2.__post_init__(rule)
        payload = rule.to_payload()
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV2CodecError("v2 execution rule is invalid") from error
    return payload


def decode_a_share_execution_submission_rule(payload: object) -> ExecutionSubmissionRuleV2:
    """Decode an exact v2 wrapper, validating nested v1 and the outer hash."""

    data = _mapping(payload, _RULE_FIELDS, "v2 rule")
    try:
        base = decode_a_share_execution_rule(data["execution_rule_v1"])
        price_rule = _decode_price_rule(data["price_submission_range"])
        stages = _decode_stages(data["allowed_stages"])
        rule = ExecutionSubmissionRuleV2(
            execution_rule_v1=base,
            price_submission_range=price_rule,
            allowed_stages=stages,
            content_hash=_string(data["content_hash"], "content_hash"),
        )
    except (AShareExecutionRuleCodecError, AShareExecutionRuleV2CodecError) as error:
        raise AShareExecutionRuleV2CodecError(f"v2 rule is invalid: {error}") from error
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV2CodecError(f"v2 rule is invalid: {error}") from error
    _require_canonical_v2(payload, encode_a_share_execution_submission_rule(rule))
    return rule


def parse_a_share_execution_rule_v2_manifest(
    text: str,
) -> tuple[ExecutionSubmissionRuleV2, ...]:
    """Parse one strict v2 manifest, rejecting duplicate keys and non-finite JSON."""

    if type(text) is not str:
        raise AShareExecutionRuleV2CodecError("manifest must be text")
    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_nonfinite,
            parse_int=_bounded_json_integer,
        )
    except AShareExecutionRuleV2CodecError as error:
        raise AShareExecutionRuleV2CodecError(f"manifest JSON is invalid: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise AShareExecutionRuleV2CodecError("manifest JSON is invalid") from error
    manifest = _mapping(raw, frozenset({"schema", "rules"}), "manifest")
    if manifest["schema"] != ASHARE_EXECUTION_RULES_V2_SCHEMA:
        raise AShareExecutionRuleV2CodecError("manifest schema is unsupported")
    rules_value = manifest["rules"]
    if type(rules_value) is not list:
        raise AShareExecutionRuleV2CodecError("manifest rules must be an array")
    rules = tuple(
        decode_a_share_execution_submission_rule(item) for item in cast(list[object], rules_value)
    )
    expected = {
        "schema": ASHARE_EXECUTION_RULES_V2_SCHEMA,
        "rules": [encode_a_share_execution_submission_rule(rule) for rule in rules],
    }
    _require_canonical_v2(raw, expected)
    return rules


def _decode_price_rule(value: object) -> PriceSubmissionRangeRule:
    data = _mapping(value, _PRICE_RULE_FIELDS, "price_submission_range")
    try:
        return PriceSubmissionRangeRule(
            market=_string(data["market"], "price_submission_range.market"),
            board=_string(data["board"], "price_submission_range.board"),
            price_tick=_decimal(data["price_tick"], "price_submission_range.price_tick"),
            buy_deviation_ratio=_decimal(
                data["buy_deviation_ratio"], "price_submission_range.buy_deviation_ratio"
            ),
            sell_deviation_ratio=_decimal(
                data["sell_deviation_ratio"], "price_submission_range.sell_deviation_ratio"
            ),
            buy_widening_ticks=_integer(
                data["buy_widening_ticks"], "price_submission_range.buy_widening_ticks"
            ),
            sell_widening_ticks=_integer(
                data["sell_widening_ticks"], "price_submission_range.sell_widening_ticks"
            ),
            minimum_distance_ticks=_integer(
                data["minimum_distance_ticks"],
                "price_submission_range.minimum_distance_ticks",
            ),
            lower_floor_ticks=_integer(
                data["lower_floor_ticks"], "price_submission_range.lower_floor_ticks"
            ),
            rounding_mode=PriceRoundingMode(
                _string(data["rounding_mode"], "price_submission_range.rounding_mode")
            ),
        )
    except (PriceSubmissionRangeValidationError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV2CodecError("price_submission_range is invalid") from error


def _decode_stages(value: object) -> tuple[PriceSubmissionStage, ...]:
    if type(value) is not list:
        raise AShareExecutionRuleV2CodecError("allowed_stages must be an array")
    result: list[PriceSubmissionStage] = []
    for item in cast(list[object], value):
        try:
            result.append(PriceSubmissionStage(_string(item, "allowed_stages item")))
        except ValueError as error:
            raise AShareExecutionRuleV2CodecError(
                "allowed_stages contains an unknown value"
            ) from error
    return tuple(result)


def _mapping(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise AShareExecutionRuleV2CodecError(f"{field_name} must be an object")
    data = cast(dict[str, object], value)
    if frozenset(data) != expected:
        raise AShareExecutionRuleV2CodecError(f"{field_name} has missing or unknown fields")
    return data


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise AShareExecutionRuleV2CodecError(f"{field_name} must be a string")
    return value


def _require_canonical_v2(actual: object, expected: object) -> None:
    if actual != expected:
        raise AShareExecutionRuleV2CodecError("payload differs from canonical v2 encoding")


def _decimal(value: object, field_name: str) -> Decimal:
    if type(value) is not str:
        raise AShareExecutionRuleV2CodecError(f"{field_name} must be canonical decimal text")
    if len(value) > _MAX_CANONICAL_DECIMAL_CHARS:
        raise AShareExecutionRuleV2CodecError(f"{field_name} exceeds the canonical text bound")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise AShareExecutionRuleV2CodecError(f"{field_name} is not a decimal") from error
    if not parsed.is_finite():
        raise AShareExecutionRuleV2CodecError(f"{field_name} must be finite")
    return parsed


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int or len(str(value)) > _MAX_CANONICAL_INTEGER_CHARS:
        raise AShareExecutionRuleV2CodecError(f"{field_name} must be a bounded integer")
    return value


def _bounded_json_integer(value: str) -> int:
    if len(value.lstrip("-")) > _MAX_CANONICAL_INTEGER_CHARS:
        raise AShareExecutionRuleV2CodecError("integer exceeds the canonical text bound")
    return int(value)


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AShareExecutionRuleV2CodecError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    raise AShareExecutionRuleV2CodecError(f"non-finite JSON number is forbidden: {value}")


__all__: tuple[str, ...] = (
    "ASHARE_EXECUTION_RULES_V2_SCHEMA",
    "AShareExecutionRuleV2CodecError",
    "decode_a_share_execution_submission_rule",
    "encode_a_share_execution_submission_rule",
    "parse_a_share_execution_rule_v2_manifest",
)
