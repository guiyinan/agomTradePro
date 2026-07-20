"""Trading calendar helpers for personal readiness window validation."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import CommandError


@dataclass(frozen=True)
class _TradingCalendar:
    source: str
    dates: tuple[date, ...] | None = None

    @property
    def date_set(self) -> set[date]:
        return set(self.dates or ())


def _resolve_trading_calendar(
    *,
    source: str,
    trading_calendar: set[date] | list[date] | tuple[date, ...] | None,
    latest_required_date: date | None,
    load_qlib_trading_calendar: Callable[[], list[date]] | None = None,
) -> _TradingCalendar:
    if trading_calendar is not None:
        return _TradingCalendar(
            source="injected",
            dates=tuple(sorted(set(trading_calendar))),
        )

    if source == "weekday":
        return _TradingCalendar(source="weekday", dates=None)

    if source not in {"auto", "qlib"}:
        raise CommandError("calendar-source must be auto, qlib, or weekday")

    loader = load_qlib_trading_calendar or _load_qlib_trading_calendar
    qlib_calendar = loader()
    if qlib_calendar and (
        latest_required_date is None or latest_required_date <= qlib_calendar[-1]
    ):
        return _TradingCalendar(source="qlib", dates=tuple(qlib_calendar))

    if source == "qlib":
        raise CommandError("Qlib trading calendar is unavailable or stale for readiness evidence")

    return _TradingCalendar(source="weekday_fallback", dates=None)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("expected-latest-date must be YYYY-MM-DD") from exc


def _load_qlib_trading_calendar() -> list[date]:
    try:
        from core.integration.runtime_settings import get_runtime_qlib_config

        runtime_config = get_runtime_qlib_config()
        provider_uri = runtime_config.get("provider_uri")
    except Exception:
        provider_uri = None

    if not provider_uri:
        provider_uri = getattr(settings, "QLIB_SETTINGS", {}).get("provider_uri")
    if not provider_uri:
        return []

    calendar_path = Path(str(provider_uri)).expanduser() / "calendars" / "day.txt"
    if not calendar_path.exists():
        return []

    values: list[date] = []
    try:
        with calendar_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                normalized = line.strip()
                if not normalized:
                    continue
                values.append(date.fromisoformat(normalized[:10]))
    except (OSError, ValueError):
        return []
    return sorted(set(values))


def _is_trading_day(value: date, calendar: _TradingCalendar) -> bool:
    if calendar.dates is not None:
        return value in calendar.date_set
    return _is_weekday(value)


def _previous_trading_day(value: date, calendar: _TradingCalendar) -> date:
    if calendar.dates is not None:
        index = bisect_left(calendar.dates, value)
        if index <= 0:
            return date.min
        return calendar.dates[index - 1]
    return _previous_weekday(value)


def _next_trading_day(value: date, calendar: _TradingCalendar) -> date:
    if calendar.dates is not None:
        index = bisect_left(calendar.dates, value)
        while index < len(calendar.dates) and calendar.dates[index] <= value:
            index += 1
        if index < len(calendar.dates):
            return calendar.dates[index]
    return _next_weekday(value)


def _is_weekday(value: date) -> bool:
    return value.weekday() < 5


def _previous_weekday(value: date) -> date:
    current = date.fromordinal(value.toordinal() - 1)
    while not _is_weekday(current):
        current = date.fromordinal(current.toordinal() - 1)
    return current


def _next_weekday(value: date) -> date:
    current = date.fromordinal(value.toordinal() + 1)
    while not _is_weekday(current):
        current = date.fromordinal(current.toordinal() + 1)
    return current
