"""Targeted, read-only repository for the Authority V3 root/revocation slice."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from django.db import DatabaseError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.connection import ConnectionDoesNotExist

from apps.account.application.account_authority_final_revalidation_v3_contracts import (
    AccountAuthorityV3FinalRootSelection,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Corruption,
    OwnerTenantAuthorityV3Unavailable,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    validate_owner_tenant_authority_v3_revocation,
)
from apps.account.infrastructure._owner_tenant_authority_v3_repository_helpers import (
    _pk,
    _restore_revocation,
    _restore_root,
)
from apps.account.infrastructure.owner_tenant_authority_v3_models import (
    OwnerTenantAuthorityV3Model,
    OwnerTenantAuthorityV3RevocationModel,
)


class DjangoAccountAuthorityV3RootRevocationRevalidationRepository:
    """Read exact root and revocation rows without invoking the legacy facade."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        """Bind all targeted queries to one explicit Django database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("account authority database alias is invalid")
        self._using = using

    @property
    def database_alias(self) -> str:
        """Return the alias bound to every targeted read."""

        return self._using

    def database_clock(self) -> datetime:
        """Read PostgreSQL's advancing wall clock on the bound connection."""

        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT clock_timestamp()")
                row = cast(tuple[object, ...] | None, cursor.fetchone())
        except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 final-check database clock is unavailable"
            ) from error
        if row is None or type(row[0]) is not datetime or not _is_aware(row[0]):
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 final-check database clock is invalid"
            )
        return row[0]

    def get_selected_root(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountAuthorityV3FinalRootSelection | None:
        """Restore one exact row and reject it if a recorded successor exists."""

        self._validate_selector(authority_id, "authority_id")
        self._validate_selector(authority_version, "authority_version")
        self._validate_hash(expected_content_hash)
        self._validate_cutoff(as_of)
        self._connection()
        try:
            rows = tuple(
                OwnerTenantAuthorityV3Model._default_manager.using(self._using)
                .filter(
                    authority_id=authority_id,
                    authority_version=authority_version,
                    content_hash=expected_content_hash,
                    recorded_at__lte=as_of,
                )
                .order_by("pk")[:2]
            )
            if len(rows) > 1:
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 selected row identity is ambiguous"
                )
            if not rows:
                return None
            row = rows[0]
            record = _restore_root(row)
            authority = record.authority
            if (
                authority.authority_id,
                authority.authority_version,
                authority.content_hash,
            ) != (authority_id, authority_version, expected_content_hash):
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 selected row differs from its exact selectors"
                )
            row_id = _pk(row)
            successors = tuple(
                OwnerTenantAuthorityV3Model._default_manager.using(self._using)
                .filter(predecessor_id=row_id, recorded_at__lte=as_of)
                .order_by("pk")[:2]
            )
            if successors:
                return None
            return AccountAuthorityV3FinalRootSelection(row_id=row_id, record=record)
        except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 selected row cannot be read"
            ) from error

    def get_exact_revocation(
        self,
        *,
        selection: AccountAuthorityV3FinalRootSelection,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Restore only the revocation row bound to this root's exact identity."""

        if type(selection) is not AccountAuthorityV3FinalRootSelection:
            raise TypeError("Authority V3 selected root must be exact")
        selection.__post_init__()
        self._validate_cutoff(as_of)
        self._connection()
        authority = selection.record.authority
        try:
            rows = tuple(
                OwnerTenantAuthorityV3RevocationModel._default_manager.using(self._using)
                .filter(
                    authority_id=selection.row_id,
                    authority_content_hash=authority.content_hash,
                    recorded_at__lte=as_of,
                )
                .order_by("pk")[:2]
            )
            if len(rows) > 1:
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 selected revocation slot is ambiguous"
                )
            if not rows:
                return None
            row = rows[0]
            record = _restore_revocation(row)
            revocation = record.revocation
            if (
                row.authority_id != selection.row_id
                or revocation.authority_content_hash != authority.content_hash
                or revocation.policy_content_hash != authority.policy.content_hash
            ):
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 revocation is substituted from its selected root"
                )
            try:
                validate_owner_tenant_authority_v3_revocation(authority, revocation)
            except (TypeError, ValueError) as error:
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 revocation does not validate against its selected root"
                ) from error
            if type(record) is not PersistedOwnerTenantAuthorityV3Revocation:
                raise OwnerTenantAuthorityV3Corruption(
                    "Authority V3 revocation record type is invalid"
                )
            return record
        except (DatabaseError, ConnectionDoesNotExist, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 selected revocation cannot be read"
            ) from error

    def _connection(self) -> BaseDatabaseWrapper:
        """Return only the declared PostgreSQL connection."""

        try:
            connection = connections[self._using]
        except (ConnectionDoesNotExist, KeyError) as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 final-check database alias is unavailable"
            ) from error
        if connection.vendor != "postgresql" or getattr(connection, "alias", None) != self._using:
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 final-check requires its exact PostgreSQL alias"
            )
        return connection

    @staticmethod
    def _validate_selector(value: object, name: str) -> None:
        """Reject malformed Authority V3 selector tokens at the repository edge."""

        if (
            type(value) is not str
            or not value
            or value.strip() != value
            or len(value) > 192
            or any(character.isspace() for character in value)
        ):
            raise OwnerTenantAuthorityV3Unavailable(f"{name} selector is invalid")

    @staticmethod
    def _validate_hash(value: object) -> None:
        """Require one complete lowercase SHA-256 content hash."""

        if (
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise OwnerTenantAuthorityV3Unavailable("Authority V3 content hash selector is invalid")

    @staticmethod
    def _validate_cutoff(value: object) -> None:
        """Require an exact timezone-aware selection cutoff."""

        if not _is_aware(value):
            raise OwnerTenantAuthorityV3Unavailable(
                "Authority V3 final-check cutoff must be timezone-aware"
            )


def _is_aware(value: object) -> bool:
    """Return whether an exact datetime carries a usable UTC offset."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = ["DjangoAccountAuthorityV3RootRevocationRevalidationRepository"]
