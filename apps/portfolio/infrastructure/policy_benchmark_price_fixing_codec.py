"""Strict codec for Portfolio benchmark price-fixing definitions."""

from __future__ import annotations

from datetime import datetime, time
from typing import cast

from apps.portfolio.domain.policy_benchmark_price_fixing import (
    PolicyBenchmarkPriceSourceRef,
    PortfolioPolicyBenchmarkPriceFixing,
)


class PolicyBenchmarkPriceFixingCodecError(ValueError):
    """Canonical price-fixing payload cannot be restored exactly."""


def encode_policy_benchmark_price_fixing(
    value: PortfolioPolicyBenchmarkPriceFixing,
) -> dict[str, object]:
    """Encode one definition without derived display fields."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key
        not in {
            "activation_available",
            "automatic_fallback_allowed",
            "must_not_execute",
        }
    }


def decode_policy_benchmark_price_fixing(payload: object) -> PortfolioPolicyBenchmarkPriceFixing:
    """Restore and revalidate one exact canonical definition."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "methodology_id",
            "methodology_version",
            "price_identifier_namespace",
            "price_field",
            "adjustment_basis",
            "venue",
            "timezone",
            "valuation_cutoff_local",
            "source_priority",
            "stale_after_seconds",
            "missing_price_policy",
            "source_failure_policy",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PortfolioPolicyBenchmarkPriceFixing(
            methodology_id=_string(data["methodology_id"]),
            methodology_version=_string(data["methodology_version"]),
            price_identifier_namespace=_string(data["price_identifier_namespace"]),
            price_field=_string(data["price_field"]),
            adjustment_basis=_string(data["adjustment_basis"]),
            venue=_string(data["venue"]),
            timezone=_string(data["timezone"]),
            valuation_cutoff_local=_local_time(data["valuation_cutoff_local"]),
            source_priority=tuple(_source(item) for item in _list(data["source_priority"])),
            stale_after_seconds=_positive_integer(data["stale_after_seconds"]),
            missing_price_policy=_string(data["missing_price_policy"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            source_failure_policy=_string(data["source_failure_policy"]),
        )
    except (PolicyBenchmarkPriceFixingCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkPriceFixingCodecError("price-fixing definition is invalid") from error
    if payload != encode_policy_benchmark_price_fixing(value):
        raise PolicyBenchmarkPriceFixingCodecError("price-fixing definition is non-canonical")
    return value


def _source(payload: object) -> PolicyBenchmarkPriceSourceRef:
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
    return PolicyBenchmarkPriceSourceRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        ordinal=_non_negative_integer(data["ordinal"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise PolicyBenchmarkPriceFixingCodecError("price-fixing payload shape is invalid")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
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
    if text.endswith("[fold=1]"):
        raw, fold = text[:-8], 1
    else:
        raw, fold = text, 0
    result = time.fromisoformat(raw)
    if result.tzinfo is not None:
        raise ValueError("local time must be timezone-free")
    return result.replace(fold=fold)


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _non_negative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


__all__ = [
    "PolicyBenchmarkPriceFixingCodecError",
    "decode_policy_benchmark_price_fixing",
    "encode_policy_benchmark_price_fixing",
]
