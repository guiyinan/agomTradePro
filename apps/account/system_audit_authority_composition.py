"""Account-owned composition of immutable authority readers for Audit."""

from __future__ import annotations

from dataclasses import dataclass

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.application.owner_tenant_authority_v1 import GetCurrentOwnerTenantAuthorityV1
from apps.account.infrastructure.account_owner_assignment_actor_authority_bundle_provider import (
    DjangoAccountActorAuthorityInputBundleProviderV3,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.owner_tenant_authority_v1_composition import (
    build_owner_tenant_authority_v1_reader,
)


@dataclass(frozen=True, slots=True)
class AccountSystemAuditAuthorityReaders:
    """Exact Account readers and shared database alias."""

    actor: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3
    scope: GetCurrentOwnerTenantAuthorityV1
    database_alias: str

    def __post_init__(self) -> None:
        """Reject malformed aliases and substituted reader contracts."""

        _validate_alias(self.database_alias)
        for name, reader in (("actor", self.actor), ("scope", self.scope)):
            if not callable(getattr(reader, "execute", None)):
                raise TypeError(f"{name} authority reader must expose execute")


def build_account_system_audit_authority_readers(
    *, using: str = "default"
) -> AccountSystemAuditAuthorityReaders:
    """Build Account authority readers against one validated alias."""

    alias = _validate_alias(using)
    actor = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
        input_bundle_provider=DjangoAccountActorAuthorityInputBundleProviderV3(using=alias),
        repository=DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(using=alias),
    )
    return AccountSystemAuditAuthorityReaders(
        actor=actor,
        scope=build_owner_tenant_authority_v1_reader(using=alias),
        database_alias=alias,
    )


def _validate_alias(value: object) -> str:
    """Return one exact bounded database alias."""

    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("database alias must be one exact database alias")
    return value


__all__ = [
    "AccountSystemAuditAuthorityReaders",
    "build_account_system_audit_authority_readers",
]
