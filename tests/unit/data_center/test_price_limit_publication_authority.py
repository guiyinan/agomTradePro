"""Application contracts for the fixed price-limit publisher authority."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.data_center.application.price_limit_publication_authority import (
    AuthorizePriceLimitPublisherUseCase,
    LockedPriceLimitPublisherPrincipal,
    PriceLimitPublisherSessionRequestProof,
)
from apps.data_center.interface.price_limit_publication_session_adapter import (
    PriceLimitPublisherSessionAdapter,
)
from core.exceptions import AuthenticationError, AuthorizationError, InvalidInputError

_NOW = datetime(2026, 10, 29, 4, 0, tzinfo=UTC)
_AUTHORITY_HASH = "sha256:" + "a" * 64


class _Principal:
    """Expose an exact, live price-limit permission witness for unit tests."""

    actor_type = "django_user"
    actor_id = "django-user:7"
    permission_codename = "publish_price_limit"
    database_alias = "default"
    user_id = 7
    permission_id = 41
    verified_at = _NOW
    session_expires_at = _NOW + timedelta(hours=1)
    authority_content_hash = _AUTHORITY_HASH

    def assert_live(self) -> None:
        """Represent a principal whose database lock lease remains active."""


class _AuthorityRepository:
    """Yield one typed principal without opening a Django transaction."""

    def __init__(self, principal: LockedPriceLimitPublisherPrincipal) -> None:
        """Store the principal returned by the fake Infrastructure port."""

        self._principal = principal

    @contextmanager
    def locked_price_limit_publisher(
        self,
        _proof: PriceLimitPublisherSessionRequestProof,
    ) -> Iterator[LockedPriceLimitPublisherPrincipal]:
        """Yield the exact principal for the duration of the test context."""

        yield self._principal


def _proof(
    *,
    user_id: int = 7,
    session_key: str = "session-key-test-only",
    request_authenticated_at: datetime = _NOW,
    request_user_database_alias: str = "default",
    database_alias: str = "default",
) -> PriceLimitPublisherSessionRequestProof:
    """Build one valid proof from a session-authenticated interface request."""

    return PriceLimitPublisherSessionRequestProof(
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
        {"request_authenticated_at": datetime(2026, 10, 29)},
        {"request_user_database_alias": "replica"},
    ],
)
def test_proof_rejects_malformed_or_cross_alias_claims(kwargs: dict[str, object]) -> None:
    """The proof cannot represent a bare id, malformed key, or split alias."""

    with pytest.raises((InvalidInputError, AuthorizationError)):
        _proof(**kwargs)  # type: ignore[arg-type]


def test_session_key_is_never_in_proof_repr() -> None:
    """The session credential must not appear in diagnostics."""

    proof = _proof()

    assert proof.session_key == "session-key-test-only"
    assert proof.session_key not in repr(proof)


def test_use_case_yields_exact_principal_only_while_repository_lease_is_open() -> None:
    """Use case binds actor, fixed permission, alias, grant, and live clock."""

    principal = _Principal()
    use_case = AuthorizePriceLimitPublisherUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with use_case.execute(_proof()) as actual:
        assert actual is principal


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_type": "service"},
        {"actor_id": "django-user:8"},
        {"permission_codename": "data_center.publish_exchange_calendar"},
        {"database_alias": "archive"},
        {"user_id": 8},
        {"permission_id": 0},
        {"verified_at": _NOW - timedelta(microseconds=1)},
        {"session_expires_at": _NOW},
        {"authority_content_hash": "not-a-hash"},
    ],
)
def test_use_case_rejects_an_unbound_principal(changes: dict[str, object]) -> None:
    """No Calendar grant, other user, expired lease, or malformed seal passes."""

    principal = _Principal()
    for name, value in changes.items():
        setattr(principal, name, value)
    use_case = AuthorizePriceLimitPublisherUseCase(
        _AuthorityRepository(principal)  # type: ignore[arg-type]
    )

    with pytest.raises(AuthorizationError) as caught:
        with use_case.execute(_proof()):
            pytest.fail("An unbound price-limit principal must not reach the caller")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_PRINCIPAL_INVALID"


def _authenticated_request(method: str) -> Request:
    """Build a DRF session-authenticated request without a database lookup."""

    user_model = get_user_model()
    user = user_model(pk=7, is_active=True)
    user._state.db = "default"
    raw_request = HttpRequest()
    raw_request.method = method
    raw_request.user = user
    raw_request.session = SessionStore(session_key="adapter-session-key")
    request = Request(raw_request, authenticators=[SessionAuthentication()])
    request._authenticator = SessionAuthentication()
    request._user = user
    return request


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_session_adapter_uses_only_the_fixed_price_limit_purpose(
    method: str,
) -> None:
    """Both management methods bind the same fixed permission, never caller input."""

    proof = PriceLimitPublisherSessionAdapter().prove(
        _authenticated_request(method),
        using="default",
    )

    assert proof.user_id == 7
    assert proof.session_key == "adapter-session-key"
    assert proof.database_alias == "default"
    assert not hasattr(proof, "permission_codename")


def test_session_adapter_rejects_unauthenticated_get_before_identity_claim() -> None:
    """An unauthenticated request cannot become a price-limit authority proof."""

    raw_request = HttpRequest()
    raw_request.method = "GET"
    request = Request(raw_request)

    with pytest.raises(AuthenticationError) as caught:
        PriceLimitPublisherSessionAdapter().prove(request, using="default")

    assert caught.value.code == "PRICE_LIMIT_PUBLISHER_SESSION_REQUIRED"
