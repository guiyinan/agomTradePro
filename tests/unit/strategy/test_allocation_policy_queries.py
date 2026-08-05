"""Unit contracts for allocation-policy query use cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.strategy.application.allocation_policy import (
    GetAllocationPolicyVersion,
    ListAllocationPolicyVersions,
)
from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyConfigurationError,
    AllocationPolicyDraft,
    AllocationPolicyEntry,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
    AllocationPolicyUnavailableError,
    AllocationPolicyVersion,
    AllocationStatisticsStatus,
    AllocationTarget,
    AssetAllocation,
    PolicyAllocationAdjustment,
    PolicyLevel,
    RegimeType,
    RiskProfile,
    calculate_allocation_policy_content_hash,
)


class FakeAllocationPolicyRepository:
    """Minimal in-memory repository for Application query tests."""

    def __init__(self, versions: list[AllocationPolicyVersion]) -> None:
        self.versions = versions

    def get_active(self, policy_key: str) -> AllocationPolicyVersion | None:
        """Return the active matching version, if present."""

        return next(
            (
                policy
                for policy in self.versions
                if policy.policy_key == policy_key
                and policy.status is AllocationPolicyStatus.ACTIVE
            ),
            None,
        )

    def get_version(
        self,
        policy_key: str,
        version: int,
    ) -> AllocationPolicyVersion | None:
        """Return one matching version."""

        return next(
            (
                policy
                for policy in self.versions
                if policy.policy_key == policy_key and policy.version == version
            ),
            None,
        )

    def list_versions(self, policy_key: str) -> list[AllocationPolicyVersion]:
        """Return matching versions newest first."""

        return sorted(
            (policy for policy in self.versions if policy.policy_key == policy_key),
            key=lambda policy: policy.version,
            reverse=True,
        )

    def create_version(self, draft: AllocationPolicyDraft) -> AllocationPolicyVersion:
        """Reject mutations in this read-only fake."""

        raise AssertionError(f"unexpected create for {draft.policy_key}")

    def activate_version(
        self,
        policy_key: str,
        version: int,
        *,
        activated_by_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Reject mutations in this read-only fake."""

        raise AssertionError(
            f"unexpected activation for {policy_key} v{version} by {activated_by_id} at {effective_at}"
        )

    def rollback_to_version(
        self,
        policy_key: str,
        version: int,
        *,
        change_reason: str,
        actor_id: int | None,
        effective_at: datetime | None = None,
    ) -> AllocationPolicyVersion:
        """Reject mutations in this read-only fake."""

        raise AssertionError(
            f"unexpected rollback for {policy_key} v{version}: {change_reason}; "
            f"actor={actor_id}; effective_at={effective_at}"
        )


def test_query_use_cases_list_and_read_repository_versions() -> None:
    """Queries preserve repository ordering and immutable version identity."""

    first = _policy(version=1, status=AllocationPolicyStatus.SUPERSEDED)
    second = _policy(version=2, status=AllocationPolicyStatus.ACTIVE)
    repository = FakeAllocationPolicyRepository([first, second])

    versions = ListAllocationPolicyVersions(repository).execute(first.policy_key)
    selected = GetAllocationPolicyVersion(repository).execute(first.policy_key, 1)

    assert [policy.version for policy in versions] == [2, 1]
    assert selected is first


def test_get_policy_version_fails_closed_for_missing_or_invalid_identity() -> None:
    """Missing versions never fall back to the active policy or static content."""

    repository = FakeAllocationPolicyRepository([])
    query = GetAllocationPolicyVersion(repository)

    with pytest.raises(
        AllocationPolicyUnavailableError,
        match="allocation_policy_version_missing:strategic_asset_allocation:v9",
    ):
        query.execute("strategic_asset_allocation", 9)
    with pytest.raises(ValueError, match="positive integer"):
        query.execute("strategic_asset_allocation", 0)


def test_get_active_status_version_revalidates_completeness() -> None:
    """An active status flag cannot make incomplete content decision-usable."""

    incomplete_active = _policy(version=2, status=AllocationPolicyStatus.ACTIVE)
    repository = FakeAllocationPolicyRepository([incomplete_active])

    with pytest.raises(
        AllocationPolicyConfigurationError,
        match="allocation policy matrix is incomplete",
    ):
        GetAllocationPolicyVersion(repository).execute(incomplete_active.policy_key, 2)


def _policy(
    *,
    version: int,
    status: AllocationPolicyStatus,
) -> AllocationPolicyVersion:
    """Build a compact, hash-valid policy version for query tests."""

    entries = (
        AllocationPolicyEntry(
            regime=RegimeType.RECOVERY,
            risk_profile=RiskProfile.MODERATE,
            target=AllocationTarget(
                allocation=AssetAllocation(
                    equity=0.5,
                    fixed_income=0.3,
                    commodity=0.1,
                    cash=0.1,
                ),
                reasoning="query fixture",
                statistics_status=AllocationStatisticsStatus.NOT_PROVIDED,
            ),
        ),
    )
    adjustments = (
        PolicyAllocationAdjustment(
            policy_level=PolicyLevel.P0,
            equity_multiplier=1.0,
        ),
    )
    return AllocationPolicyVersion(
        policy_key="strategic_asset_allocation",
        version=version,
        status=status,
        entries=entries,
        adjustments=adjustments,
        content_hash=calculate_allocation_policy_content_hash(entries, adjustments),
        source_type=AllocationPolicySourceType.HUMAN,
        change_reason="query fixture",
        created_at=datetime(2026, 8, 5, tzinfo=UTC),
        effective_at=(
            datetime(2026, 8, 5, tzinfo=UTC) if status is AllocationPolicyStatus.ACTIVE else None
        ),
    )
