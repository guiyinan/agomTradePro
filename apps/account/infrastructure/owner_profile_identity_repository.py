"""Django-backed Account owner User/Profile identity query."""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS

from apps.account.application.owner_profile_identity import (
    AccountOwnerProfileIdentity,
    AccountOwnerProfileIdentityRepository,
)
from apps.account.infrastructure.identity_models import AccountProfileModel


class DjangoAccountOwnerProfileIdentityRepository(AccountOwnerProfileIdentityRepository):
    """Read only the profile ID tied to the actual authenticated User row."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the database alias used by the surrounding Application composition."""

        self._using = using

    def get_for_user(self, *, user_id: int) -> AccountOwnerProfileIdentity | None:
        """Return exact User/Profile IDs without relying on numeric ID coincidence."""

        row = (
            AccountProfileModel._default_manager.using(self._using)
            .filter(user_id=user_id)
            .values_list("user_id", "pk")
            .first()
        )
        if row is None:
            return None
        source_user_id, profile_id = row
        if type(source_user_id) is not int or type(profile_id) is not int:
            return None
        if source_user_id != user_id or profile_id <= 0:
            return None
        return AccountOwnerProfileIdentity(user_id=source_user_id, profile_id=profile_id)


__all__: tuple[str, ...] = ("DjangoAccountOwnerProfileIdentityRepository",)
