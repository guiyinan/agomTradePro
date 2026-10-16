"""Strict JSON codec for v3 execution rules with explicit settlement input."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import NoReturn, cast

from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
    SettlementPolicyV1,
)
from apps.risk_center.infrastructure.ashare_execution_rule_v2_codec import (
    AShareExecutionRuleV2CodecError,
    decode_a_share_execution_submission_rule,
    encode_a_share_execution_submission_rule,
)

ASHARE_EXECUTION_RULES_V3_SCHEMA: str = "a-share-execution-rules.v3"
_MAX_CANONICAL_INTEGER_CHARS: int = 257
_MAX_TIMESTAMP_CHARS: int = 64
_POLICY_FIELDS = frozenset(
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
_BUNDLE_FIELDS = frozenset(
    {
        "bundle_id",
        "bundle_version",
        "execution_submission_v2",
        "settlement_policy_v1",
        "content_hash",
    }
)
_MANIFEST_FIELDS = frozenset({"schema", "rules"})


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

    data = _mapping(payload, _BUNDLE_FIELDS, "v3 rule")
    try:
        v2_rule = decode_a_share_execution_submission_rule(data["execution_submission_v2"])
        policy = _decode_policy(data["settlement_policy_v1"])
        bundle = ExecutionSettlementBundleV3(
            bundle_id=_string(data["bundle_id"], "bundle_id"),
            bundle_version=_string(data["bundle_version"], "bundle_version"),
            execution_submission_v2=v2_rule,
            settlement_policy_v1=policy,
            content_hash=_string(data["content_hash"], "content_hash"),
        )
    except (AShareExecutionRuleV2CodecError, AShareExecutionRuleV3CodecError) as error:
        raise AShareExecutionRuleV3CodecError(f"v3 rule is invalid: {error}") from error
    except (ArithmeticError, TypeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError(f"v3 rule is invalid: {error}") from error
    _require_canonical(payload, encode_a_share_execution_settlement_bundle(bundle))
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
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_nonfinite,
            parse_int=_bounded_json_integer,
        )
    except AShareExecutionRuleV3CodecError as error:
        raise AShareExecutionRuleV3CodecError(f"manifest JSON is invalid: {error}") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError("manifest JSON is invalid") from error
    manifest = _mapping(raw, _MANIFEST_FIELDS, "manifest")
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
    _require_canonical(raw, expected)
    return rules


def _decode_policy(value: object) -> SettlementPolicyV1:
    data = _mapping(value, _POLICY_FIELDS, "settlement_policy_v1")
    try:
        return SettlementPolicyV1(
            policy_id=_string(data["policy_id"], "policy_id"),
            policy_version=_string(data["policy_version"], "policy_version"),
            security_id=_string(data["security_id"], "security_id"),
            market=_string(data["market"], "market"),
            board=_string(data["board"], "board"),
            settlement_basis=SettlementBasis(_string(data["settlement_basis"], "settlement_basis")),
            settlement_lag_sessions=_integer(
                data["settlement_lag_sessions"], "settlement_lag_sessions"
            ),
            bound_execution_rule_v2_hash=_string(
                data["bound_execution_rule_v2_hash"], "bound_execution_rule_v2_hash"
            ),
            source_id=_string(data["source_id"], "source_id"),
            source_version=_string(data["source_version"], "source_version"),
            source_hash=_string(data["source_hash"], "source_hash"),
            source_observed_at=_datetime(data["source_observed_at"], "source_observed_at"),
            source_available_at=_datetime(data["source_available_at"], "source_available_at"),
            effective_from=_datetime(data["effective_from"], "effective_from"),
            valid_until=_datetime(data["valid_until"], "valid_until"),
            content_hash=_string(data["content_hash"], "content_hash"),
        )
    except (TypeError, ValueError) as error:
        raise AShareExecutionRuleV3CodecError("settlement_policy_v1 is invalid") from error


def _mapping(value: object, expected: frozenset[str], field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise AShareExecutionRuleV3CodecError(f"{field_name} must be an object")
    data = cast(dict[str, object], value)
    if frozenset(data) != expected:
        raise AShareExecutionRuleV3CodecError(f"{field_name} has missing or unknown fields")
    return data


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise AShareExecutionRuleV3CodecError(f"{field_name} must be a string")
    return value


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int or len(str(value)) > _MAX_CANONICAL_INTEGER_CHARS:
        raise AShareExecutionRuleV3CodecError(f"{field_name} must be a bounded integer")
    return value


def _bounded_json_integer(value: str) -> int:
    if len(value.lstrip("-")) > _MAX_CANONICAL_INTEGER_CHARS:
        raise AShareExecutionRuleV3CodecError("integer exceeds the canonical text bound")
    return int(value)


def _datetime(value: object, field_name: str) -> datetime:
    text = _string(value, field_name)
    if len(text) > _MAX_TIMESTAMP_CHARS or not text.endswith("Z"):
        raise AShareExecutionRuleV3CodecError(
            f"{field_name} must use bounded canonical UTC Z notation"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AShareExecutionRuleV3CodecError(f"{field_name} is not an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AShareExecutionRuleV3CodecError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _pairs_to_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AShareExecutionRuleV3CodecError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    raise AShareExecutionRuleV3CodecError(f"non-finite JSON number is forbidden: {value}")


def _require_canonical(actual: object, expected: object) -> None:
    if actual != expected:
        raise AShareExecutionRuleV3CodecError("payload differs from canonical v3 encoding")


__all__: tuple[str, ...] = (
    "ASHARE_EXECUTION_RULES_V3_SCHEMA",
    "AShareExecutionRuleV3CodecError",
    "decode_a_share_execution_settlement_bundle",
    "encode_a_share_execution_settlement_bundle",
    "parse_a_share_execution_rule_v3_manifest",
)
