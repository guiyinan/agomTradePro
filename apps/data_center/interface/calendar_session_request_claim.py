"""Shared Interface validation for fixed-purpose session request adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from core.exceptions import AuthenticationError, ExternalServiceError, InvalidInputError

_Purpose = Literal["publisher", "audit_reader", "price_limit_publisher"]
_VALID_PURPOSES = ("publisher", "audit_reader", "price_limit_publisher")


@dataclass(frozen=True, slots=True)
class _CalendarSessionRequestClaim:
    """Raw session facts extracted from one real authenticated DRF request."""

    user_id: int
    session_key: str = field(repr=False, compare=False)
    request_authenticated_at: datetime
    request_user_database_alias: str
    database_alias: str


def _prove_session_request_claim(
    request: Request,
    *,
    using: str,
    purpose: _Purpose,
) -> _CalendarSessionRequestClaim:
    """Require one exact HTTP method, DRF SessionAuth, and same-alias DB session."""

    if type(purpose) is not str or purpose not in _VALID_PURPOSES:
        raise InvalidInputError(
            "Session request adapter received an unsupported internal purpose",
            code="CALENDAR_SESSION_PURPOSE_INVALID",
        )
    if purpose == "publisher":
        prefix = "CALENDAR_PUBLISHER_"
        subject = "Calendar publisher"
        required_methods: tuple[str, ...] = ("POST",)
    elif purpose == "audit_reader":
        prefix = "CALENDAR_AUDIT_READER_"
        subject = "Calendar audit reader"
        required_methods = ("GET",)
    else:
        prefix = "PRICE_LIMIT_PUBLISHER_"
        subject = "Price-limit publisher manager"
        required_methods = ("GET", "POST")
    required_method_text = " or ".join(required_methods)

    if (
        not isinstance(request, Request)
        or type(using) is not str
        or not using
        or using.strip() != using
    ):
        raise AuthenticationError(
            f"{subject} requires a DRF request and explicit database alias",
            code=f"{prefix}REQUEST_INVALID",
        )
    if request.method not in required_methods:
        raise AuthenticationError(
            f"{subject} requires a session-authenticated {required_method_text} request",
            code=f"{prefix}SESSION_REQUIRED",
        )
    if type(request.successful_authenticator) is not SessionAuthentication:
        raise AuthenticationError(
            f"{subject} accepts only Django session authentication",
            code=f"{prefix}SESSION_REQUIRED",
        )

    raw_request = request._request
    if not isinstance(raw_request, HttpRequest) or raw_request.method not in required_methods:
        raise AuthenticationError(
            f"{subject} request does not match its Django request",
            code=f"{prefix}REQUEST_INVALID",
        )
    user_model = get_user_model()
    user = request.user
    raw_user = raw_request.user
    if (
        not isinstance(user, user_model)
        or not isinstance(raw_user, user_model)
        or user.is_authenticated is not True
        or raw_user.is_authenticated is not True
        or type(user.pk) is not int
        or user.pk <= 0
        or raw_user.pk != user.pk
    ):
        raise AuthenticationError(
            f"{subject} requires the authenticated Django user",
            code=f"{prefix}SESSION_REQUIRED",
        )

    session = raw_request.session
    session_engine = settings.SESSION_ENGINE
    if session_engine != "django.contrib.sessions.backends.db":
        raise ExternalServiceError(
            f"{subject} requires a lockable database session backend",
            code=f"{prefix}SESSION_BACKEND_UNAVAILABLE",
        )
    session_store = import_string(f"{session_engine}.SessionStore")
    if type(session) is not session_store:
        raise AuthenticationError(
            f"{subject} request has no database-backed session",
            code=f"{prefix}SESSION_REQUIRED",
        )
    session_key = session.session_key
    if type(session_key) is not str or not session_key:
        raise AuthenticationError(
            f"{subject} session is unavailable",
            code=f"{prefix}SESSION_REQUIRED",
        )

    user_alias = user._state.db
    raw_user_alias = raw_user._state.db
    if type(user_alias) is not str or user_alias != raw_user_alias or user_alias != using:
        raise AuthenticationError(
            f"{subject} session user is not on the requested database",
            code=f"{prefix}ALIAS_MISMATCH",
        )

    return _CalendarSessionRequestClaim(
        user_id=user.pk,
        session_key=session_key,
        request_authenticated_at=timezone.now(),
        request_user_database_alias=user_alias,
        database_alias=using,
    )


def _prove_calendar_session_request(
    request: Request,
    *,
    using: str,
    purpose: Literal["publisher", "audit_reader"],
) -> _CalendarSessionRequestClaim:
    """Retain the existing Calendar-only helper surface for its adapters."""

    return _prove_session_request_claim(request, using=using, purpose=purpose)
