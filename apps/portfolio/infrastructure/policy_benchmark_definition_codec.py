"""Strict canonical codec for Portfolio policy-benchmark definitions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)


class PolicyBenchmarkDefinitionCodecError(ValueError):
    """A stored benchmark definition is malformed or non-canonical."""


def encode_policy_benchmark_definition(
    value: PortfolioPolicyBenchmarkDefinition,
) -> dict[str, object]:
    """Encode one complete definition without its derived inactive flags."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_policy_benchmark_definition(
    payload: object,
) -> PortfolioPolicyBenchmarkDefinition:
    """Restore and revalidate one exact canonical benchmark definition."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "definition_id",
            "definition_version",
            "base_currency",
            "constituents",
            "methodology_refs",
            "valuation_timezone",
            "valuation_cutoff",
            "evaluation_window_days",
            "max_price_age_seconds",
            "max_fx_age_seconds",
            "missing_price_policy",
            "missing_fx_policy",
            "recorded_at",
            "valid_until",
            "permission",
            "blocker_codes",
            "identity_hash",
            "content_hash",
        },
    )
    constituents = tuple(_constituent(item) for item in _list(data["constituents"]))
    refs = tuple(_methodology_ref(item) for item in _list(data["methodology_refs"]))
    if len(refs) != 5:
        raise PolicyBenchmarkDefinitionCodecError(
            "benchmark methodology reference count is invalid"
        )
    try:
        value = PortfolioPolicyBenchmarkDefinition(
            definition_id=_string(data["definition_id"]),
            definition_version=_string(data["definition_version"]),
            base_currency=_string(data["base_currency"]),
            constituents=constituents,
            corporate_action_ref=refs[0],
            cost_tax_ref=refs[1],
            fx_fixing_ref=refs[2],
            price_fixing_ref=refs[3],
            trading_calendar_ref=refs[4],
            valuation_timezone=_string(data["valuation_timezone"]),
            valuation_cutoff=_string(data["valuation_cutoff"]),
            evaluation_window_days=_positive_integer(data["evaluation_window_days"]),
            max_price_age_seconds=_positive_integer(data["max_price_age_seconds"]),
            max_fx_age_seconds=_positive_integer(data["max_fx_age_seconds"]),
            missing_price_policy=_string(data["missing_price_policy"]),
            missing_fx_policy=_string(data["missing_fx_policy"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            blocker_codes=tuple(_string(item) for item in _list(data["blocker_codes"])),
        )
    except (PolicyBenchmarkDefinitionCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkDefinitionCodecError(
            "policy-benchmark definition is invalid"
        ) from error
    if payload != encode_policy_benchmark_definition(value):
        raise PolicyBenchmarkDefinitionCodecError("policy-benchmark definition is non-canonical")
    return value


def _constituent(payload: object) -> PolicyBenchmarkConstituentDefinition:
    data = _mapping(
        payload,
        {"benchmark_code", "price_identifier", "currency", "weight", "ordinal"},
    )
    return PolicyBenchmarkConstituentDefinition(
        benchmark_code=_string(data["benchmark_code"]),
        price_identifier=_string(data["price_identifier"]),
        currency=_string(data["currency"]),
        weight=_decimal(data["weight"]),
        ordinal=_non_negative_integer(data["ordinal"]),
    )


def _methodology_ref(payload: object) -> PolicyBenchmarkMethodologyRef:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "artifact_id",
            "artifact_version",
            "content_hash",
            "recorded_at",
            "valid_until",
        },
    )
    return PolicyBenchmarkMethodologyRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise PolicyBenchmarkDefinitionCodecError("benchmark payload shape is invalid")
    return cast(dict[str, object], payload)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(_string(value))
    except InvalidOperation as error:
        raise ValueError("expected canonical Decimal text") from error


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _non_negative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "PolicyBenchmarkDefinitionCodecError",
    "decode_policy_benchmark_definition",
    "encode_policy_benchmark_definition",
]
