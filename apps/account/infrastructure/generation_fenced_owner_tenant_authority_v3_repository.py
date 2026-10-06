"""Caller-owned read scope for generation-fenced Authority V3 graph reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import DatabaseError, connections

from apps.account.application.owner_tenant_authority_v3_contracts import (
    OwnerTenantAuthorityV3Conflict,
    OwnerTenantAuthorityV3Unavailable,
)
from apps.account.infrastructure.account_authority_generation import (
    AccountAuthorityGenerationUnavailable,
    require_active_account_authority_generation_fence,
)
from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_repository import (
    DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v5_repository import (
    DjangoAccountOwnerAssignmentEvidenceV5Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v3_repository import (
    DjangoOwnerTenantAuthorityV3Repository,
    OwnerTenantAuthorityV3Clock,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)


class GenerationFencedOwnerTenantAuthorityV3Repository(DjangoOwnerTenantAuthorityV3Repository):
    """Join the finalizer-owned generation fence for one current graph read."""

    def __init__(
        self,
        *,
        expected_generation: int,
        using: str,
        clock: OwnerTenantAuthorityV3Clock,
        assignments: DjangoAccountOwnerAssignmentEvidenceV5Repository,
        policies: DjangoSingleOwnerAuthorityPolicyV1Repository,
        actors: DjangoAccountOwnerAssignmentActorAuthoritySourceV3Repository,
    ) -> None:
        """Bind the read-only repository scope to one locked generation."""

        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be one non-negative integer")
        super().__init__(
            using=using,
            clock=clock,
            assignments=assignments,
            policies=policies,
            actors=actors,
        )
        self._expected_generation = expected_generation

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Reuse the caller's outer transaction without granting write capability."""

        self._postgresql()
        connection = connections[self._using]
        require_active_account_authority_generation_fence(
            using=self._using,
            connection=connection,
            generation=self._expected_generation,
        )
        if self._active:
            raise OwnerTenantAuthorityV3Conflict(
                "owner tenant authority v3 UOW cannot be re-entered"
            )
        self._active = True
        try:
            yield
            require_active_account_authority_generation_fence(
                using=self._using,
                connection=connection,
                generation=self._expected_generation,
            )
        except AccountAuthorityGenerationUnavailable:
            raise
        except DatabaseError as error:
            raise OwnerTenantAuthorityV3Unavailable(
                "owner tenant authority v3 caller-owned transaction is unavailable"
            ) from error
        finally:
            self._uow = None
            self._active = False


__all__ = ["GenerationFencedOwnerTenantAuthorityV3Repository"]
