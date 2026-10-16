"""Application contract for a live, lock-owning calendar audit reader."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core.exceptions import AuthorizationError, InvalidInputError

CALENDAR_AUDIT_READ_PERMISSION_CODENAME = "view_exchange_calendar_publication_audit"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CalendarAuditReaderSessionRequestProof:
    """Carry a real GET session claim for lock-time database revalidation.

    This object is an input claim, not authorization. Infrastructure must
    reload the session, user, exact permission definition, and grant witnesses
    under one alias and keep their locks until the context exits.
    """

    user_id: int
    session_key: str = field(repr=False, compare=False)
    request_authenticated_at: datetime
    request_user_database_alias: str
    database_alias: str

    def __post_init__(self) -> None:
        """Reject malformed claims before Infrastructure performs any query."""

        self.validate()

    def validate(self) -> None:
        """Recheck every field even if a caller bypassed frozen guards."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise InvalidInputError(
                "Calendar audit reader proof requires a positive user id",
                code="CALENDAR_AUDIT_READER_PROOF_INVALID",
            )
        if (
            type(self.session_key) is not str
            or not self.session_key
            or len(self.session_key) > 40
            or self.session_key.strip() != self.session_key
        ):
            raise InvalidInputError(
                "Calendar audit reader proof requires a valid session key",
                code="CALENDAR_AUDIT_READER_PROOF_INVALID",
            )
        _require_aware_utc(self.request_authenticated_at)
        for name, value in (
            ("request user database alias", self.request_user_database_alias),
            ("database alias", self.database_alias),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise InvalidInputError(
                    f"Calendar audit reader proof has an invalid {name}",
                    code="CALENDAR_AUDIT_READER_PROOF_INVALID",
                )
        if self.request_user_database_alias != self.database_alias:
            raise AuthorizationError(
                "Calendar audit reader identity and authority database aliases differ",
                code="CALENDAR_AUDIT_READER_ALIAS_MISMATCH",
            )


class LockedCalendarAuditReaderPrincipal(Protocol):
    """Exact actor and grant witness exposed only while auth row locks remain."""

    @property
    def actor_type(self) -> str:
        """Return the exact actor kind while the lock lease remains active."""

    @property
    def actor_id(self) -> str:
        """Return the canonical actor id while the lock lease remains active."""

    @property
    def permission_codename(self) -> str:
        """Return the exact read permission checked under lock."""

    @property
    def database_alias(self) -> str:
        """Return the alias holding every authorization witness lock."""

    @property
    def user_id(self) -> int:
        """Return the session-authenticated user id while the lease is active."""

    @property
    def permission_id(self) -> int:
        """Return the exact persisted permission id checked under lock."""

    @property
    def verified_at(self) -> datetime:
        """Return the current lock-time permission verification instant."""

    @property
    def session_expires_at(self) -> datetime:
        """Return the locked Django session expiry instant."""

    @property
    def authority_content_hash(self) -> str:
        """Return a digest of the current locked permission/grant observation."""

    def assert_live(self) -> None:
        """Raise unless locks, owner thread, monotonic time, and session remain valid."""


class CalendarAuditReaderAuthorityRepositoryPort(Protocol):
    """Hold the exact read permission witnesses under one owned transaction."""

    def locked_calendar_audit_reader(
        self,
        proof: CalendarAuditReaderSessionRequestProof,
    ) -> AbstractContextManager[LockedCalendarAuditReaderPrincipal]:
        """Revalidate a real session and exact read grant until context exit."""


class AuthorizeCalendarAuditReaderUseCase:
    """Validate the read proof and keep the authorization lease open for its caller."""

    def __init__(self, repository: CalendarAuditReaderAuthorityRepositoryPort) -> None:
        """Build the use case with an explicit, same-alias authority repository."""

        self._repository = repository

    @contextmanager
    def execute(
        self,
        proof: CalendarAuditReaderSessionRequestProof,
    ) -> Iterator[LockedCalendarAuditReaderPrincipal]:
        """Yield a read principal while session and grant witnesses remain locked."""

        if type(proof) is not CalendarAuditReaderSessionRequestProof:
            raise InvalidInputError(
                "Calendar audit reader authorization requires a typed session proof",
                code="CALENDAR_AUDIT_READER_PROOF_INVALID",
            )
        proof.validate()
        with self._repository.locked_calendar_audit_reader(proof) as principal:
            _validate_principal(principal, proof)
            try:
                yield principal
            except BaseException:
                raise
            else:
                principal.assert_live()


def _validate_principal(
    principal: LockedCalendarAuditReaderPrincipal,
    proof: CalendarAuditReaderSessionRequestProof,
) -> None:
    """Reject a structurally shaped repository response for another grant."""

    try:
        principal.assert_live()
        actor_type = principal.actor_type
        actor_id = principal.actor_id
        permission_codename = principal.permission_codename
        database_alias = principal.database_alias
        user_id = principal.user_id
        permission_id = principal.permission_id
        verified_at = principal.verified_at
        session_expires_at = principal.session_expires_at
        authority_content_hash = principal.authority_content_hash
    except (AttributeError, TypeError) as exc:
        raise AuthorizationError(
            "Calendar audit reader repository returned an incomplete principal",
            code="CALENDAR_AUDIT_READER_PRINCIPAL_INVALID",
        ) from exc

    if (
        type(actor_type) is not str
        or actor_type != "django_user"
        or type(actor_id) is not str
        or actor_id != f"django-user:{proof.user_id}"
        or type(permission_codename) is not str
        or permission_codename != CALENDAR_AUDIT_READ_PERMISSION_CODENAME
        or type(database_alias) is not str
        or database_alias != proof.database_alias
        or type(user_id) is not int
        or user_id != proof.user_id
        or type(permission_id) is not int
        or permission_id <= 0
        or not _is_aware_utc(verified_at)
        or verified_at < proof.request_authenticated_at
        or not _is_aware_utc(session_expires_at)
        or session_expires_at <= verified_at
        or type(authority_content_hash) is not str
        or _SHA256_RE.fullmatch(authority_content_hash) is None
    ):
        raise AuthorizationError(
            "Calendar audit reader repository returned an unbound principal",
            code="CALENDAR_AUDIT_READER_PRINCIPAL_INVALID",
        )


def _require_aware_utc(value: object) -> None:
    """Require an aware UTC request instant with a stable application error."""

    if not _is_aware_utc(value):
        raise InvalidInputError(
            "Calendar audit reader proof time must be timezone-aware UTC",
            code="CALENDAR_AUDIT_READER_PROOF_INVALID",
        )


def _is_aware_utc(value: object) -> bool:
    """Return whether a value is an actual UTC-aware datetime."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0


__all__ = [
    "AuthorizeCalendarAuditReaderUseCase",
    "CALENDAR_AUDIT_READ_PERMISSION_CODENAME",
    "CalendarAuditReaderAuthorityRepositoryPort",
    "CalendarAuditReaderSessionRequestProof",
    "LockedCalendarAuditReaderPrincipal",
]
