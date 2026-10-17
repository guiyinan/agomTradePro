"""Typed, non-authorizing contents for short-lived calendar preview tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreview,
    ConfirmCalendarPublicationIntent,
)
from apps.data_center.domain.exchange_calendar import ExchangeCalendarError
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
)
from core.exceptions import InvalidInputError

CALENDAR_PREVIEW_DATABASE_ALIAS = "default"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ACTOR_USER_ID = (1 << 63) - 1


class CalendarPreviewTokenError(InvalidInputError):
    """Typed fail-closed error for unavailable, invalid, or expired preview tokens."""

    default_message = "Calendar preview token is invalid or unavailable"
    default_code = "CALENDAR_PREVIEW_TOKEN_INVALID"

    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        """Expose a stable token boundary code without including token contents."""

        super().__init__(message, code=code, status_code=status_code)


@dataclass(frozen=True, slots=True)
class CalendarPreviewTokenContent:
    """Exact confirmation echo bound to one actor, session, alias, and original TTL.

    This DTO is content only. It does not authenticate a request, prove a live
    permission, or replace the confirmation flow's fresh CAS and Audit checks.
    """

    intent: ConfirmCalendarPublicationIntent
    actor_user_id: int
    session_key_sha256: str = field(repr=False)
    database_alias: str
    first_seen_at: datetime
    previewed_at: datetime
    response_expires_at: datetime

    def __post_init__(self) -> None:
        """Validate exact nested intent, bindings, and UTC expiry relationship."""

        self.validate()

    def validate(self) -> None:
        """Revalidate fields in case a frozen instance was altered at runtime."""

        if type(self.intent) is not ConfirmCalendarPublicationIntent:
            raise CalendarPreviewTokenError(
                "Preview token content requires an exact confirmation intent",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        if (
            type(self.actor_user_id) is not int
            or self.actor_user_id < 1
            or self.actor_user_id > _MAX_ACTOR_USER_ID
        ):
            raise CalendarPreviewTokenError(
                "Preview token actor identity is invalid",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        if (
            type(self.session_key_sha256) is not str
            or _SHA256_RE.fullmatch(self.session_key_sha256) is None
        ):
            raise CalendarPreviewTokenError(
                "Preview token session binding is invalid",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        if (
            type(self.database_alias) is not str
            or self.database_alias != CALENDAR_PREVIEW_DATABASE_ALIAS
        ):
            raise CalendarPreviewTokenError(
                "Preview token database alias is not supported",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        try:
            self.intent.__post_init__()
        except (
            AttributeError,
            CalendarFormalPublicationError,
            CalendarPublicationOperationsError,
            ExchangeCalendarError,
            TypeError,
            ValueError,
        ) as error:
            raise CalendarPreviewTokenError(
                "Preview token confirmation intent is invalid",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            ) from error
        first_seen_at = _require_utc(self.first_seen_at, "first_seen_at")
        previewed_at = _require_utc(self.previewed_at, "previewed_at")
        response_expires_at = _require_utc(self.response_expires_at, "response_expires_at")
        if first_seen_at > previewed_at:
            raise CalendarPreviewTokenError(
                "Preview token preview time precedes source response completion",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        try:
            expected_expiry = first_seen_at + timedelta(
                seconds=self.intent.expected_identity.calendar_response_max_age_seconds
            )
        except OverflowError as error:
            raise CalendarPreviewTokenError(
                "Preview token response-age TTL exceeds the datetime range",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            ) from error
        if response_expires_at != expected_expiry:
            raise CalendarPreviewTokenError(
                "Preview token expiry does not match the source response-age TTL",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        if previewed_at >= response_expires_at:
            raise CalendarPreviewTokenError(
                "Preview token expiry must follow its original preview time",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )

    @classmethod
    def from_preview(
        cls,
        preview: CalendarPublicationPreview,
        *,
        actor_user_id: int,
        session_key_sha256: str,
    ) -> CalendarPreviewTokenContent:
        """Copy exact echo and TTL clocks from a verified preview into non-authorizing content."""

        if type(preview) is not CalendarPublicationPreview:
            raise CalendarPreviewTokenError(
                "Preview token factory requires an exact publication preview",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            )
        try:
            preview.__post_init__()
            intent = preview.confirmation_intent()
            return cls(
                intent=intent,
                actor_user_id=actor_user_id,
                session_key_sha256=session_key_sha256,
                database_alias=CALENDAR_PREVIEW_DATABASE_ALIAS,
                first_seen_at=preview.first_seen_at,
                previewed_at=preview.previewed_at,
                response_expires_at=preview.response_expires_at,
            )
        except CalendarPreviewTokenError:
            raise
        except (
            AttributeError,
            CalendarFormalPublicationError,
            CalendarPublicationOperationsError,
            ExchangeCalendarError,
            TypeError,
            ValueError,
        ) as error:
            raise CalendarPreviewTokenError(
                "Publication preview cannot be bound to a token",
                code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
            ) from error


class CalendarPreviewTokenCodec(Protocol):
    """Encrypt and validate non-authorizing preview confirmation contents."""

    def encode(self, content: CalendarPreviewTokenContent) -> str:
        """Return a bounded opaque token for one exact preview content DTO."""

    def decode(
        self,
        token: str,
        *,
        actor_user_id: int,
        session_key_sha256: str,
        database_alias: str,
        now: datetime,
    ) -> CalendarPreviewTokenContent:
        """Return the original content only while its bindings and TTL remain valid."""


def _require_utc(value: object, field_name: str) -> datetime:
    """Return an exact timezone-aware UTC datetime or raise a typed token error."""

    if type(value) is not datetime or value.tzinfo is None:
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} must be an aware UTC datetime",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as error:
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} must be an aware UTC datetime",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        ) from error
    if offset != timedelta(0):
        raise CalendarPreviewTokenError(
            f"Preview token {field_name} must use UTC",
            code="CALENDAR_PREVIEW_TOKEN_CONTENT_INVALID",
        )
    return value.astimezone(UTC)
