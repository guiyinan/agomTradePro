"""Portfolio-owned benchmark trading-calendar methodology definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

POLICY_BENCHMARK_TRADING_CALENDAR_OWNER = "portfolio"
POLICY_BENCHMARK_TRADING_CALENDAR_TYPE = "trading_calendar_definition"
POLICY_BENCHMARK_TRADING_CALENDAR_SCHEMA = "portfolio-policy-benchmark-trading-calendar.v1"
POLICY_BENCHMARK_TRADING_CALENDAR_PERMISSION = "methodology_definition_only"


def _token(value: object, field_name: str, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _local_time(value: object, field_name: str) -> time:
    if type(value) is not time or value.tzinfo is not None:
        raise ValueError(f"{field_name} must be an exact timezone-free local time")
    return value


def _time_text(value: time) -> str:
    text = value.isoformat(timespec="microseconds" if value.microsecond else "seconds")
    return f"{text}[fold=1]" if value.fold == 1 else text


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkCalendarDay:
    """One exact local calendar date and its benchmark valuation session."""

    calendar_date: date
    ordinal: int
    is_valuation_day: bool
    session_open_local: time | None
    session_close_local: time | None
    valuation_cutoff_local: time | None

    def __post_init__(self) -> None:
        if type(self.calendar_date) is not date:
            raise TypeError("calendar_date must be an exact date")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("calendar day ordinal must be an exact non-negative integer")
        if type(self.is_valuation_day) is not bool:
            raise TypeError("is_valuation_day must be an exact boolean")
        clocks = (
            self.session_open_local,
            self.session_close_local,
            self.valuation_cutoff_local,
        )
        if self.is_valuation_day:
            if any(value is None for value in clocks):
                raise ValueError("valuation day requires complete session and cutoff clocks")
            for field_name, value in zip(
                (
                    "session_open_local",
                    "session_close_local",
                    "valuation_cutoff_local",
                ),
                clocks,
                strict=True,
            ):
                _local_time(value, field_name)
        elif any(value is not None for value in clocks):
            raise ValueError("non-valuation day cannot publish session or cutoff clocks")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical complete day membership."""

        return {
            "calendar_date": self.calendar_date.isoformat(),
            "ordinal": self.ordinal,
            "is_valuation_day": self.is_valuation_day,
            "session_open_local": (
                _time_text(self.session_open_local) if self.session_open_local is not None else None
            ),
            "session_close_local": (
                _time_text(self.session_close_local)
                if self.session_close_local is not None
                else None
            ),
            "valuation_cutoff_local": (
                _time_text(self.valuation_cutoff_local)
                if self.valuation_cutoff_local is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PortfolioPolicyBenchmarkTradingCalendar:
    """Complete valuation-date methodology, distinct from monitoring calendars."""

    methodology_id: str
    methodology_version: str
    market_calendar_code: str
    timezone: str
    coverage_start: date
    coverage_end: date
    days: tuple[PolicyBenchmarkCalendarDay, ...]
    recorded_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_TRADING_CALENDAR_OWNER
    artifact_type: str = POLICY_BENCHMARK_TRADING_CALENDAR_TYPE
    schema: str = POLICY_BENCHMARK_TRADING_CALENDAR_SCHEMA
    permission: str = POLICY_BENCHMARK_TRADING_CALENDAR_PERMISSION

    def __post_init__(self) -> None:
        self._validate_authority()
        for field_name in (
            "methodology_id",
            "methodology_version",
            "market_calendar_code",
            "timezone",
        ):
            _token(getattr(self, field_name), field_name)
        if type(self.coverage_start) is not date or type(self.coverage_end) is not date:
            raise TypeError("coverage dates must use exact date values")
        if self.coverage_start > self.coverage_end:
            raise ValueError("calendar coverage window is inverted")
        zone = self._zone()
        self._validate_days(zone)
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        coverage_start_at = datetime.combine(self.coverage_start, time.min, tzinfo=zone)
        coverage_end_at = datetime.combine(
            self.coverage_end + timedelta(days=1), time.min, tzinfo=zone
        )
        if recorded_at > coverage_start_at:
            raise ValueError("trading calendar must be published before coverage starts")
        if valid_until < coverage_end_at:
            raise ValueError("valid_until must cover the complete calendar coverage")
        if recorded_at >= valid_until:
            raise ValueError("trading calendar validity window is invalid")
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        elif _hash(self.identity_hash, "identity_hash") != expected_identity:
            raise ValueError("trading calendar identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        elif _hash(self.content_hash, "content_hash") != expected_content:
            raise ValueError("trading calendar content_hash is invalid")

    def _validate_authority(self) -> None:
        if (
            self.owner != POLICY_BENCHMARK_TRADING_CALENDAR_OWNER
            or self.artifact_type != POLICY_BENCHMARK_TRADING_CALENDAR_TYPE
            or self.schema != POLICY_BENCHMARK_TRADING_CALENDAR_SCHEMA
            or self.permission != POLICY_BENCHMARK_TRADING_CALENDAR_PERMISSION
        ):
            raise ValueError("policy benchmark trading-calendar authority is fixed")

    def _zone(self) -> ZoneInfo:
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone must name an installed IANA timezone") from error
        if zone.key != self.timezone:
            raise ValueError("timezone must use its canonical IANA key")
        return zone

    def _validate_days(self, zone: ZoneInfo) -> None:
        if type(self.days) is not tuple or not self.days:
            raise ValueError("calendar days must be a non-empty exact tuple")
        expected_count = (self.coverage_end - self.coverage_start).days + 1
        if len(self.days) != expected_count:
            raise ValueError("calendar coverage membership must include every date")
        for ordinal, day in enumerate(self.days):
            if type(day) is not PolicyBenchmarkCalendarDay:
                raise TypeError("calendar days must contain exact benchmark day values")
            PolicyBenchmarkCalendarDay.__post_init__(day)
            if day.ordinal != ordinal:
                raise ValueError("calendar day ordinal must be contiguous and ordered")
            if day.calendar_date != self.coverage_start + timedelta(days=ordinal):
                raise ValueError("calendar coverage membership must be consecutive")
            if day.is_valuation_day:
                self._validate_session(day, zone)

    def _validate_session(self, day: PolicyBenchmarkCalendarDay, zone: ZoneInfo) -> None:
        assert day.session_open_local is not None
        assert day.session_close_local is not None
        assert day.valuation_cutoff_local is not None
        opened = _resolve_local(day.calendar_date, day.session_open_local, zone)
        closed = _resolve_local(day.calendar_date, day.session_close_local, zone)
        cutoff = _resolve_local(day.calendar_date, day.valuation_cutoff_local, zone)
        if not opened < closed <= cutoff:
            raise ValueError("valuation day session clock must satisfy open < close <= cutoff")

    @property
    def activation_available(self) -> bool:
        """Remain false until a separate two-person activation exists."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a calendar methodology grants no trade authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable methodology is currently knowable."""

        _aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "methodology_id": self.methodology_id,
            "methodology_version": self.methodology_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "market_calendar_code": self.market_calendar_code,
            "timezone": self.timezone,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "days": [day.to_payload() for day in self.days],
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete definition with explicit inactive safety markers."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def _resolve_local(day: date, clock: time, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(day, clock.replace(tzinfo=None))
    candidates: list[datetime] = []
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold)
        roundtrip = candidate.astimezone(UTC).astimezone(zone)
        if roundtrip.replace(tzinfo=None) == naive and roundtrip.fold == fold:
            candidates.append(candidate)
    if not candidates:
        raise ValueError("local session clock does not exist in the IANA timezone")
    offsets = {candidate.utcoffset() for candidate in candidates}
    if len(offsets) > 1:
        if clock.fold != 1:
            raise ValueError("local session clock is ambiguous without fold=1")
        return candidates[1]
    if clock.fold != 0:
        raise ValueError("fold=1 is noncanonical for an unambiguous local session clock")
    return candidates[0]


__all__ = [
    "POLICY_BENCHMARK_TRADING_CALENDAR_OWNER",
    "POLICY_BENCHMARK_TRADING_CALENDAR_PERMISSION",
    "POLICY_BENCHMARK_TRADING_CALENDAR_SCHEMA",
    "POLICY_BENCHMARK_TRADING_CALENDAR_TYPE",
    "PolicyBenchmarkCalendarDay",
    "PortfolioPolicyBenchmarkTradingCalendar",
]
