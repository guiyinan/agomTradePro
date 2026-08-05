"""Data-migration contracts for the legacy Strategy allocation policy."""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.strategy.domain.allocation_matrix import AllocationStatisticsStatus
from apps.strategy.infrastructure.allocation_policy_repository import (
    DjangoAllocationPolicyRepository,
)
from apps.strategy.infrastructure.models import (
    AllocationPolicyAdjustmentModel,
    AllocationPolicyEntryModel,
    AllocationPolicyVersionModel,
)


@pytest.mark.django_db
def test_legacy_allocation_policy_seed_is_idempotent_and_explicitly_unverified() -> None:
    AllocationPolicyVersionModel._default_manager.all().delete()
    migration = importlib.import_module(
        "apps.strategy.migrations.0013_seed_legacy_allocation_policy"
    )
    state_apps = (
        MigrationExecutor(connection)
        .loader.project_state([("strategy", "0013_seed_legacy_allocation_policy")])
        .apps
    )

    migration.seed_legacy_allocation_policy(state_apps, None)
    migration.seed_legacy_allocation_policy(state_apps, None)

    assert (
        AllocationPolicyVersionModel._default_manager.filter(
            policy_key=migration.POLICY_KEY,
            version=1,
        ).count()
        == 1
    )
    assert (
        AllocationPolicyEntryModel._default_manager.filter(
            policy_version__policy_key=migration.POLICY_KEY
        ).count()
        == 16
    )
    assert (
        AllocationPolicyAdjustmentModel._default_manager.filter(
            policy_version__policy_key=migration.POLICY_KEY
        ).count()
        == 4
    )
    assert set(
        AllocationPolicyEntryModel._default_manager.filter(
            policy_version__policy_key=migration.POLICY_KEY
        ).values_list("statistics_status", flat=True)
    ) == {"legacy_unverified"}

    active = DjangoAllocationPolicyRepository().get_active(migration.POLICY_KEY)
    assert active is not None
    assert {entry.target.statistics_status for entry in active.entries} == {
        AllocationStatisticsStatus.LEGACY_UNVERIFIED
    }
