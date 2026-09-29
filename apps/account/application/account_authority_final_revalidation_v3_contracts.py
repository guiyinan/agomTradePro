"""Targeted Application read port for the Authority V3 partial final check."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)


@dataclass(frozen=True, slots=True)
class AccountAuthorityV3FinalRootSelection:
    """One exact Authority V3 row selected by its database identity and sealed record."""

    row_id: int
    record: PersistedOwnerTenantAuthorityV3

    def __post_init__(self) -> None:
        """Reject an incomplete or substituted selected row."""

        if type(self.row_id) is not int or self.row_id <= 0:
            raise ValueError("Authority V3 selected row ID must be a positive integer")
        if type(self.record) is not PersistedOwnerTenantAuthorityV3:
            raise TypeError("Authority V3 selected record must be exact")
        self.record.__post_init__()


class AccountAuthorityV3RootRevocationRevalidationRepository(Protocol):
    """Read only one selected Authority V3 row and its revocation slot."""

    @property
    def database_alias(self) -> str:
        """Return the exact Django alias used for every repository query."""

        ...

    def database_clock(self) -> datetime:
        """Return PostgreSQL ``clock_timestamp()`` from the bound connection."""

        ...

    def get_selected_root(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountAuthorityV3FinalRootSelection | None:
        """Read one exact current-head row without traversing its parent graph."""

        ...

    def get_exact_revocation(
        self,
        *,
        selection: AccountAuthorityV3FinalRootSelection,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Read only the selected root's exact revocation slot at ``as_of``."""

        ...


__all__ = [
    "AccountAuthorityV3FinalRootSelection",
    "AccountAuthorityV3RootRevocationRevalidationRepository",
]
