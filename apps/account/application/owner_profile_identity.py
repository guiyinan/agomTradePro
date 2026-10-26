"""Typed Application contract for mapping an authenticated User to its profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AccountOwnerProfileIdentity:
    """Stable User/Profile identity pair resolved by Account's own source."""

    user_id: int
    profile_id: int

    def __post_init__(self) -> None:
        """Require two independent positive primary keys."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive exact integer")
        if type(self.profile_id) is not int or self.profile_id <= 0:
            raise ValueError("profile_id must be a positive exact integer")


class AccountOwnerProfileIdentityRepository(Protocol):
    """Read the AccountProfile identity bound to one authenticated User ID."""

    def get_for_user(self, *, user_id: int) -> AccountOwnerProfileIdentity | None:
        """Return the exact persisted pair or None when the account profile is absent."""
        ...


class GetAccountOwnerProfileIdentityUseCase:
    """Resolve User-to-profile ownership without exposing Account ORM models."""

    def __init__(self, repository: AccountOwnerProfileIdentityRepository) -> None:
        """Inject Account's typed owner-profile query port."""

        self._repository = repository

    def execute(self, *, user_id: int) -> AccountOwnerProfileIdentity | None:
        """Return no profile for an invalid User ID instead of guessing an ID match."""

        if type(user_id) is not int or user_id <= 0:
            return None
        identity = self._repository.get_for_user(user_id=user_id)
        if identity is None or identity.user_id != user_id:
            return None
        return identity


__all__: tuple[str, ...] = (
    "AccountOwnerProfileIdentity",
    "AccountOwnerProfileIdentityRepository",
    "GetAccountOwnerProfileIdentityUseCase",
)
