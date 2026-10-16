"""Application boundary checks for the calendar audit reader permission lease."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import pytest
from rest_framework.request import Request

from apps.data_center.application.calendar_audit_read_authority import (
    AuthorizeCalendarAuditReaderUseCase,
    CalendarAuditReaderSessionRequestProof,
    LockedCalendarAuditReaderPrincipal,
)
from apps.data_center.interface.calendar_session_request_claim import (
    _CalendarSessionRequestClaim,
    _prove_calendar_session_request,
)
from core.exceptions import AuthorizationError, InvalidInputError

_NOW = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)


@dataclass
class _Principal:
    """Provide a mutable lease-shaped response for application revalidation."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "view_exchange_calendar_publication_audit"
    database_alias: str = "default"
    user_id: int = 7
    permission_id: int = 31
    verified_at: datetime = _NOW
    session_expires_at: datetime = _NOW + timedelta(hours=1)
    authority_content_hash: str = "sha256:" + "a" * 64
    live: bool = True
    assert_live_calls: int = 0

    def assert_live(self) -> None:
        """Represent a live lock lease and count every liveness check."""

        self.assert_live_calls += 1
        if not self.live:
            raise AuthorizationError("test reader lease expired")


class _AuthorityRepository:
    """Yield one fake lock lease to test application-level exact binding."""

    def __init__(self, principal: LockedCalendarAuditReaderPrincipal) -> None:
        """Store the principal returned for this application test."""

        self._principal = principal

    @contextmanager
    def locked_calendar_audit_reader(
        self,
        _proof: CalendarAuditReaderSessionRequestProof,
    ) -> Iterator[LockedCalendarAuditReaderPrincipal]:
        """Yield the test principal during the repository context."""

        yield self._principal


def _proof(
    *,
    user_id: int = 7,
    session_key: str = "reader-session-key-test",
    request_authenticated_at: datetime = _NOW,
    request_user_database_alias: str = "default",
    database_alias: str = "default",
) -> CalendarAuditReaderSessionRequestProof:
    """Build one valid session claim without asserting it is itself authority."""

    return CalendarAuditReaderSessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=request_authenticated_at,
        request_user_database_alias=request_user_database_alias,
        database_alias=database_alias,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": 0},
        {"user_id": True},
        {"session_key": ""},
        {"session_key": " key"},
        {"session_key": "x" * 41},
        {"request_authenticated_at": datetime(2026, 10, 16)},
        {"request_user_database_alias": "replica"},
    ],
)
def test_reader_proof_rejects_malformed_session_claims(changes: dict[str, object]) -> None:
    """A caller cannot turn a bare id, invalid session, or split alias into proof."""

    with pytest.raises((InvalidInputError, AuthorizationError)):
        _proof(**changes)  # type: ignore[arg-type]


def test_reader_session_key_is_excluded_from_proof_repr() -> None:
    """The bearer session key stays out of ordinary application diagnostics."""

    proof = _proof()

    assert proof.session_key == "reader-session-key-test"
    assert proof.session_key not in repr(proof)


def test_session_request_claim_rejects_unknown_internal_purpose() -> None:
    """An invalid dynamic purpose never falls through to read permission."""

    with pytest.raises(InvalidInputError) as caught:
        _prove_calendar_session_request(
            cast(Request, object()),
            using="default",
            purpose=cast(Literal["publisher", "audit_reader"], "unknown"),
        )

    assert caught.value.code == "CALENDAR_SESSION_PURPOSE_INVALID"


def test_internal_request_claim_hides_session_key_from_repr_and_equality() -> None:
    """The shared adapter claim does not expose or compare its bearer key."""

    claim = _CalendarSessionRequestClaim(
        user_id=7,
        session_key="internal-session-key-test",
        request_authenticated_at=_NOW,
        request_user_database_alias="default",
        database_alias="default",
    )
    same_request_other_key = _CalendarSessionRequestClaim(
        user_id=7,
        session_key="other-internal-session-key-test",
        request_authenticated_at=_NOW,
        request_user_database_alias="default",
        database_alias="default",
    )

    assert "internal-session-key-test" not in repr(claim)
    assert claim == same_request_other_key


def test_use_case_holds_and_rechecks_exact_reader_principal() -> None:
    """The principal is validated at entry and again before normal context exit."""

    principal = _Principal()
    use_case = AuthorizeCalendarAuditReaderUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with use_case.execute(_proof()) as actual:
        assert actual is principal
        assert actual.permission_codename == "view_exchange_calendar_publication_audit"

    assert principal.assert_live_calls >= 2


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_type": "service"},
        {"actor_id": "django-user:8"},
        {"permission_codename": "publish_exchange_calendar"},
        {"database_alias": "archive"},
        {"user_id": 8},
        {"permission_id": 0},
        {"verified_at": _NOW - timedelta(microseconds=1)},
        {"session_expires_at": _NOW},
        {"authority_content_hash": "a" * 64},
    ],
)
def test_use_case_rejects_principal_not_bound_to_current_read_grant(
    changes: dict[str, object],
) -> None:
    """Actor, permission, alias, time, expiry and hash are rechecked at the App edge."""

    principal = _Principal()
    for name, value in changes.items():
        setattr(principal, name, value)
    use_case = AuthorizeCalendarAuditReaderUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with pytest.raises(AuthorizationError) as caught:
        with use_case.execute(_proof()):
            pytest.fail("An unbound reader principal must not reach the caller")

    assert caught.value.code == "CALENDAR_AUDIT_READER_PRINCIPAL_INVALID"
