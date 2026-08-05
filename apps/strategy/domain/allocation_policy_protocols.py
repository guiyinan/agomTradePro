"""Repository ports for versioned Strategy allocation policies."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyDraft,
    AllocationPolicyVersion,
)


class AllocationPolicyRepositoryProtocol(Protocol):
    """Persistence boundary consumed by Strategy allocation use cases."""

    def get_active(self, policy_key: str) -> AllocationPolicyVersion | None:
        """Return the active version for ``policy_key``, if one exists."""

        ...

    def get_version(
        self,
        policy_key: str,
        version: int,
    ) -> AllocationPolicyVersion | None:
        """Return one immutable policy version, if it exists."""

        ...

    def list_versions(self, policy_key: str) -> list[AllocationPolicyVersion]:
        """Return all immutable versions from newest to oldest."""

        ...

    def create_version(self, draft: AllocationPolicyDraft) -> AllocationPolicyVersion:
        """Persist ``draft`` as the next inactive version."""

        ...

    def activate_version(
        self,
        policy_key: str,
        version: int,
        *,
        activated_by_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Atomically make a complete draft the sole active version."""

        ...

    def rollback_to_version(
        self,
        policy_key: str,
        version: int,
        *,
        change_reason: str,
        actor_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Copy an old version into a newly activated rollback version."""

        ...
