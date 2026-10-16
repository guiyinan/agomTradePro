"""Session-bound application contract for calendar publication principals."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core.exceptions import AuthorizationError, InvalidInputError

CALENDAR_PUBLISH_PERMISSION_CODENAME = "publish_exchange_calendar"


@dataclass(frozen=True, slots=True)
class CalendarPublisherSessionRequestProof:
    """Carry the authenticated session claim for lock-time database revalidation.

    The proof is not authority by itself. Infrastructure must reload the session,
    user, permission, and concrete grant rows from ``database_alias`` while their
    rows are locked. The session key is a credential and is excluded from repr.
    """

    user_id: int
    session_key: str = field(repr=False, compare=False)
    request_authenticated_at: datetime
    request_user_database_alias: str
    database_alias: str

    def __post_init__(self) -> None:
        """Reject malformed claims before any repository access."""

        self.validate()

    def validate(self) -> None:
        """Revalidate fields even if a caller bypassed frozen dataclass guards."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise InvalidInputError(
                "Calendar publisher proof requires a positive user id",
                code="CALENDAR_PUBLISHER_PROOF_INVALID",
            )
        if (
            type(self.session_key) is not str
            or not self.session_key
            or len(self.session_key) > 40
            or self.session_key.strip() != self.session_key
        ):
            raise InvalidInputError(
                "Calendar publisher proof requires a valid session key",
                code="CALENDAR_PUBLISHER_PROOF_INVALID",
            )
        _require_aware_utc(self.request_authenticated_at)
        for name, value in (
            ("request user database alias", self.request_user_database_alias),
            ("database alias", self.database_alias),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise InvalidInputError(
                    f"Calendar publisher proof has an invalid {name}",
                    code="CALENDAR_PUBLISHER_PROOF_INVALID",
                )
        if self.request_user_database_alias != self.database_alias:
            raise AuthorizationError(
                "Calendar publisher identity and authority database aliases differ",
                code="CALENDAR_PUBLISHER_ALIAS_MISMATCH",
            )


class LockedCalendarPublisherPrincipal(Protocol):
    """Exact authenticated actor exposed only while its database locks are held."""

    @property
    def actor_type(self) -> str:
        """Return the exact actor kind while the lock lease remains active."""

    @property
    def actor_id(self) -> str:
        """Return the canonical actor id while the lock lease remains active."""

    @property
    def permission_codename(self) -> str:
        """Return the exact permission codename checked under lock."""

    @property
    def database_alias(self) -> str:
        """Return the database alias holding all authorization locks."""

    @property
    def user_id(self) -> int:
        """Return the authenticated user id while the lease remains active."""

    @property
    def permission_id(self) -> int:
        """Return the exact persisted permission id checked under lock."""

    @property
    def verified_at(self) -> datetime:
        """Return the post-lock verification instant while the lease is active."""

    def assert_live(self) -> None:
        """Raise unless the authorization row locks are still held."""


class CalendarPublisherAuthorityRepositoryPort(Protocol):
    """Verify a session and explicit permission under one alias and transaction."""

    def locked_calendar_publisher(
        self,
        proof: CalendarPublisherSessionRequestProof,
    ) -> AbstractContextManager[LockedCalendarPublisherPrincipal]:
        """Hold current session, identity, and permission witnesses until exit."""


class AuthorizeCalendarPublisherUseCase:
    """Recheck application inputs and expose only an exact locked principal."""

    def __init__(self, repository: CalendarPublisherAuthorityRepositoryPort) -> None:
        """Build the use case with an explicit authority repository."""

        self._repository = repository

    @contextmanager
    def execute(
        self,
        proof: CalendarPublisherSessionRequestProof,
    ) -> Iterator[LockedCalendarPublisherPrincipal]:
        """Yield a principal while session and permission witnesses remain locked."""

        if type(proof) is not CalendarPublisherSessionRequestProof:
            raise InvalidInputError(
                "Calendar publisher authorization requires a typed session proof",
                code="CALENDAR_PUBLISHER_PROOF_INVALID",
            )
        proof.validate()
        with self._repository.locked_calendar_publisher(proof) as principal:
            _validate_principal(principal, proof)
            yield principal


def _validate_principal(
    principal: LockedCalendarPublisherPrincipal,
    proof: CalendarPublisherSessionRequestProof,
) -> None:
    """Reject a structurally valid repository result for another principal."""

    try:
        principal.assert_live()
        actor_type = principal.actor_type
        actor_id = principal.actor_id
        permission_codename = principal.permission_codename
        database_alias = principal.database_alias
        user_id = principal.user_id
        permission_id = principal.permission_id
        verified_at = principal.verified_at
    except (AttributeError, TypeError) as exc:
        raise AuthorizationError(
            "Calendar publisher repository returned an incomplete principal",
            code="CALENDAR_PUBLISHER_PRINCIPAL_INVALID",
        ) from exc

    if (
        type(actor_type) is not str
        or actor_type != "django_user"
        or type(actor_id) is not str
        or actor_id != f"django-user:{proof.user_id}"
        or type(permission_codename) is not str
        or permission_codename != CALENDAR_PUBLISH_PERMISSION_CODENAME
        or type(database_alias) is not str
        or database_alias != proof.database_alias
        or type(user_id) is not int
        or user_id != proof.user_id
        or type(permission_id) is not int
        or permission_id <= 0
        or not _is_aware_utc(verified_at)
        or verified_at < proof.request_authenticated_at
    ):
        raise AuthorizationError(
            "Calendar publisher repository returned an unbound principal",
            code="CALENDAR_PUBLISHER_PRINCIPAL_INVALID",
        )


def _require_aware_utc(value: object) -> None:
    """Require a UTC instant and report malformed request proof consistently."""

    if not _is_aware_utc(value):
        raise InvalidInputError(
            "Calendar publisher proof time must be timezone-aware UTC",
            code="CALENDAR_PUBLISHER_PROOF_INVALID",
        )


def _is_aware_utc(value: object) -> bool:
    """Return whether a value is an actual UTC-aware datetime."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0


__all__ = [
    "AuthorizeCalendarPublisherUseCase",
    "CALENDAR_PUBLISH_PERMISSION_CODENAME",
    "CalendarPublisherAuthorityRepositoryPort",
    "CalendarPublisherSessionRequestProof",
    "LockedCalendarPublisherPrincipal",
]
