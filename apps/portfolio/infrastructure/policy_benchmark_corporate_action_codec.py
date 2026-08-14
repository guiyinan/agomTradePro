"""Strict codec for Portfolio benchmark corporate-action methodologies."""

from __future__ import annotations

from datetime import datetime, time
from typing import cast

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PolicyBenchmarkCorporateActionRule,
    PolicyBenchmarkCorporateActionSourceRef,
    PortfolioPolicyBenchmarkCorporateAction,
)


class PolicyBenchmarkCorporateActionCodecError(ValueError):
    """Canonical corporate-action methodology cannot be restored exactly."""


def encode_policy_benchmark_corporate_action(
    value: PortfolioPolicyBenchmarkCorporateAction,
) -> dict[str, object]:
    """Encode one methodology without derived authority markers."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key
        not in {
            "activation_available",
            "automatic_fallback_allowed",
            "mutable_fact_projection_allowed",
            "must_not_execute",
        }
    }


def decode_policy_benchmark_corporate_action(
    payload: object,
) -> PortfolioPolicyBenchmarkCorporateAction:
    """Restore and revalidate one exact canonical methodology."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "methodology_id",
            "methodology_version",
            "security_identifier_namespace",
            "timezone",
            "business_date_cutoff_local",
            "business_date_policy",
            "non_business_date_policy",
            "source_priority",
            "event_rules",
            "source_failure_policy",
            "missing_action_policy",
            "unknown_event_type_policy",
            "price_input_adjustment_basis",
            "adjustment_application_policy",
            "duplicate_event_policy",
            "pre_adjusted_input_policy",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PortfolioPolicyBenchmarkCorporateAction(
            methodology_id=_string(data["methodology_id"]),
            methodology_version=_string(data["methodology_version"]),
            security_identifier_namespace=_string(data["security_identifier_namespace"]),
            timezone=_string(data["timezone"]),
            business_date_cutoff_local=_local_time(data["business_date_cutoff_local"]),
            source_priority=tuple(_source(item) for item in _list(data["source_priority"])),
            event_rules=tuple(_rule(item) for item in _list(data["event_rules"])),
            missing_action_policy=_string(data["missing_action_policy"]),
            unknown_event_type_policy=_string(data["unknown_event_type_policy"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            business_date_policy=_string(data["business_date_policy"]),
            non_business_date_policy=_string(data["non_business_date_policy"]),
            source_failure_policy=_string(data["source_failure_policy"]),
            price_input_adjustment_basis=_string(data["price_input_adjustment_basis"]),
            adjustment_application_policy=_string(data["adjustment_application_policy"]),
            duplicate_event_policy=_string(data["duplicate_event_policy"]),
            pre_adjusted_input_policy=_string(data["pre_adjusted_input_policy"]),
        )
    except (PolicyBenchmarkCorporateActionCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkCorporateActionCodecError(
            "corporate-action methodology is invalid"
        ) from error
    if payload != encode_policy_benchmark_corporate_action(value):
        raise PolicyBenchmarkCorporateActionCodecError(
            "corporate-action methodology is non-canonical"
        )
    return value


def _source(payload: object) -> PolicyBenchmarkCorporateActionSourceRef:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "content_hash",
            "ordinal",
            "recorded_at",
            "valid_until",
        },
    )
    return PolicyBenchmarkCorporateActionSourceRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        ordinal=_non_negative(data["ordinal"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _rule(payload: object) -> PolicyBenchmarkCorporateActionRule:
    data = _mapping(
        payload,
        {
            "ordinal",
            "event_type",
            "required_date_fields",
            "effective_date_semantics",
            "ex_date_semantics",
            "pay_date_semantics",
            "valuation_treatment",
            "performance_treatment",
        },
    )
    return PolicyBenchmarkCorporateActionRule(
        ordinal=_non_negative(data["ordinal"]),
        event_type=_string(data["event_type"]),
        required_date_fields=tuple(_string(item) for item in _list(data["required_date_fields"])),
        effective_date_semantics=_string(data["effective_date_semantics"]),
        ex_date_semantics=_string(data["ex_date_semantics"]),
        pay_date_semantics=_string(data["pay_date_semantics"]),
        valuation_treatment=_string(data["valuation_treatment"]),
        performance_treatment=_string(data["performance_treatment"]),
    )


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise PolicyBenchmarkCorporateActionCodecError("corporate-action payload shape is invalid")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _non_negative(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.isoformat().replace("+00:00", "Z") != text:
        raise ValueError("datetime is non-canonical")
    return result


def _local_time(value: object) -> time:
    text = _string(value)
    fold = 1 if text.endswith("[fold=1]") else 0
    raw = text[:-8] if fold else text
    result = time.fromisoformat(raw)
    if result.tzinfo is not None:
        raise ValueError("local time must be timezone-free")
    return result.replace(fold=fold)


__all__ = [
    "PolicyBenchmarkCorporateActionCodecError",
    "decode_policy_benchmark_corporate_action",
    "encode_policy_benchmark_corporate_action",
]
