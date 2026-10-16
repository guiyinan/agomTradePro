"""Pure response-age windows for source-bound calendar publication evidence.

The window is a temporal validity calculation only. It does not establish that
a calendar snapshot was formally published, authorize a publisher, or permit
an execution decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .contracts import MAX_CATALOG_TTL_SECONDS
from .exchange_calendar import ExchangeCalendarSnapshot


class CalendarPublicationWindowError(ValueError):
    """Recognized invalid or unsupported calendar publication-window input."""

    def __init__(self, code: str, message: str) -> None:
        """Keep a stable machine-readable reason without an application dependency."""

        self.code = code
        super().__init__(message)


class CalendarPublicationLifecycle(StrEnum):
    """Publication lifecycle states supported by the first calendar window slice."""

    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    REINSTATED = "reinstated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CalendarPublicationWindow:
    """Calculate a half-open response-age window from an exact calendar snapshot.

    ``snapshot.first_seen_at`` is the local response-completion anchor;
    ``published_at`` is a system knowledge event. Neither value is an upstream
    observation clock. The class deliberately carries no source hash changes,
    authority claim, or execution permission.
    """

    snapshot: ExchangeCalendarSnapshot
    calendar_response_max_age_seconds: int
    published_at: datetime
    lifecycle: CalendarPublicationLifecycle
    superseded_at: datetime | None

    def __post_init__(self) -> None:
        """Validate exact source evidence, clock order, TTL bounds, and lifecycle."""

        if type(self.snapshot) is not ExchangeCalendarSnapshot:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_SNAPSHOT_INVALID",
                "snapshot must be an exact ExchangeCalendarSnapshot",
            )
        try:
            self.snapshot.__post_init__()
        except (AttributeError, TypeError, ValueError) as error:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_SNAPSHOT_INVALID",
                "snapshot source or knowledge evidence is invalid",
            ) from error

        if (
            type(self.calendar_response_max_age_seconds) is not int
            or self.calendar_response_max_age_seconds < 1
            or self.calendar_response_max_age_seconds > MAX_CATALOG_TTL_SECONDS
        ):
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_TTL_INVALID",
                "calendar response max age must be a positive signed 64-bit integer",
            )
        if type(self.lifecycle) is not CalendarPublicationLifecycle:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_LIFECYCLE_INVALID",
                "calendar publication lifecycle must be a typed supported state",
            )
        if self.lifecycle in {
            CalendarPublicationLifecycle.ROLLED_BACK,
            CalendarPublicationLifecycle.REINSTATED,
            CalendarPublicationLifecycle.UNSUPPORTED,
        }:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_LIFECYCLE_UNSUPPORTED",
                "calendar rollback, reinstatement, and unknown lifecycle are unsupported",
            )

        _require_utc(self.published_at, "published_at")
        if self.superseded_at is not None:
            _require_utc(self.superseded_at, "superseded_at")
        if self.published_at < self.snapshot.recorded_at:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_KNOWLEDGE_TIME_INVALID",
                "publication knowledge time cannot precede snapshot recording",
            )

        if self.lifecycle is CalendarPublicationLifecycle.PUBLISHED:
            if self.superseded_at is not None:
                raise CalendarPublicationWindowError(
                    "CALENDAR_WINDOW_LIFECYCLE_INVALID",
                    "published lifecycle cannot carry a supersede time",
                )
        elif self.lifecycle is CalendarPublicationLifecycle.SUPERSEDED:
            if self.superseded_at is None:
                raise CalendarPublicationWindowError(
                    "CALENDAR_WINDOW_LIFECYCLE_INVALID",
                    "superseded lifecycle requires an exact supersede time",
                )
            if self.superseded_at < self.published_at:
                raise CalendarPublicationWindowError(
                    "CALENDAR_WINDOW_KNOWLEDGE_TIME_INVALID",
                    "supersede time cannot precede publication knowledge time",
                )

        response_expires_at = self._response_expires_at()
        valid_until = (
            min(response_expires_at, self.superseded_at)
            if self.superseded_at is not None
            else response_expires_at
        )
        if response_expires_at <= self.published_at or valid_until <= self.published_at:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_EXPIRED_AT_PUBLICATION",
                "calendar publication has no positive response-age window",
            )

    @property
    def response_expires_at(self) -> datetime:
        """Return response completion plus the explicit calendar response TTL."""

        self.__post_init__()
        return self._response_expires_at()

    @property
    def valid_from(self) -> datetime:
        """Return the system publication knowledge time, inclusive."""

        self.__post_init__()
        return self.published_at

    @property
    def valid_until(self) -> datetime:
        """Return the earlier of source-response expiry and forward supersession."""

        self.__post_init__()
        response_expires_at = self._response_expires_at()
        if self.superseded_at is None:
            return response_expires_at
        return min(response_expires_at, self.superseded_at)

    def is_effective_at(self, as_of: datetime) -> bool:
        """Return whether this window contains an aware UTC knowledge cutoff."""

        self.__post_init__()
        _require_utc(as_of, "as_of")
        return self.published_at <= as_of < self.valid_until

    def _response_expires_at(self) -> datetime:
        """Add the bounded response TTL without clamping datetime overflow."""

        try:
            return self.snapshot.first_seen_at + timedelta(
                seconds=self.calendar_response_max_age_seconds
            )
        except OverflowError as error:
            raise CalendarPublicationWindowError(
                "CALENDAR_WINDOW_EXPIRY_OVERFLOW",
                "calendar response expiry exceeds the datetime range",
            ) from error


def _require_utc(value: datetime, field_name: str) -> None:
    """Require an exact timezone-aware UTC instant for all knowledge clocks."""

    if type(value) is not datetime or value.tzinfo is None:
        raise CalendarPublicationWindowError(
            "CALENDAR_WINDOW_TIME_INVALID",
            f"{field_name} must be a timezone-aware UTC instant",
        )
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise CalendarPublicationWindowError(
            "CALENDAR_WINDOW_TIME_INVALID",
            f"{field_name} must be a timezone-aware UTC instant",
        )


__all__ = [
    "CalendarPublicationLifecycle",
    "CalendarPublicationWindow",
    "CalendarPublicationWindowError",
]
