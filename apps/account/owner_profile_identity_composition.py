"""Composition root for the typed Account owner-profile identity query."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.account.application.owner_profile_identity import GetAccountOwnerProfileIdentityUseCase
from apps.account.infrastructure.owner_profile_identity_repository import (
    DjangoAccountOwnerProfileIdentityRepository,
)


def build_account_owner_profile_identity_query(
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> GetAccountOwnerProfileIdentityUseCase:
    """Build Account's public User-to-profile lookup with its own repository."""

    return GetAccountOwnerProfileIdentityUseCase(
        DjangoAccountOwnerProfileIdentityRepository(using=using)
    )


__all__: tuple[str, ...] = ("build_account_owner_profile_identity_query",)
