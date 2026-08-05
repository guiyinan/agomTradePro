"""Version, activation, rollback, and fail-closed allocation-policy contracts."""

from __future__ import annotations

from dataclasses import replace

import pytest
from django.core.exceptions import ValidationError

from apps.strategy.application.allocation_policy import get_allocation_target
from apps.strategy.domain.allocation_matrix import (
    AllocationPolicyConfigurationError,
    AllocationPolicyDraft,
    AllocationPolicyEntry,
    AllocationPolicySourceType,
    AllocationPolicyStatus,
    AllocationPolicyUnavailableError,
    AllocationStatisticsStatus,
    AllocationTarget,
    AssetAllocation,
    PolicyAllocationAdjustment,
    PolicyLevel,
    RegimeType,
    RiskProfile,
)
from apps.strategy.infrastructure.allocation_policy_repository import (
    DjangoAllocationPolicyRepository,
)
from apps.strategy.infrastructure.models import (
    AllocationPolicyEntryModel,
    AllocationPolicyVersionModel,
)

pytestmark = pytest.mark.django_db


def _draft(
    *,
    equity: float,
    fixed_income: float,
    policy_key: str = "test_allocation_policy",
    change_reason: str = "test version",
) -> AllocationPolicyDraft:
    entries = tuple(
        AllocationPolicyEntry(
            regime=regime,
            risk_profile=risk_profile,
            target=AllocationTarget(
                allocation=AssetAllocation(
                    equity=equity,
                    fixed_income=fixed_income,
                    commodity=0.1,
                    cash=1.0 - equity - fixed_income - 0.1,
                ),
                reasoning=f"dynamic {equity:.2f}",
                expected_return=0.08,
                expected_volatility=0.12,
                sharpe_ratio=0.5,
                statistics_status=AllocationStatisticsStatus.HUMAN_ASSUMPTION,
            ),
        )
        for regime in RegimeType
        for risk_profile in RiskProfile
    )
    adjustments = tuple(
        PolicyAllocationAdjustment(
            policy_level=level,
            equity_multiplier=0.5 if level is PolicyLevel.P1 else 1.0,
            expected_return_multiplier=0.75 if level is PolicyLevel.P1 else 1.0,
            expected_volatility_multiplier=0.8 if level is PolicyLevel.P1 else 1.0,
            sharpe_multiplier=0.9 if level is PolicyLevel.P1 else 1.0,
        )
        for level in PolicyLevel
    )
    return AllocationPolicyDraft(
        policy_key=policy_key,
        entries=entries,
        adjustments=adjustments,
        source_type=AllocationPolicySourceType.HUMAN,
        change_reason=change_reason,
    )


def _empty_repository() -> DjangoAllocationPolicyRepository:
    AllocationPolicyVersionModel._default_manager.all().delete()
    return DjangoAllocationPolicyRepository()


def test_active_policy_switches_runtime_to_dynamic_version() -> None:
    repository = _empty_repository()
    first = repository.create_version(_draft(equity=0.4, fixed_income=0.3))
    repository.activate_version(first.policy_key, first.version, activated_by_id=None)

    initial_target = get_allocation_target(
        "Recovery",
        "moderate",
        "P1",
        policy_key=first.policy_key,
        repository=repository,
    )
    assert initial_target.allocation.equity == pytest.approx(0.2)
    assert initial_target.allocation_policy_version == 1

    second = repository.create_version(_draft(equity=0.6, fixed_income=0.2))
    active = repository.activate_version(
        second.policy_key,
        second.version,
        activated_by_id=None,
    )
    changed_target = get_allocation_target(
        "Recovery",
        "moderate",
        "P1",
        policy_key=second.policy_key,
        repository=repository,
    )

    assert active.version == 2
    assert changed_target.allocation.equity == pytest.approx(0.3)
    assert changed_target.expected_return == pytest.approx(0.06)
    assert changed_target.statistics_status is AllocationStatisticsStatus.HUMAN_ASSUMPTION
    assert changed_target.must_not_use_statistics_as_model_estimate is True
    assert AllocationPolicyVersionModel._default_manager.get(version=1).status == "superseded"


def test_rollback_creates_new_version_and_historical_content_is_immutable() -> None:
    repository = _empty_repository()
    first = repository.create_version(_draft(equity=0.4, fixed_income=0.3))
    repository.activate_version(first.policy_key, first.version, activated_by_id=None)
    second = repository.create_version(_draft(equity=0.6, fixed_income=0.2))
    repository.activate_version(second.policy_key, second.version, activated_by_id=None)

    rolled_back = repository.rollback_to_version(
        first.policy_key,
        first.version,
        change_reason="restore approved allocation",
        actor_id=None,
    )

    assert rolled_back.version == 3
    assert rolled_back.status is AllocationPolicyStatus.ACTIVE
    assert rolled_back.based_on_version == first.version
    assert rolled_back.content_hash == first.content_hash
    assert rolled_back.source_type is AllocationPolicySourceType.ROLLBACK
    historical = repository.get_version(first.policy_key, first.version)
    assert historical is not None
    assert historical.status is AllocationPolicyStatus.SUPERSEDED
    assert historical.content_hash == first.content_hash
    assert historical.entries == first.entries

    stored_first = AllocationPolicyVersionModel._default_manager.get(
        policy_key=first.policy_key,
        version=first.version,
    )
    stored_first.change_reason = "forbidden edit"
    with pytest.raises(ValidationError, match="immutable"):
        stored_first.save()

    stored_entry = AllocationPolicyEntryModel._default_manager.filter(
        policy_version=stored_first
    ).first()
    assert stored_entry is not None
    stored_entry.reasoning = "forbidden edit"
    with pytest.raises(ValidationError, match="immutable"):
        stored_entry.save()


def test_incomplete_version_cannot_be_activated() -> None:
    repository = _empty_repository()
    full_draft = _draft(equity=0.4, fixed_income=0.3)
    incomplete = replace(full_draft, entries=full_draft.entries[:1])
    created = repository.create_version(incomplete)

    with pytest.raises(AllocationPolicyConfigurationError, match="incomplete"):
        repository.activate_version(created.policy_key, created.version, activated_by_id=None)

    assert repository.get_active(created.policy_key) is None
    assert (
        repository.get_version(created.policy_key, created.version).status
        is AllocationPolicyStatus.DRAFT
    )


def test_missing_active_policy_fails_closed_without_static_matrix_fallback() -> None:
    repository = _empty_repository()

    with pytest.raises(
        AllocationPolicyUnavailableError,
        match="active_allocation_policy_missing",
    ):
        get_allocation_target(
            "Recovery",
            "moderate",
            "P0",
            policy_key="missing_policy",
            repository=repository,
        )
