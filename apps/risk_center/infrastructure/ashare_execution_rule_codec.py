"""Strict JSON codec for canonical A-share execution rule configuration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import NoReturn, cast

from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionRuleV2
from apps.risk_center.domain.execution_trading_constraints import (
    AShareExecutionRule,
    ExecutionQuantityConstraint,
    SellOddLotMode,
)
from apps.risk_center.domain.price_submission_range import (
    PriceRoundingMode,
    PriceSubmissionRangeRule,
    PriceSubmissionRangeValidationError,
    PriceSubmissionStage,
)

ASHARE_EXECUTION_RULES_SCHEMA: str = "a-share-execution-rules.v1"
_MAX_CANONICAL_DECIMAL_CHARS = 257
_MAX_CANONICAL_INTEGER_CHARS = 257
_MAX_TIMESTAMP_CHARS = 64

ASHARE_EXECUTION_RULES_V2_SCHEMA: str = "a-share-execution-rules.v2"
ASHARE_EXECUTION_RULES_V3_SCHEMA: str = "a-share-execution-rules.v3"
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
_RULE_FIELDS_V2 = frozenset(
    {"execution_rule_v1", "price_submission_range", "allowed_stages", "content_hash"}
)
_POLICY_FIELDS_V3 = frozenset(
    {
        "policy_id",
        "policy_version",
        "security_id",
        "market",
        "board",
        "settlement_basis",
        "settlement_lag_sessions",
        "bound_execution_rule_v2_hash",
        "source_id",
        "source_version",
        "source_hash",
        "source_observed_at",
        "source_available_at",
        "effective_from",
        "valid_until",
        "content_hash",
    }
)
_BUNDLE_FIELDS_V3 = frozenset(
    {
        "bundle_id",
        "bundle_version",
        "execution_submission_v2",
        "settlement_policy_v1",
        "content_hash",
    }
)
_MANIFEST_FIELDS_V3 = frozenset({"schema", "rules"})


class AShareExecutionRuleCodecError(ValueError):
    """Rule manifest or canonical payload is malformed or noncanonical."""


_RULE_FIELDS_V1 = frozenset(
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

    data = _mapping_v1(payload, _RULE_FIELDS_V1, "rule")
    try:
        rule = AShareExecutionRule(
            rule_id=_string_v1(data["rule_id"], "rule_id"),
            rule_version=_string_v1(data["rule_version"], "rule_version"),
            security_id=_string_v1(data["security_id"], "security_id"),
            market=_string_v1(data["market"], "market"),
            board=_string_v1(data["board"], "board"),
            buy_quantity=_decode_quantity(data["buy_quantity"], "buy_quantity"),
            sell_quantity=_decode_quantity(data["sell_quantity"], "sell_quantity"),
            sell_odd_lot_mode=SellOddLotMode(
                _string_v1(data["sell_odd_lot_mode"], "sell_odd_lot_mode")
            ),
            price_tick=_decimal_v1(data["price_tick"], "price_tick"),
            rule_source_id=_string_v1(data["rule_source_id"], "rule_source_id"),
            rule_source_version=_string_v1(data["rule_source_version"], "rule_source_version"),
            rule_source_hash=_string_v1(data["rule_source_hash"], "rule_source_hash"),
            source_observed_at=_datetime_v1(data["source_observed_at"], "source_observed_at"),
            source_available_at=_datetime_v1(data["source_available_at"], "source_available_at"),
            effective_from=_datetime_v1(data["effective_from"], "effective_from"),
            valid_until=_datetime_v1(data["valid_until"], "valid_until"),
            content_hash=_string_v1(data["content_hash"], "content_hash"),
        )
    except (AShareExecutionRuleCodecError, TypeError, ValueError) as error:
        raise AShareExecutionRuleCodecError(
            f"A-share execution rule is invalid: {error}"
        ) from error
    _require_canonical_v1(payload, encode_a_share_execution_rule(rule))
    return rule


def parse_a_share_execution_rule_manifest(text: str) -> tuple[AShareExecutionRule, ...]:
    """Parse a strict operator manifest, rejecting duplicate keys and non-finite JSON."""

    if type(text) is not str:
        raise AShareExecutionRuleCodecError("manifest must be text")
    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object_v1,
            parse_constant=_reject_nonfinite_v1,
        )
    except AShareExecutionRuleCodecError as error:
        raise AShareExecutionRuleCodecError(f"manifest JSON is invalid: {error}") from error
    except json.JSONDecodeError as error:
        raise AShareExecutionRuleCodecError("manifest JSON is invalid") from error
    manifest = _mapping_v1(raw, frozenset({"schema", "rules"}), "manifest")
    if manifest["schema"] != ASHARE_EXECUTION_RULES_SCHEMA:
        raise AShareExecutionRuleCodecError("manifest schema is unsupported")
    rules_value = manifest["rules"]
    if type(rules_value) is not list:
        raise AShareExecutionRuleCodecError("manifest rules must be an array")
    rules = tuple(decode_a_share_execution_rule(item) for item in cast(list[object], rules_value))
    _require_canonical_v1(
        raw, {"schema": manifest["schema"], "rules": [rule.to_payload() for rule in rules]}
    )
    return rules


def _decode_quantity(value: object, field_name: str) -> ExecutionQuantityConstraint:
    data = _mapping_v1(value, frozenset({"minimum", "step", "maximum"}), field_name)
    try:
        return ExecutionQuantityConstraint(
            minimum=_decimal_v1(data["minimum"], f"{field_name}.minimum"),
            step=_decimal_v1(data["step"], f"{field_name}.step"),
            maximum=_decimal_v1(data["maximum"], f"{field_name}.maximum"),
        )
    except (TypeError, ValueError) as error:
        raise AShareExecutionRuleCodecError(f"{field_name} is invalid") from error


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

    data = _mapping_v2(payload, _RULE_FIELDS_V2, "v2 rule")
    try:
        base = decode_a_share_execution_rule(data["execution_rule_v1"])
        price_rule = _decode_price_rule(data["price_submission_range"])
        stages = _decode_stages(data["allowed_stages"])
        rule = ExecutionSubmissionRuleV2(
            execution_rule_v1=base,
            price_submission_range=price_rule,
            allowed_stages=stages,
            content_hash=_string_v2(data["content_hash"], "content_hash"),
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
            object_pairs_hook=_pairs_to_object_v2,
            parse_constant=_reject_nonfinite_v2,
            parse_int=_bounded_json_integer_v2,
        )
    except AShareExecutionRuleV2CodecError as error:
        raise AShareExecutionRuleV2CodecError(f"manifest JSON is invalid: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise AShareExecutionRuleV2CodecError("manifest JSON is invalid") from error
    manifest = _mapping_v2(raw, frozenset({"schema", "rules"}), "manifest")
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
    data = _mapping_v2(value, _PRICE_RULE_FIELDS, "price_submission_range")
    try:
        return PriceSubmissionRangeRule(
            market=_string_v2(data["market"], "price_submission_range.market"),
            board=_string_v2(data["board"], "price_submission_range.board"),
            price_tick=_decimal_v2(data["price_tick"], "price_submission_range.price_tick"),
            buy_deviation_ratio=_decimal_v2(
                data["buy_deviation_ratio"], "price_submission_range.buy_deviation_ratio"
            ),
            sell_deviation_ratio=_decimal_v2(
                data["sell_deviation_ratio"], "price_submission_range.sell_deviation_ratio"
            ),
            buy_widening_ticks=_integer_v2(
                data["buy_widening_ticks"], "price_submission_range.buy_widening_ticks"
            ),
            sell_widening_ticks=_integer_v2(
                data["sell_widening_ticks"], "price_submission_range.sell_widening_ticks"
            ),
            minimum_distance_ticks=_integer_v2(
                data["minimum_distance_ticks"],
                "price_submission_range.minimum_distance_ticks",
            ),
            lower_floor_ticks=_integer_v2(
                data["lower_floor_ticks"], "price_submission_range.lower_floor_ticks"
            ),
            rounding_mode=PriceRoundingMode(
                _string_v2(data["rounding_mode"], "price_submission_range.rounding_mode")
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
            result.append(PriceSubmissionStage(_string_v2(item, "allowed_stages item")))
        except ValueError as error:
            raise AShareExecutionRuleV2CodecError(
                "allowed_stages contains an unknown value"
            ) from error
    return tuple(result)


class AShareExecutionRuleV3CodecError(ValueError):
    """A v3 manifest or canonical settlement bundle is malformed."""


def encode_a_share_execution_settlement_bundle(
    bundle: ExecutionSettlementBundleV3,
) -> dict[str, object]:
    """Return one complete v3 payload after revalidating its nested contracts."""

    if type(bundle) is not ExecutionSettlementBundleV3:
        raise AShareExecutionRuleV3CodecError("expected an exact ExecutionSettlementBundleV3")
    try:
        ExecutionSettlementBundleV3.__post_init__(bundle)
        return {
            "bundle_id": bundle.bundle_id,
            "bundle_version": bundle.bundle_version,
            "execution_submission_v2": encode_a_share_execution_submission_rule(
                bundle.execution_submission_v2
            ),
            "settlement_policy_v1": bundle.settlement_policy_v1.to_payload(),
            "content_hash": bundle.content_hash,
        }
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError("v3 settlement bundle is invalid") from error


def decode_a_share_execution_settlement_bundle(
    payload: object,
) -> ExecutionSettlementBundleV3:
    """Decode one exact v3 bundle and revalidate v1, v2, policy, and outer hashes."""

    data = _mapping_v3(payload, _BUNDLE_FIELDS_V3, "v3 rule")
    try:
        v2_rule = decode_a_share_execution_submission_rule(data["execution_submission_v2"])
        policy = _decode_policy(data["settlement_policy_v1"])
        bundle = ExecutionSettlementBundleV3(
            bundle_id=_string_v3(data["bundle_id"], "bundle_id"),
            bundle_version=_string_v3(data["bundle_version"], "bundle_version"),
            execution_submission_v2=v2_rule,
            settlement_policy_v1=policy,
            content_hash=_string_v3(data["content_hash"], "content_hash"),
        )
    except (AShareExecutionRuleV2CodecError, AShareExecutionRuleV3CodecError) as error:
        raise AShareExecutionRuleV3CodecError(f"v3 rule is invalid: {error}") from error
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError(f"v3 rule is invalid: {error}") from error
    _require_canonical_v3(payload, encode_a_share_execution_settlement_bundle(bundle))
    return bundle


def parse_a_share_execution_rule_v3_manifest(
    text: str,
) -> tuple[ExecutionSettlementBundleV3, ...]:
    """Parse one strict v3 manifest, rejecting duplicate keys and non-finite JSON."""

    if type(text) is not str:
        raise AShareExecutionRuleV3CodecError("manifest must be text")
    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_pairs_to_object_v3,
            parse_constant=_reject_nonfinite_v3,
            parse_int=_bounded_json_integer_v3,
        )
    except AShareExecutionRuleV3CodecError as error:
        raise AShareExecutionRuleV3CodecError(f"manifest JSON is invalid: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError("manifest JSON is invalid") from error
    manifest = _mapping_v3(raw, _MANIFEST_FIELDS_V3, "manifest")
    if manifest["schema"] != ASHARE_EXECUTION_RULES_V3_SCHEMA:
        raise AShareExecutionRuleV3CodecError("manifest schema is unsupported")
    rules_value = manifest["rules"]
    if type(rules_value) is not list:
        raise AShareExecutionRuleV3CodecError("manifest rules must be an array")
    rules = tuple(
        decode_a_share_execution_settlement_bundle(item) for item in cast(list[object], rules_value)
    )
    expected: dict[str, object] = {
        "schema": ASHARE_EXECUTION_RULES_V3_SCHEMA,
        "rules": [encode_a_share_execution_settlement_bundle(rule) for rule in rules],
    }
    _require_canonical_v3(raw, expected)
    return rules


def _decode_policy(value: object) -> SettlementPolicyV1:
    data = _mapping_v3(value, _POLICY_FIELDS_V3, "settlement_policy_v1")
    try:
        return SettlementPolicyV1(
            policy_id=_string_v3(data["policy_id"], "policy_id"),
            policy_version=_string_v3(data["policy_version"], "policy_version"),
            security_id=_string_v3(data["security_id"], "security_id"),
            market=_string_v3(data["market"], "market"),
            board=_string_v3(data["board"], "board"),
            settlement_basis=SettlementBasis(
                _string_v3(data["settlement_basis"], "settlement_basis")
            ),
            settlement_lag_sessions=_integer_v3(
                data["settlement_lag_sessions"], "settlement_lag_sessions"
            ),
            bound_execution_rule_v2_hash=_string_v3(
                data["bound_execution_rule_v2_hash"], "bound_execution_rule_v2_hash"
            ),
            source_id=_string_v3(data["source_id"], "source_id"),
            source_version=_string_v3(data["source_version"], "source_version"),
            source_hash=_string_v3(data["source_hash"], "source_hash"),
            source_observed_at=_datetime_v3(data["source_observed_at"], "source_observed_at"),
            source_available_at=_datetime_v3(data["source_available_at"], "source_available_at"),
            effective_from=_datetime_v3(data["effective_from"], "effective_from"),
            valid_until=_datetime_v3(data["valid_until"], "valid_until"),
            content_hash=_string_v3(data["content_hash"], "content_hash"),
        )
    except (TypeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError("settlement_policy_v1 is invalid") from error


def _mapping(
    value: object,
    expected: frozenset[str],
    field_name: str,
    *,
    error_type: type[ValueError],
) -> dict[str, object]:
    """Require an object with an exact key set and string keys."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise error_type(f"{field_name} must be an object")
    data = cast(dict[str, object], value)
    if frozenset(data) != expected:
        raise error_type(f"{field_name} has missing or unknown fields")
    return data


def _string(value: object, field_name: str, *, error_type: type[ValueError]) -> str:
    """Require an exact string value without coercion."""

    if type(value) is not str:
        raise error_type(f"{field_name} must be a string")
    return value


def _decimal(value: object, field_name: str, *, error_type: type[ValueError]) -> Decimal:
    """Parse the shared bounded canonical decimal text shape."""

    if type(value) is not str:
        raise error_type(f"{field_name} must be canonical decimal text")
    if len(value) > _MAX_CANONICAL_DECIMAL_CHARS:
        raise error_type(f"{field_name} exceeds the canonical text bound")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise error_type(f"{field_name} is not a decimal") from error
    if not parsed.is_finite():
        raise error_type(f"{field_name} must be finite")
    return parsed


def _integer(value: object, field_name: str, *, error_type: type[ValueError]) -> int:
    """Parse the shared bounded exact-integer shape used by V2 and V3."""

    if type(value) is not int or len(str(value)) > _MAX_CANONICAL_INTEGER_CHARS:
        raise error_type(f"{field_name} must be a bounded integer")
    return value


def _bounded_json_integer(value: str, *, error_type: type[ValueError]) -> int:
    """Reject oversized integer tokens before the JSON parser builds an int."""

    if len(value.lstrip("-")) > _MAX_CANONICAL_INTEGER_CHARS:
        raise error_type("integer exceeds the canonical text bound")
    return int(value)


def _datetime(
    value: object,
    field_name: str,
    *,
    error_type: type[ValueError],
    max_chars: int | None,
) -> datetime:
    """Parse canonical UTC Z timestamps, retaining the V3 length bound."""

    text = _string(value, field_name, error_type=error_type)
    if (max_chars is not None and len(text) > max_chars) or not text.endswith("Z"):
        qualifier = "bounded canonical" if max_chars is not None else "canonical"
        raise error_type(f"{field_name} must use {qualifier} UTC Z notation")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise error_type(f"{field_name} is not an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error_type(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _pairs_to_object(
    pairs: list[tuple[str, object]], *, error_type: type[ValueError]
) -> dict[str, object]:
    """Reject duplicate JSON object keys while preserving version error types."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise error_type(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str, *, error_type: type[ValueError]) -> NoReturn:
    """Reject NaN and Infinity JSON constants with the matching codec error."""

    raise error_type(f"non-finite JSON number is forbidden: {value}")


def _require_canonical(
    actual: object, expected: object, *, error_type: type[ValueError], message: str
) -> None:
    """Require exact parsed JSON equality with the version's encoder output."""

    if actual != expected:
        raise error_type(message)


def _mapping_v1(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    return _mapping(value, expected, field_name, error_type=AShareExecutionRuleCodecError)


def _string_v1(value: object, field_name: str) -> str:
    return _string(value, field_name, error_type=AShareExecutionRuleCodecError)


def _decimal_v1(value: object, field_name: str) -> Decimal:
    return _decimal(value, field_name, error_type=AShareExecutionRuleCodecError)


def _datetime_v1(value: object, field_name: str) -> datetime:
    return _datetime(value, field_name, error_type=AShareExecutionRuleCodecError, max_chars=None)


def _pairs_to_object_v1(pairs: list[tuple[str, object]]) -> dict[str, object]:
    return _pairs_to_object(pairs, error_type=AShareExecutionRuleCodecError)


def _reject_nonfinite_v1(value: str) -> NoReturn:
    _reject_nonfinite(value, error_type=AShareExecutionRuleCodecError)


def _require_canonical_v1(actual: object, expected: object) -> None:
    _require_canonical(
        actual,
        expected,
        error_type=AShareExecutionRuleCodecError,
        message="payload differs from canonical domain encoding",
    )


def _mapping_v2(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    return _mapping(value, expected, field_name, error_type=AShareExecutionRuleV2CodecError)


def _string_v2(value: object, field_name: str) -> str:
    return _string(value, field_name, error_type=AShareExecutionRuleV2CodecError)


def _decimal_v2(value: object, field_name: str) -> Decimal:
    return _decimal(value, field_name, error_type=AShareExecutionRuleV2CodecError)


def _integer_v2(value: object, field_name: str) -> int:
    return _integer(value, field_name, error_type=AShareExecutionRuleV2CodecError)


def _bounded_json_integer_v2(value: str) -> int:
    return _bounded_json_integer(value, error_type=AShareExecutionRuleV2CodecError)


def _pairs_to_object_v2(pairs: list[tuple[str, object]]) -> dict[str, object]:
    return _pairs_to_object(pairs, error_type=AShareExecutionRuleV2CodecError)


def _reject_nonfinite_v2(value: str) -> NoReturn:
    _reject_nonfinite(value, error_type=AShareExecutionRuleV2CodecError)


def _require_canonical_v2(actual: object, expected: object) -> None:
    _require_canonical(
        actual,
        expected,
        error_type=AShareExecutionRuleV2CodecError,
        message="payload differs from canonical v2 encoding",
    )


def _mapping_v3(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    return _mapping(value, expected, field_name, error_type=AShareExecutionRuleV3CodecError)


def _string_v3(value: object, field_name: str) -> str:
    return _string(value, field_name, error_type=AShareExecutionRuleV3CodecError)


def _integer_v3(value: object, field_name: str) -> int:
    return _integer(value, field_name, error_type=AShareExecutionRuleV3CodecError)


def _bounded_json_integer_v3(value: str) -> int:
    return _bounded_json_integer(value, error_type=AShareExecutionRuleV3CodecError)


def _datetime_v3(value: object, field_name: str) -> datetime:
    return _datetime(
        value,
        field_name,
        error_type=AShareExecutionRuleV3CodecError,
        max_chars=_MAX_TIMESTAMP_CHARS,
    )


def _pairs_to_object_v3(pairs: list[tuple[str, object]]) -> dict[str, object]:
    return _pairs_to_object(pairs, error_type=AShareExecutionRuleV3CodecError)


def _reject_nonfinite_v3(value: str) -> NoReturn:
    _reject_nonfinite(value, error_type=AShareExecutionRuleV3CodecError)


def _require_canonical_v3(actual: object, expected: object) -> None:
    _require_canonical(
        actual,
        expected,
        error_type=AShareExecutionRuleV3CodecError,
        message="payload differs from canonical v3 encoding",
    )
