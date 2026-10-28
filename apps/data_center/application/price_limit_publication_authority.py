"""Application contract for live price-limit publication authority."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from core.exceptions import AuthorizationError, InvalidInputError

PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME = "publish_price_limit"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PriceLimitPublisherSessionRequestProof:
    """Carry one real session claim for locked Infrastructure revalidation.

    This proof is not authorization. Infrastructure reloads the database
    session, active user, exact permission, and grant rows under one alias.
    The session key is a credential and is excluded from ordinary repr output.
    """

    user_id: int
    session_key: str = field(repr=False, compare=False)
    request_authenticated_at: datetime
    request_user_database_alias: str
    database_alias: str

    def __post_init__(self) -> None:
        """Reject malformed proof data before any repository access."""

        self.validate()

    def validate(self) -> None:
        """Revalidate every field even if a caller bypassed frozen guards."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise InvalidInputError(
                "Price-limit publisher proof requires a positive user id",
                code="PRICE_LIMIT_PUBLISHER_PROOF_INVALID",
            )
        if (
            type(self.session_key) is not str
            or not self.session_key
            or len(self.session_key) > 40
            or self.session_key.strip() != self.session_key
        ):
            raise InvalidInputError(
                "Price-limit publisher proof requires a valid session key",
                code="PRICE_LIMIT_PUBLISHER_PROOF_INVALID",
            )
        if not _is_aware_utc(self.request_authenticated_at):
            raise InvalidInputError(
                "Price-limit publisher proof time must be timezone-aware UTC",
                code="PRICE_LIMIT_PUBLISHER_PROOF_INVALID",
            )
        for name, value in (
            ("request user database alias", self.request_user_database_alias),
            ("database alias", self.database_alias),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise InvalidInputError(
                    f"Price-limit publisher proof has an invalid {name}",
                    code="PRICE_LIMIT_PUBLISHER_PROOF_INVALID",
                )
        if self.request_user_database_alias != self.database_alias:
            raise AuthorizationError(
                "Price-limit publisher identity and authority database aliases differ",
                code="PRICE_LIMIT_PUBLISHER_ALIAS_MISMATCH",
            )


class LockedPriceLimitPublisherPrincipal(Protocol):
    """Exact actor and permission witness valid only under database locks."""

    @property
    def actor_type(self) -> str:
        """Return the verified actor kind while the lease is active."""

    @property
    def actor_id(self) -> str:
        """Return the canonical verified actor id while the lease is active."""

    @property
    def permission_codename(self) -> str:
        """Return the fixed price-limit permission checked under lock."""

    @property
    def database_alias(self) -> str:
        """Return the alias that holds all authorization row locks."""

    @property
    def user_id(self) -> int:
        """Return the authenticated Django user id while live."""

    @property
    def permission_id(self) -> int:
        """Return the persisted permission id checked under lock."""

    @property
    def verified_at(self) -> datetime:
        """Return the post-lock verification instant."""

    @property
    def session_expires_at(self) -> datetime:
        """Return the locked database session expiry instant."""

    @property
    def authority_content_hash(self) -> str:
        """Return the digest of this purpose's locked grant witnesses."""

    def assert_live(self) -> None:
        """Raise unless the row locks and session lease remain valid."""


class PriceLimitPublisherAuthorityRepositoryPort(Protocol):
    """Hold one session and explicit price-limit grant under one alias."""

    def locked_price_limit_publisher(
        self,
        proof: PriceLimitPublisherSessionRequestProof,
    ) -> AbstractContextManager[LockedPriceLimitPublisherPrincipal]:
        """Revalidate and hold the exact live permission witnesses."""


class AuthorizePriceLimitPublisherUseCase:
    """Validate proof and expose the exact locked price-limit principal."""

    def __init__(self, repository: PriceLimitPublisherAuthorityRepositoryPort) -> None:
        """Build the use case with its explicit Infrastructure port."""

        self._repository = repository

    @contextmanager
    def execute(
        self,
        proof: PriceLimitPublisherSessionRequestProof,
    ) -> Iterator[LockedPriceLimitPublisherPrincipal]:
        """Yield a principal only while the repository lease remains active."""

        if type(proof) is not PriceLimitPublisherSessionRequestProof:
            raise InvalidInputError(
                "Price-limit publisher authorization requires a typed session proof",
                code="PRICE_LIMIT_PUBLISHER_PROOF_INVALID",
            )
        proof.validate()
        with self._repository.locked_price_limit_publisher(proof) as principal:
            _validate_principal(principal, proof)
            yield principal
            principal.assert_live()


def _validate_principal(
    principal: LockedPriceLimitPublisherPrincipal,
    proof: PriceLimitPublisherSessionRequestProof,
) -> None:
    """Reject a repository witness for another actor, permission, or lease."""

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
            "Price-limit publisher repository returned an incomplete principal",
            code="PRICE_LIMIT_PUBLISHER_PRINCIPAL_INVALID",
        ) from exc

    if (
        type(actor_type) is not str
        or actor_type != "django_user"
        or type(actor_id) is not str
        or actor_id != f"django-user:{proof.user_id}"
        or type(permission_codename) is not str
        or permission_codename != PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME
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
            "Price-limit publisher repository returned an unbound principal",
            code="PRICE_LIMIT_PUBLISHER_PRINCIPAL_INVALID",
        )


def _is_aware_utc(value: object) -> bool:
    """Return whether a value is an actual UTC-aware datetime."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0


__all__ = [
    "AuthorizePriceLimitPublisherUseCase",
    "LockedPriceLimitPublisherPrincipal",
    "PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME",
    "PriceLimitPublisherAuthorityRepositoryPort",
    "PriceLimitPublisherSessionRequestProof",
]
