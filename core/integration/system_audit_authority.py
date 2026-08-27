"""Composition-root adapters from Account authority ledgers to Audit facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.owner_tenant_authority_v1 import (
    GetCurrentOwnerTenantAuthorityV1Command,
)
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v1 import OwnerTenantAuthorityV1
from apps.account.system_audit_authority_composition import (
    AccountSystemAuditAuthorityReaders,
    build_account_system_audit_authority_readers,
)
from apps.audit.application.system_audit_authority_provider import (
    SystemAuditActorAuthorityFacts,
    SystemAuditActorAuthorityReader,
    SystemAuditScopeAuthorityFacts,
    SystemAuditScopeAuthorityReader,
)


class ActorAuthoritySourceReader(Protocol):
    """Read one exact-current Account actor authority source."""

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Return the exact source or ``None``."""


class OwnerTenantAuthorityReader(Protocol):
    """Read one exact-current owner/tenant authority source."""

    def execute(
        self, command: GetCurrentOwnerTenantAuthorityV1Command
    ) -> OwnerTenantAuthorityV1 | None:
        """Return the exact authority or ``None``."""


class _AliasBoundActorAdapter(SystemAuditActorAuthorityReader, Protocol):
    """Audit actor reader that exposes its composition alias."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the Account actor reader."""


class _AliasBoundScopeAdapter(SystemAuditScopeAuthorityReader, Protocol):
    """Audit scope reader that exposes its composition alias."""

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the owner/tenant scope reader."""


@dataclass(frozen=True, slots=True)
class AccountSystemAuditActorAuthorityAdapter(SystemAuditActorAuthorityReader):
    """Project Account's immutable actor source into Audit facts."""

    reader: ActorAuthoritySourceReader
    database_alias: str = "default"

    def __post_init__(self) -> None:
        """Reject an unbound or malformed reader."""

        if not callable(getattr(self.reader, "execute", None)):
            raise TypeError("actor authority reader must expose execute")
        _validate_alias(self.database_alias)

    def get_current(
        self, *, source_id: str, source_version: str, expected_content_hash: str, as_of: datetime
    ) -> SystemAuditActorAuthorityFacts | None:
        """Forward the exact selector and project only a valid current source."""

        source = self.reader.execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source_id, source_version, expected_content_hash, as_of
            )
        )
        if source is None:
            return None
        if type(source) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise TypeError("actor authority source type substitution")
        source.__post_init__()
        if source.authority_state != "current" or not source.is_temporally_current_at(as_of):
            return None
        return SystemAuditActorAuthorityFacts(
            source_id=source.source_id,
            source_version=source.source_version,
            content_hash=source.content_hash,
            actor_id=source.actor_id,
            user_id=source.user_id,
            is_authenticated=source.is_authenticated,
            is_staff=source.is_staff,
            role=source.rbac_role,
            authority_state="active",
            recorded_at=source.recorded_at,
            valid_until=source.valid_until,
        )


@dataclass(frozen=True, slots=True)
class AccountSystemAuditScopeAuthorityAdapter(SystemAuditScopeAuthorityReader):
    """Project Account's immutable owner/tenant authority into Audit facts."""

    reader: OwnerTenantAuthorityReader
    database_alias: str = "default"

    def __post_init__(self) -> None:
        """Reject an unbound or malformed reader."""

        if not callable(getattr(self.reader, "execute", None)):
            raise TypeError("scope authority reader must expose execute")
        _validate_alias(self.database_alias)

    def get_current(
        self, *, source_id: str, source_version: str, expected_content_hash: str, as_of: datetime
    ) -> SystemAuditScopeAuthorityFacts | None:
        """Forward the exact selector and project only a valid current authority."""

        authority = self.reader.execute(
            GetCurrentOwnerTenantAuthorityV1Command(
                source_id, source_version, expected_content_hash, as_of
            )
        )
        if authority is None:
            return None
        if type(authority) is not OwnerTenantAuthorityV1:
            raise TypeError("owner tenant authority type substitution")
        authority.__post_init__()
        if authority.status != "active" or not authority.is_current_at(as_of):
            return None
        return SystemAuditScopeAuthorityFacts(
            source_id=authority.authority_id,
            source_version=authority.authority_version,
            content_hash=authority.content_hash,
            actor_id=authority.actor_id,
            user_id=authority.actor_user_id,
            tenant_id=authority.tenant_id,
            owner_id=authority.owner_id,
            authority_state=authority.status,
            recorded_at=authority.recorded_at,
            valid_until=authority.valid_until,
        )


@dataclass(frozen=True, slots=True)
class SystemAuditAuthorityReaders:
    """Typed actor/scope readers bound to one database alias."""

    actor: _AliasBoundActorAdapter
    scope: _AliasBoundScopeAdapter
    database_alias: str

    def __post_init__(self) -> None:
        """Require both children to carry the same alias as the bundle."""

        alias = _validate_alias(self.database_alias)
        for name, reader in (("actor", self.actor), ("scope", self.scope)):
            if not callable(getattr(reader, "get_current", None)):
                raise TypeError(f"{name} authority adapter must expose get_current")
            reader_alias = _validate_alias(getattr(reader, "database_alias", None))
            if reader_alias != alias:
                raise ValueError("authority readers must share one database alias")


def build_system_audit_authority_readers(*, using: str = "default") -> SystemAuditAuthorityReaders:
    """Build both concrete authority adapters against one validated alias."""

    alias = _validate_alias(using)
    readers = build_account_system_audit_authority_readers(using=alias)
    if type(readers) is not AccountSystemAuditAuthorityReaders:
        raise TypeError("Account authority reader bundle type was substituted")
    readers.__post_init__()
    if readers.database_alias != alias:
        raise ValueError("Account authority readers must share the Audit database alias")
    return SystemAuditAuthorityReaders(
        actor=AccountSystemAuditActorAuthorityAdapter(readers.actor, alias),
        scope=AccountSystemAuditScopeAuthorityAdapter(readers.scope, alias),
        database_alias=alias,
    )


def _validate_alias(value: object) -> str:
    """Validate one exact bounded database alias."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        raise ValueError("database alias must be one exact database alias")
    return value


__all__ = [
    "AccountSystemAuditActorAuthorityAdapter",
    "AccountSystemAuditScopeAuthorityAdapter",
    "SystemAuditAuthorityReaders",
    "build_system_audit_authority_readers",
]
