"""Pure institutional-calendar rules with explicit evidence and knowledge time."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.exchange_calendar import ExchangeCalendarDay

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InstitutionalCalendarError(ValueError):
    """Reject invalid institutional-calendar evidence with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        """Retain the machine-readable reason alongside the human message."""

        self.code = code
        super().__init__(message)


class SixPeriod(StrEnum):
    """The six preregistered natural-day windows in each calendar month."""

    DAYS_01_05 = "01-05"
    DAYS_06_10 = "06-10"
    DAYS_11_15 = "11-15"
    DAYS_16_20 = "16-20"
    DAYS_21_25 = "21-25"
    DAYS_26_END = "26-month_end"


class EvidenceGrade(StrEnum):
    """Describe source evidence independently of the event lifecycle."""

    CONFIRMED = "confirmed"
    DERIVED = "derived"
    TENTATIVE = "tentative"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"


class EventLifecycle(StrEnum):
    """Describe event occurrence without overwriting its evidence grade."""

    SCHEDULED = "scheduled"
    OCCURRED = "occurred"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class KnowledgeMode(StrEnum):
    """Select system replay or historical market-availability reconstruction."""

    SYSTEM_KNOWN = "system_known"
    MARKET_AVAILABLE = "market_available"


@dataclass(frozen=True, slots=True)
class SixNaturalDayWindow:
    """One full natural-day window bound to an explicit research-rule version."""

    category: SixPeriod
    start_date: date
    end_date: date
    rule_version: str

    def __post_init__(self) -> None:
        """Reject inverted, mislabeled, or unversioned windows."""

        _require_date(self.start_date, "window.start_date")
        _require_date(self.end_date, "window.end_date")
        _require_identity(self.rule_version, "window.rule_version")
        if not isinstance(self.category, SixPeriod):
            raise InstitutionalCalendarError(
                "SIX_PERIOD_CATEGORY_INVALID", "window category must be typed"
            )
        expected = _period_bounds(self.start_date.year, self.start_date.month, self.category)
        if (self.start_date, self.end_date) != expected:
            raise InstitutionalCalendarError(
                "SIX_PERIOD_WINDOW_INVALID", "window dates do not match their category"
            )


@dataclass(frozen=True, slots=True)
class DateOnlyAvailabilityRule:
    """Versioned conservative availability rule for sources without a time."""

    rule_version: str
    timezone_name: str
    local_cutoff: time

    def __post_init__(self) -> None:
        """Require a valid timezone and a naive local wall-clock cutoff."""

        _require_identity(self.rule_version, "availability.rule_version")
        _require_identity(self.timezone_name, "availability.timezone_name")
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise InstitutionalCalendarError(
                "DATE_ONLY_AVAILABILITY_TIMEZONE_INVALID", "availability timezone is unknown"
            ) from exc
        if type(self.local_cutoff) is not time or self.local_cutoff.tzinfo is not None:
            raise InstitutionalCalendarError(
                "DATE_ONLY_AVAILABILITY_CUTOFF_INVALID",
                "availability cutoff must be a naive local time",
            )


@dataclass(frozen=True, slots=True)
class InstitutionalEvent:
    """One immutable event version with source, market, and system evidence clocks."""

    event_id: str
    source_id: str
    source_event_id: str
    event_type: str
    title: str
    evidence: EvidenceGrade
    lifecycle: EventLifecycle
    revision: int
    scheduled_at: datetime | None
    effective_on: date | None
    source_published_at: datetime | None
    source_published_on: date | None
    available_at: datetime
    first_seen_at: datetime
    recorded_at: datetime
    original_sha256: str
    supersedes_event_id: str | None

    def __post_init__(self) -> None:
        """Fail closed on missing originals, invalid clocks, or false occurrence."""

        for field_name, value in (
            ("event_id", self.event_id),
            ("source_id", self.source_id),
            ("source_event_id", self.source_event_id),
            ("event_type", self.event_type),
        ):
            _require_identity(value, f"event.{field_name}")
        _require_text(self.title, "event.title")
        if not isinstance(self.evidence, EvidenceGrade) or not isinstance(
            self.lifecycle, EventLifecycle
        ):
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_STATE_INVALID", "event evidence and lifecycle must be typed"
            )
        if type(self.revision) is not int or self.revision < 1:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_REVISION_INVALID", "event revision must be positive"
            )
        if self.revision == 1 and self.supersedes_event_id is not None:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_REVISION_INVALID", "first version cannot supersede an event"
            )
        if self.revision > 1:
            if self.supersedes_event_id is None:
                raise InstitutionalCalendarError(
                    "INSTITUTIONAL_EVENT_REVISION_INVALID",
                    "successor must identify its predecessor",
                )
            _require_identity(self.supersedes_event_id, "event.supersedes_event_id")
        for time_field_name, time_value in (
            ("scheduled_at", self.scheduled_at),
            ("source_published_at", self.source_published_at),
            ("available_at", self.available_at),
            ("first_seen_at", self.first_seen_at),
            ("recorded_at", self.recorded_at),
        ):
            if time_value is not None:
                _require_utc(time_value, f"event.{time_field_name}")
        for date_field_name, date_value in (
            ("effective_on", self.effective_on),
            ("source_published_on", self.source_published_on),
        ):
            if date_value is not None:
                _require_date(date_value, f"event.{date_field_name}")
        if self.source_published_at is None and self.source_published_on is None:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_SOURCE_TIME_MISSING",
                "event source publication time is unknown",
            )
        if self.source_published_at is not None and self.available_at < self.source_published_at:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_AVAILABILITY_INVALID",
                "market availability cannot precede source publication",
            )
        if self.recorded_at < self.first_seen_at:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_KNOWLEDGE_TIME_INVALID",
                "recorded_at cannot precede first_seen_at",
            )
        if not _SHA256_RE.fullmatch(self.original_sha256):
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_ORIGINAL_INVALID", "event requires an exact SHA-256 original"
            )
        if self.lifecycle in {EventLifecycle.OCCURRED, EventLifecycle.CANCELLED} and (
            self.evidence is not EvidenceGrade.CONFIRMED or self.source_published_at is None
        ):
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_OCCURRENCE_UNPROVED",
                "occurred or cancelled states require an actual official source",
            )

    def is_visible(self, known_at: datetime, mode: KnowledgeMode) -> bool:
        """Evaluate visibility using only the selected, explicitly named clock mode."""

        _require_utc(known_at, "known_at")
        if not isinstance(mode, KnowledgeMode):
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_EVENT_KNOWLEDGE_MODE_INVALID", "knowledge mode must be typed"
            )
        if mode is KnowledgeMode.SYSTEM_KNOWN:
            return self.first_seen_at <= known_at and self.recorded_at <= known_at
        return self.available_at <= known_at


def six_period_for(day: date, *, rule_version: str) -> SixNaturalDayWindow:
    """Return the full versioned natural-day window containing one date."""

    _require_date(day, "day")
    category = _category_for_day(day.day)
    start, end = _period_bounds(day.year, day.month, category)
    return SixNaturalDayWindow(category, start, end, rule_version)


def iter_six_period_windows(
    coverage_start: date, coverage_end: date, *, rule_version: str
) -> tuple[SixNaturalDayWindow, ...]:
    """Return every complete window overlapping an inclusive cross-month range."""

    _require_date(coverage_start, "coverage_start")
    _require_date(coverage_end, "coverage_end")
    if coverage_start > coverage_end:
        raise InstitutionalCalendarError(
            "SIX_PERIOD_RANGE_INVALID", "coverage_start cannot follow coverage_end"
        )
    windows: list[SixNaturalDayWindow] = []
    year, month = coverage_start.year, coverage_start.month
    while (year, month) <= (coverage_end.year, coverage_end.month):
        for category in SixPeriod:
            start, end = _period_bounds(year, month, category)
            if start <= coverage_end and end >= coverage_start:
                windows.append(SixNaturalDayWindow(category, start, end, rule_version))
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return tuple(windows)


def trading_days_for_window(
    window: SixNaturalDayWindow, days: tuple[ExchangeCalendarDay, ...]
) -> tuple[date, ...]:
    """Align a natural window to explicit sessions without guessing missing dates."""

    if not isinstance(window, SixNaturalDayWindow) or not isinstance(days, tuple):
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE", "calendar coverage must be typed"
        )
    expected_count = (window.end_date - window.start_date).days + 1
    if len(days) != expected_count:
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE", "calendar must cover every natural date"
        )
    exchange: str | None = None
    sessions: list[date] = []
    for index, item in enumerate(days):
        expected_date = window.start_date + timedelta(days=index)
        if not isinstance(item, ExchangeCalendarDay) or item.calendar_date != expected_date:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE",
                "calendar dates must be complete, ordered, and unique",
            )
        if exchange is None:
            exchange = item.exchange
        if item.exchange != exchange:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_CALENDAR_EXCHANGE_MISMATCH", "calendar exchanges cannot be mixed"
            )
        if item.is_open:
            sessions.append(item.calendar_date)
    return tuple(sessions)


def conservative_date_only_available_at(
    source_date: date,
    rule: DateOnlyAvailabilityRule,
    days: tuple[ExchangeCalendarDay, ...],
) -> datetime:
    """Use the next explicitly open day's versioned cutoff, never source midnight."""

    _require_date(source_date, "source_date")
    if not isinstance(rule, DateOnlyAvailabilityRule) or not isinstance(days, tuple):
        raise InstitutionalCalendarError(
            "DATE_ONLY_AVAILABILITY_RULE_INVALID", "availability rule and calendar must be typed"
        )
    by_date: dict[date, ExchangeCalendarDay] = {}
    exchange: str | None = None
    for item in days:
        if not isinstance(item, ExchangeCalendarDay) or item.calendar_date in by_date:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE",
                "calendar rows are invalid or duplicate",
            )
        if exchange is None:
            exchange = item.exchange
        if item.exchange != exchange:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_CALENDAR_EXCHANGE_MISMATCH", "calendar exchanges cannot be mixed"
            )
        by_date[item.calendar_date] = item
    next_session = min(
        (item.calendar_date for item in days if item.calendar_date > source_date and item.is_open),
        default=None,
    )
    if next_session is None:
        raise InstitutionalCalendarError(
            "DATE_ONLY_AVAILABILITY_UNCOVERED", "no next open session exists in calendar coverage"
        )
    current = source_date
    while current <= next_session:
        if current not in by_date:
            raise InstitutionalCalendarError(
                "INSTITUTIONAL_CALENDAR_COVERAGE_INCOMPLETE",
                "date-only availability requires continuous explicit calendar coverage",
            )
        current += timedelta(days=1)
    zone = ZoneInfo(rule.timezone_name)
    return datetime.combine(next_session, rule.local_cutoff, tzinfo=zone).astimezone(UTC)


def _period_bounds(year: int, month: int, category: SixPeriod) -> tuple[date, date]:
    """Calculate exact month-local bounds for a typed category."""

    starts = {
        SixPeriod.DAYS_01_05: 1,
        SixPeriod.DAYS_06_10: 6,
        SixPeriod.DAYS_11_15: 11,
        SixPeriod.DAYS_16_20: 16,
        SixPeriod.DAYS_21_25: 21,
        SixPeriod.DAYS_26_END: 26,
    }
    start_day = starts[category]
    end_day = {
        SixPeriod.DAYS_01_05: 5,
        SixPeriod.DAYS_06_10: 10,
        SixPeriod.DAYS_11_15: 15,
        SixPeriod.DAYS_16_20: 20,
        SixPeriod.DAYS_21_25: 25,
        SixPeriod.DAYS_26_END: calendar.monthrange(year, month)[1],
    }[category]
    return date(year, month, start_day), date(year, month, end_day)


def _category_for_day(day: int) -> SixPeriod:
    """Map a valid day of month to its preregistered category."""

    if day <= 5:
        return SixPeriod.DAYS_01_05
    if day <= 10:
        return SixPeriod.DAYS_06_10
    if day <= 15:
        return SixPeriod.DAYS_11_15
    if day <= 20:
        return SixPeriod.DAYS_16_20
    if day <= 25:
        return SixPeriod.DAYS_21_25
    return SixPeriod.DAYS_26_END


def _require_utc(value: datetime, field_name: str) -> None:
    """Require an aware UTC datetime at every evidence-clock boundary."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_EVENT_TIME_INVALID", f"{field_name} must be timezone-aware UTC"
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_EVENT_TIME_INVALID", f"{field_name} must be timezone-aware UTC"
        )


def _require_date(value: date, field_name: str) -> None:
    """Reject datetime subclasses where only a calendar date is accepted."""

    if type(value) is not date:
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_EVENT_DATE_INVALID", f"{field_name} must be a date"
        )


def _require_identity(value: str, field_name: str) -> None:
    """Require bounded canonical identity text without internal whitespace."""

    _require_text(value, field_name)
    if any(character.isspace() for character in value):
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_EVENT_IDENTITY_INVALID", f"{field_name} must be canonical identity text"
        )


def _require_text(value: str, field_name: str) -> None:
    """Require bounded, stripped, non-empty text."""

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 240:
        raise InstitutionalCalendarError(
            "INSTITUTIONAL_EVENT_IDENTITY_INVALID", f"{field_name} must be bounded non-empty text"
        )


__all__ = [
    "DateOnlyAvailabilityRule",
    "EvidenceGrade",
    "EventLifecycle",
    "InstitutionalCalendarError",
    "InstitutionalEvent",
    "KnowledgeMode",
    "SixNaturalDayWindow",
    "SixPeriod",
    "conservative_date_only_available_at",
    "iter_six_period_windows",
    "six_period_for",
    "trading_days_for_window",
]
