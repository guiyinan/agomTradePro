"""Server-owned Authority V3 reader used by the System Audit composition root."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apps.account.application.account_owner_assignment_actor_authority_source_v3 import (
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3,
    GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.owner_tenant_authority_v3 import (
    GetCurrentOwnerTenantAuthorityV3Command,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    CurrentOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3,
)
from apps.account.application.physical_account_row_observation_v2 import (
    ExactPhysicalSimulatedAccountRowV2Provider,
)
from apps.account.application.single_owner_actor_authority import SingleOwnerPolicyBinding
from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)
from apps.account.domain.owner_tenant_authority_v3 import OwnerTenantAuthorityV3
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_system_audit_actor_authority_bundle_provider import (
    DjangoAccountSystemAuditActorAuthorityBundleProviderV3,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
)
from apps.account.owner_tenant_authority_v3_composition import (
    build_owner_tenant_authority_v3_facade,
)


@dataclass(frozen=True, slots=True)
class AccountSystemAuditOwnerTenantAuthorityV3Reader:
    """Rebuild a V3 current facade from immutable actor and authority selectors."""

    actor_source_id: str
    actor_source_version: str
    actor_content_hash: str
    physical_row_provider: ExactPhysicalSimulatedAccountRowV2Provider
    database_alias: str = "default"

    def __post_init__(self) -> None:
        """Validate server-owned selectors before any storage access."""

        for name in ("actor_source_id", "actor_source_version"):
            _token(getattr(self, name), name)
        _digest(self.actor_content_hash, "actor_content_hash")
        _alias(self.database_alias)
        for method in ("get_exact_final", "get_exact_current"):
            if not callable(getattr(self.physical_row_provider, method, None)):
                raise TypeError(f"physical row provider must expose {method}")

    def execute(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> CurrentOwnerTenantAuthorityV3 | None:
        """Return one fully revalidated V3 observation without request-derived identity."""

        if type(command) is not GetCurrentOwnerTenantAuthorityV3Command:
            raise TypeError("command must be exact GetCurrentOwnerTenantAuthorityV3Command")
        command.__post_init__()
        authority = self._sealed_authority(command)
        if authority is None:
            return None
        actor = self._current_actor()
        if actor is None:
            return None
        if (
            actor.actor_id != authority.actor_id
            or actor.user_id != authority.actor_user_id
            or actor.is_authenticated is not True
            or actor.is_active is not True
            or actor.is_staff is not True
            or actor.rbac_role != "admin"
        ):
            return None
        principal = AuthenticatedAccountPrincipalV3(
            principal_id=actor.principal_id,
            user_id=actor.user_id,
            authentication_context_hash=actor.authentication_context_content_hash,
            authenticated_at=actor.principal_authenticated_at,
            valid_until=actor.principal_valid_until,
        )
        policy = authority.policy
        binding = SingleOwnerPolicyBinding(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            tenant_id=policy.tenant_id,
            owner_id=policy.owner_id,
            account_namespace=policy.account_namespace,
            account_id=policy.account_id,
        )
        facade = build_owner_tenant_authority_v3_facade(
            principal=principal,
            policy_binding=binding,
            actor_source_id=self.actor_source_id,
            actor_source_version=self.actor_source_version,
            actor_source_content_hash=self.actor_content_hash,
            validity_period=timedelta(seconds=1),
            physical_row_provider=self.physical_row_provider,
            using=self.database_alias,
        )
        return facade.get_current(command)

    def _sealed_authority(
        self,
        command: GetCurrentOwnerTenantAuthorityV3Command,
    ) -> OwnerTenantAuthorityV3 | None:
        """Restore the exact winner only to bind its immutable policy selectors."""

        repository = DjangoOwnerTenantAuthorityV3Repository(using=self.database_alias)
        with repository.atomic():
            cutoff = repository.now()
            record = repository.get_winner(
                authority_id=command.authority_id,
                authority_version=command.authority_version,
                as_of=cutoff,
            )
            if record is None:
                return None
            if type(record) is not PersistedOwnerTenantAuthorityV3:
                raise TypeError("owner tenant authority v3 record type substitution")
            record.__post_init__()
            authority = record.authority
            if authority.content_hash != command.expected_content_hash:
                return None
            head = repository.get_head(authority_id=command.authority_id, as_of=cutoff)
            if type(head) is not PersistedOwnerTenantAuthorityV3 or head.authority != authority:
                return None
            if (
                not authority.is_current_at(cutoff)
                or repository.get_revocation(
                    authority_content_hash=authority.content_hash,
                    as_of=cutoff,
                )
                is not None
            ):
                return None
            return authority

    def _current_actor(self) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        """Read the exact actor selector against its immutable current source bundle."""

        repository = DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository(
            using=self.database_alias
        )
        reader = GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3(
            input_bundle_provider=DjangoAccountSystemAuditActorAuthorityBundleProviderV3(
                using=self.database_alias
            ),
            repository=repository,
        )
        source = reader.execute(
            GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command(
                source_id=self.actor_source_id,
                source_version=self.actor_source_version,
                expected_content_hash=self.actor_content_hash,
                as_of=repository.now(),
            )
        )
        if source is not None and type(source) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise TypeError("actor authority source v3 type substitution")
        return source


def _token(value: object, name: str) -> None:
    """Require one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    """Require one complete lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _alias(value: object) -> None:
    """Require one exact bounded database alias."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 64
        or any(character.isspace() for character in value)
    ):
        raise ValueError("database_alias must be one exact database alias")


__all__ = ["AccountSystemAuditOwnerTenantAuthorityV3Reader"]
