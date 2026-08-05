"""Application use cases for Strategy-owned allocation-policy versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyDraft,
    AllocationPolicyStatus,
    AllocationPolicyUnavailableError,
    AllocationPolicyVersion,
    AllocationTarget,
    resolve_allocation_target,
)
from apps.strategy.domain.allocation_policy_protocols import (
    AllocationPolicyRepositoryProtocol,
)

DEFAULT_ALLOCATION_POLICY_KEY = "strategic_asset_allocation"


@dataclass(frozen=True)
class ActivateAllocationPolicyRequest:
    """Input for activating one already-created policy version."""

    policy_key: str
    version: int
    actor_id: int | None
    effective_at: datetime | None = None


@dataclass(frozen=True)
class RollbackAllocationPolicyRequest:
    """Input for copying and activating an older policy revision."""

    policy_key: str
    version: int
    change_reason: str
    actor_id: int | None
    effective_at: datetime | None = None


class GetActiveAllocationPolicy:
    """Read the active allocation policy through an injected repository port."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, policy_key: str) -> AllocationPolicyVersion:
        """Return the active version or fail closed with a stable reason."""

        active = self._repository.get_active(policy_key)
        if active is None:
            raise AllocationPolicyUnavailableError(f"active_allocation_policy_missing:{policy_key}")
        active.validate_for_activation()
        return active


class ListAllocationPolicyVersions:
    """List immutable allocation-policy versions through the repository port."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, policy_key: str) -> list[AllocationPolicyVersion]:
        """Return versions in repository-defined newest-first order."""

        if not policy_key.strip():
            raise ValueError("policy_key is required")
        return self._repository.list_versions(policy_key)


class GetAllocationPolicyVersion:
    """Read one immutable allocation-policy version by stable identity."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, policy_key: str, version: int) -> AllocationPolicyVersion:
        """Return the requested version or fail closed with a stable reason."""

        if not policy_key.strip():
            raise ValueError("policy_key is required")
        if isinstance(version, bool) or version <= 0:
            raise ValueError("version must be a positive integer")
        policy = self._repository.get_version(policy_key, version)
        if policy is None:
            raise AllocationPolicyUnavailableError(
                f"allocation_policy_version_missing:{policy_key}:v{version}"
            )
        if policy.status is AllocationPolicyStatus.ACTIVE:
            policy.validate_for_activation()
        return policy


class CreateAllocationPolicyVersion:
    """Create an immutable inactive allocation-policy version."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, draft: AllocationPolicyDraft) -> AllocationPolicyVersion:
        """Persist the next version without implicitly activating it."""

        return self._repository.create_version(draft)


class ActivateAllocationPolicyVersion:
    """Activate a complete version through the repository transaction boundary."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, request: ActivateAllocationPolicyRequest) -> AllocationPolicyVersion:
        """Activate the requested version and return the stored active revision."""

        return self._repository.activate_version(
            request.policy_key,
            request.version,
            activated_by_id=request.actor_id,
            effective_at=request.effective_at,
        )


class RollbackAllocationPolicyVersion:
    """Rollback by creating a new version rather than mutating historical content."""

    def __init__(self, repository: AllocationPolicyRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, request: RollbackAllocationPolicyRequest) -> AllocationPolicyVersion:
        """Copy the selected historical content into a newly active revision."""

        return self._repository.rollback_to_version(
            request.policy_key,
            request.version,
            change_reason=request.change_reason,
            actor_id=request.actor_id,
            effective_at=request.effective_at,
        )


def get_active_allocation_policy(
    policy_key: str = DEFAULT_ALLOCATION_POLICY_KEY,
) -> AllocationPolicyVersion:
    """Return the active policy through the default application composition."""

    from apps.strategy.application.repository_provider import (
        get_allocation_policy_repository,
    )

    return GetActiveAllocationPolicy(get_allocation_policy_repository()).execute(policy_key)


def list_allocation_policy_versions(
    policy_key: str = DEFAULT_ALLOCATION_POLICY_KEY,
) -> list[AllocationPolicyVersion]:
    """List policy versions through the default application composition."""

    from apps.strategy.application.repository_provider import (
        get_allocation_policy_repository,
    )

    return ListAllocationPolicyVersions(get_allocation_policy_repository()).execute(policy_key)


def get_allocation_policy_version(
    version: int,
    policy_key: str = DEFAULT_ALLOCATION_POLICY_KEY,
) -> AllocationPolicyVersion:
    """Return one policy version through the default application composition."""

    from apps.strategy.application.repository_provider import (
        get_allocation_policy_repository,
    )

    return GetAllocationPolicyVersion(get_allocation_policy_repository()).execute(
        policy_key,
        version,
    )


def get_allocation_target(
    regime: str,
    risk_profile: str,
    policy_level: str | None = None,
    *,
    policy_key: str = DEFAULT_ALLOCATION_POLICY_KEY,
    repository: AllocationPolicyRepositoryProtocol | None = None,
) -> AllocationTarget:
    """Compatibility facade backed only by the active database policy version."""

    if repository is None:
        from apps.strategy.application.repository_provider import (
            get_allocation_policy_repository,
        )

        repository = get_allocation_policy_repository()
    active = GetActiveAllocationPolicy(repository).execute(policy_key)
    return resolve_allocation_target(active, regime, risk_profile, policy_level)
