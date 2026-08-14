"""Strict codec for Portfolio benchmark trading-calendar definitions."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import cast

from apps.portfolio.domain.policy_benchmark_trading_calendar import (
    PolicyBenchmarkCalendarDay,
    PortfolioPolicyBenchmarkTradingCalendar,
)


class PolicyBenchmarkTradingCalendarCodecError(ValueError):
    """Canonical calendar payload cannot be restored exactly."""


def encode_policy_benchmark_trading_calendar(
    value: PortfolioPolicyBenchmarkTradingCalendar,
) -> dict[str, object]:
    """Encode one definition without derived safety display fields."""

    payload = value.to_payload()
    return {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_policy_benchmark_trading_calendar(
    payload: object,
) -> PortfolioPolicyBenchmarkTradingCalendar:
    """Restore and revalidate one exact canonical calendar definition."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "methodology_id",
            "methodology_version",
            "market_calendar_code",
            "timezone",
            "coverage_start",
            "coverage_end",
            "days",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PortfolioPolicyBenchmarkTradingCalendar(
            methodology_id=_string(data["methodology_id"]),
            methodology_version=_string(data["methodology_version"]),
            market_calendar_code=_string(data["market_calendar_code"]),
            timezone=_string(data["timezone"]),
            coverage_start=_date(data["coverage_start"]),
            coverage_end=_date(data["coverage_end"]),
            days=tuple(_day(item) for item in _list(data["days"])),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
        )
    except (PolicyBenchmarkTradingCalendarCodecError, TypeError, ValueError) as error:
        raise PolicyBenchmarkTradingCalendarCodecError(
            "benchmark trading-calendar definition is invalid"
        ) from error
    if payload != encode_policy_benchmark_trading_calendar(value):
        raise PolicyBenchmarkTradingCalendarCodecError(
            "benchmark trading-calendar definition is non-canonical"
        )
    return value


def _day(payload: object) -> PolicyBenchmarkCalendarDay:
    data = _mapping(
        payload,
        {
            "calendar_date",
            "ordinal",
            "is_valuation_day",
            "session_open_local",
            "session_close_local",
            "valuation_cutoff_local",
        },
    )
    return PolicyBenchmarkCalendarDay(
        calendar_date=_date(data["calendar_date"]),
        ordinal=_non_negative_integer(data["ordinal"]),
        is_valuation_day=_boolean(data["is_valuation_day"]),
        session_open_local=_optional_time(data["session_open_local"]),
        session_close_local=_optional_time(data["session_close_local"]),
        valuation_cutoff_local=_optional_time(data["valuation_cutoff_local"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise PolicyBenchmarkTradingCalendarCodecError("calendar payload shape is invalid")
    return cast(dict[str, object], payload)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError("expected list")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _date(value: object) -> date:
    text = _string(value)
    result = date.fromisoformat(text)
    if result.isoformat() != text:
        raise ValueError("date is non-canonical")
    return result


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.isoformat().replace("+00:00", "Z") != text:
        raise ValueError("datetime is non-canonical")
    return result


def _optional_time(value: object) -> time | None:
    if value is None:
        return None
    text = _string(value)
    fold = 1 if text.endswith("[fold=1]") else 0
    raw = text[:-8] if fold else text
    result = time.fromisoformat(raw)
    if result.tzinfo is not None:
        raise ValueError("local time must be timezone-free")
    return result.replace(fold=fold)


def _non_negative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
    return value


__all__ = [
    "PolicyBenchmarkTradingCalendarCodecError",
    "decode_policy_benchmark_trading_calendar",
    "encode_policy_benchmark_trading_calendar",
]
