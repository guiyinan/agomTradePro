"""Component coverage for the strict Binding-v1 consumption-claim backfill."""

from __future__ import annotations

import pytest

from apps.account.application.canonical_account_creation import (
    CanonicalAccountCreationConflict,
)
from apps.account.infrastructure.canonical_account_creation_consumption_backfill import (
    DjangoCanonicalAccountCreationConsumptionBackfill,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
    _binding_values,
)
from tests.unit.account.test_canonical_account_creation import _allocation, _binding


class _AllowPreflight:
    def verify(self, *, using: str) -> None:
        assert using == "default"


def _backfill() -> DjangoCanonicalAccountCreationConsumptionBackfill:
    return DjangoCanonicalAccountCreationConsumptionBackfill(preflight=_AllowPreflight())


def _seed_legacy_binding() -> CanonicalAccountCreationBindingModel:
    allocation = _allocation()
    binding = _binding(allocation=allocation)
    repository = DjangoCanonicalAccountCreationRepository()
    with repository.atomic():
        repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
        world = repository._closed_consumption_world(lock=True)
        allocation_row = world.allocations[0][0]
        repository._insert(
            CanonicalAccountCreationBindingModel,
            _binding_values(
                binding,
                allocation_pk=allocation_row.pk,
                consumption_claim_pk=None,
            ),
        )
    return CanonicalAccountCreationBindingModel.objects.get()


@pytest.mark.django_db(transaction=True)
def test_backfill_defaults_to_stable_dry_run_without_mutating_legacy_bytes() -> None:
    row = _seed_legacy_binding()
    immutable_before = (row.canonical_payload, row.content_hash, row.record_seal, row.ledger_seal)
    backfill = _backfill()

    dry = backfill.run()
    assert (dry.dry_run, dry.scanned, dry.eligible, dry.created) == (True, 1, 1, 0)
    row.refresh_from_db()
    assert row.consumption_claim_id is None
    assert dry.write_enabled is False
    assert dry.blocker_codes == ("consumption_claim_backfill_provenance_clock_not_integrated",)
    assert (
        row.canonical_payload,
        row.content_hash,
        row.record_seal,
        row.ledger_seal,
    ) == immutable_before


@pytest.mark.django_db(transaction=True)
def test_backfill_write_is_blocked_before_preflight_or_database_mutation() -> None:
    row = _seed_legacy_binding()
    with pytest.raises(CanonicalAccountCreationConflict, match="provenance_clock"):
        _backfill().run(dry_run=False)
    row.refresh_from_db()
    assert row.consumption_claim_id is None


def test_backfill_rejects_implicit_alias_and_bool_substitution() -> None:
    with pytest.raises(ValueError, match="using"):
        DjangoCanonicalAccountCreationConsumptionBackfill(using=" default ")
    with pytest.raises(TypeError, match="exact bool"):
        _backfill().run(dry_run=1)  # type: ignore[arg-type]
