"""SQLite component evidence for the Research R2 trial-policy registry."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector

from apps.research.application.r2_market_structure_trial_policy_registry import (
    R2TrialPolicyRegistryConflict,
    R2TrialPolicyRegistryCorruption,
    R2TrialPolicyRegistryUnavailable,
    RegisterR2MarketStructureTrialPolicyCommand,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MarketStructureTrialPolicy,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_models import (
    R2MarketStructureTrialPolicyLedgerModel,
)
from apps.research.infrastructure.r2_market_structure_trial_policy_repository import (
    _record_values,
)
from apps.research.r2_market_structure_trial_policy_composition import (
    _build_django_r2_trial_policy_registry_test_runtime,
    _DjangoR2TrialPolicyRegistryTestRuntime,
    build_django_r2_trial_policy_registry_runtime,
)
from tests.unit.research.r2_market_structure_trial_monitoring_factories import (
    NOW,
    build_r2_scenario,
)

LEDGER_TIME = NOW - timedelta(days=30, hours=12)
CUTOFF = NOW - timedelta(days=30, hours=18)

pytestmark = pytest.mark.django_db(transaction=True)


class _Clock:
    def __init__(self, value: datetime = LEDGER_TIME) -> None:
        self.value = value

    @property
    def unit_of_work_key(self) -> str:
        return "django:default"

    def now(self) -> datetime:
        return self.value


class _Owner:
    unit_of_work_key = "django:default"

    def __init__(self, policy: R2MarketStructureTrialPolicy) -> None:
        self.policy = policy
        self.calls: list[datetime] = []
        self.replacement: R2MarketStructureTrialPolicy | None = None

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        self.calls.append(as_of)
        selected = (
            self.replacement
            if len(self.calls) == 2 and self.replacement is not None
            else self.policy
        )
        if (selected.policy_id, selected.policy_version) != (
            policy_id,
            policy_version,
        ):
            return None
        return selected


def _command(
    policy: R2MarketStructureTrialPolicy,
) -> RegisterR2MarketStructureTrialPolicyCommand:
    return RegisterR2MarketStructureTrialPolicyCommand(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        as_of=CUTOFF,
    )


def _runtime(
    policy: R2MarketStructureTrialPolicy | None = None,
    *,
    owner: _Owner | None = None,
    clock: _Clock | None = None,
) -> _DjangoR2TrialPolicyRegistryTestRuntime:
    selected = policy or build_r2_scenario().policy
    return _build_django_r2_trial_policy_registry_test_runtime(
        definition_provider=owner or _Owner(selected),
        clock=clock or _Clock(),
    )


def test_private_runtime_roundtrip_exact_pit_and_existing_r2_provider() -> None:
    policy = build_r2_scenario().policy
    owner = _Owner(policy)
    clock = _Clock()
    runtime = _runtime(owner=owner, clock=clock)

    record = runtime.register.execute(_command(policy))
    clock.value = policy.selection_as_of + timedelta(seconds=1)

    assert owner.calls == [CUTOFF, LEDGER_TIME]
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 1
    assert (
        runtime.repository.get_record_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            as_of=policy.selection_as_of,
        )
        == record
    )
    assert (
        runtime.provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            as_of=policy.selection_as_of,
        )
        == policy
    )
    assert (
        runtime.repository.get_record_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            as_of=LEDGER_TIME - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        runtime.provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash="f" * 64,
            as_of=policy.selection_as_of,
        )
        is None
    )


def test_identical_winner_version_fork_and_conflicting_fork_are_exact() -> None:
    policy = build_r2_scenario().policy
    runtime = _runtime(policy)
    first = runtime.register.execute(_command(policy))
    assert runtime.register.execute(_command(policy)) == first
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 1

    policy_v2 = replace(policy, policy_version="v2")
    second = _runtime(policy_v2).register.execute(_command(policy_v2))
    assert second.policy.policy_version == "v2"
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 2

    changed_v1 = replace(policy, expected_label_set_hash="f" * 64)
    with pytest.raises(R2TrialPolicyRegistryConflict):
        _runtime(changed_v1).register.execute(_command(changed_v1))
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 2


def test_owner_replacement_and_outer_rollback_leave_zero_rows() -> None:
    policy = build_r2_scenario().policy
    owner = _Owner(policy)
    owner.replacement = replace(policy, expected_label_set_hash="f" * 64)
    with pytest.raises(R2TrialPolicyRegistryUnavailable, match="changed"):
        _runtime(owner=owner).register.execute(_command(policy))
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 0

    class _Rollback(Exception):
        pass

    with pytest.raises(_Rollback), transaction.atomic():
        _runtime(policy).register.execute(_command(policy))
        raise _Rollback
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 0


def test_public_runtime_is_inert_and_empty_db_means_r2_blocked() -> None:
    policy = build_r2_scenario().policy
    runtime = build_django_r2_trial_policy_registry_runtime()

    assert runtime.provider.__slots__ == ("_repository",)
    assert not hasattr(runtime.provider, "append")
    assert (
        runtime.provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            as_of=policy.selection_as_of,
        )
        is None
    )
    with pytest.raises(R2TrialPolicyRegistryUnavailable, match="provider"):
        runtime.register.execute(_command(policy))
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 0


def test_orm_queryset_bulk_and_collector_mutation_guards() -> None:
    policy = build_r2_scenario().policy
    record = _runtime(policy).register.execute(_command(policy))
    row = R2MarketStructureTrialPolicyLedgerModel.objects.get()

    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(force_update=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R2MarketStructureTrialPolicyLedgerModel.objects.update(policy_version="fork")
    with pytest.raises(ValidationError):
        R2MarketStructureTrialPolicyLedgerModel.objects.all().delete()
    with pytest.raises(ValidationError):
        R2MarketStructureTrialPolicyLedgerModel.objects.bulk_create(
            [R2MarketStructureTrialPolicyLedgerModel(**_record_values(record))]
        )
    with pytest.raises(ValidationError, match="exact insert claim"):
        R2MarketStructureTrialPolicyLedgerModel.objects.create(**_record_values(record))
    collector = Collector(using="default")
    collector.collect([row])
    with pytest.raises(ValidationError):
        with transaction.atomic():
            collector.delete()
    assert R2MarketStructureTrialPolicyLedgerModel.objects.count() == 1


def test_header_tamper_is_detected_by_exact_reader() -> None:
    policy = build_r2_scenario().policy
    clock = _Clock()
    runtime = _runtime(policy, clock=clock)
    runtime.register.execute(_command(policy))
    clock.value = policy.selection_as_of + timedelta(seconds=1)
    table = R2MarketStructureTrialPolicyLedgerModel._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET taxonomy_publication_hash = %s ' "WHERE policy_id = %s",
            ["0" * 64, policy.policy_id],
        )

    with pytest.raises(R2TrialPolicyRegistryCorruption, match="header"):
        runtime.repository.get_record_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_content_hash=policy.content_hash,
            as_of=policy.selection_as_of,
        )
