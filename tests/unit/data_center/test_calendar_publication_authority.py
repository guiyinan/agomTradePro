"""Application-boundary tests for the session publisher principal contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.calendar_publication_authority import (
    AuthorizeCalendarPublisherUseCase,
    CalendarPublisherSessionRequestProof,
    LockedCalendarPublisherPrincipal,
)
from core.exceptions import AuthorizationError, InvalidInputError

_NOW = datetime(2026, 10, 16, 4, 0, tzinfo=UTC)


class _Principal:
    """Provide a typed in-memory witness for Application validation tests."""

    actor_type = "django_user"
    actor_id = "django-user:7"
    permission_codename = "publish_exchange_calendar"
    database_alias = "default"
    user_id = 7
    permission_id = 31
    verified_at = _NOW

    def assert_live(self) -> None:
        """Represent a principal whose repository lock is still held."""


class _AuthorityRepository:
    """Yield one injected principal without opening Django infrastructure."""

    def __init__(self, principal: LockedCalendarPublisherPrincipal) -> None:
        """Store the test principal to exercise application-level revalidation."""

        self._principal = principal

    @contextmanager
    def locked_calendar_publisher(
        self,
        _proof: CalendarPublisherSessionRequestProof,
    ) -> Iterator[LockedCalendarPublisherPrincipal]:
        """Yield the injected principal inside a normal context lifetime."""

        yield self._principal


def _proof(
    *,
    user_id: int = 7,
    session_key: str = "session-key-test-only",
    request_authenticated_at: datetime = _NOW,
    request_user_database_alias: str = "default",
    database_alias: str = "default",
) -> CalendarPublisherSessionRequestProof:
    """Build one structurally valid request claim for use-case tests."""

    return CalendarPublisherSessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=request_authenticated_at,
        request_user_database_alias=request_user_database_alias,
        database_alias=database_alias,
    )


@pytest.mark.parametrize(
    "kwargs",
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
def test_request_proof_rejects_unusable_or_cross_alias_claims(
    kwargs: dict[str, object],
) -> None:
    """The proof cannot represent a bare id, malformed session, or split alias."""

    with pytest.raises((InvalidInputError, AuthorizationError)):
        _proof(**kwargs)  # type: ignore[arg-type]


def test_session_key_is_never_in_the_proof_repr() -> None:
    """The in-memory bearer credential must not appear in ordinary diagnostics."""

    proof = _proof()

    assert proof.session_key == "session-key-test-only"
    assert proof.session_key not in repr(proof)


def test_use_case_yields_exact_principal_only_during_repository_context() -> None:
    """Use case checks request identity, permission name, alias, and time binding."""

    principal = _Principal()
    use_case = AuthorizeCalendarPublisherUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with use_case.execute(_proof()) as actual:
        assert actual is principal


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_type": "service"},
        {"actor_id": "django-user:8"},
        {"permission_codename": "auth.change_user"},
        {"database_alias": "archive"},
        {"user_id": 8},
        {"permission_id": 0},
        {"verified_at": _NOW - timedelta(microseconds=1)},
    ],
)
def test_use_case_rejects_unbound_or_expired_repository_principal(
    changes: dict[str, object],
) -> None:
    """A repository response cannot substitute another actor or stale clock."""

    principal = _Principal()
    for name, value in changes.items():
        setattr(principal, name, value)
    use_case = AuthorizeCalendarPublisherUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with pytest.raises(AuthorizationError) as caught:
        with use_case.execute(_proof()):
            pytest.fail("Invalid principal must not reach the caller")

    assert caught.value.code == "CALENDAR_PUBLISHER_PRINCIPAL_INVALID"
