"""Strict codec for Portfolio benchmark FX-fixing definitions."""

from __future__ import annotations

from datetime import datetime, time
from typing import cast

from apps.portfolio.domain.policy_benchmark_fx_fixing import (
    PolicyBenchmarkFxSourceRef,
    PortfolioPolicyBenchmarkFxFixing,
)


class PolicyBenchmarkFxFixingCodecError(ValueError):
    """Canonical FX-fixing payload cannot be restored exactly."""


def encode_policy_benchmark_fx_fixing(value: PortfolioPolicyBenchmarkFxFixing) -> dict[str, object]:
    """Encode one definition without derived display fields."""
    return {
        key: item
        for key, item in value.to_payload().items()
        if key not in {"activation_available", "automatic_fallback_allowed", "must_not_execute"}
    }


def decode_policy_benchmark_fx_fixing(payload: object) -> PortfolioPolicyBenchmarkFxFixing:
    """Restore and revalidate one exact canonical definition."""
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "methodology_id",
            "methodology_version",
            "base_currency",
            "quote_currency",
            "currency_pair",
            "fixing_convention",
            "inverse_rate_allowed",
            "timezone",
            "valuation_cutoff_local",
            "source_priority",
            "stale_after_seconds",
            "triangulation_policy",
            "triangulation_currency",
            "source_failure_policy",
            "missing_fx_policy",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PortfolioPolicyBenchmarkFxFixing(
            methodology_id=_string(data["methodology_id"]),
            methodology_version=_string(data["methodology_version"]),
            base_currency=_string(data["base_currency"]),
            quote_currency=_string(data["quote_currency"]),
            fixing_convention=_string(data["fixing_convention"]),
            inverse_rate_allowed=_boolean(data["inverse_rate_allowed"]),
            timezone=_string(data["timezone"]),
            valuation_cutoff_local=_local_time(data["valuation_cutoff_local"]),
            source_priority=tuple(_source(item) for item in _list(data["source_priority"])),
            stale_after_seconds=_positive(data["stale_after_seconds"]),
            triangulation_policy=_string(data["triangulation_policy"]),
            triangulation_currency=_optional_string(data["triangulation_currency"]),
            source_failure_policy=_string(data["source_failure_policy"]),
            missing_fx_policy=_string(data["missing_fx_policy"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
        )
    except (PolicyBenchmarkFxFixingCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkFxFixingCodecError("FX-fixing definition is invalid") from error
    if data["currency_pair"] != value.currency_pair or payload != encode_policy_benchmark_fx_fixing(
        value
    ):
        raise PolicyBenchmarkFxFixingCodecError("FX-fixing definition is non-canonical")
    return value


def _source(payload: object) -> PolicyBenchmarkFxSourceRef:
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
    return PolicyBenchmarkFxSourceRef(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        artifact_id=_string(data["artifact_id"]),
        artifact_version=_string(data["artifact_version"]),
        content_hash=_string(data["content_hash"]),
        ordinal=_non_negative(data["ordinal"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
    )


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise PolicyBenchmarkFxFixingCodecError("FX-fixing payload shape is invalid")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
    return value


def _positive(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
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
    "PolicyBenchmarkFxFixingCodecError",
    "decode_policy_benchmark_fx_fixing",
    "encode_policy_benchmark_fx_fixing",
]
