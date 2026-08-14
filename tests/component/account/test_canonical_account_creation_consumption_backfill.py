"""Component coverage for the strict Binding-v1 consumption-claim backfill."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import connection

from apps.account.application.canonical_account_creation import CanonicalAccountCreationConflict
from apps.account.infrastructure.canonical_account_creation_consumption_backfill import (
    DjangoCanonicalAccountCreationConsumptionBackfill,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_maintenance_lock import (
    CanonicalAccountCreationMaintenanceLockUnavailable,
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


class _AllowWrite:
    def verify(self, *, using: str, knowledge_at: object) -> None:
        assert using == "default"
        assert knowledge_at is not None


def _backfill(
    *, allow_sqlite_test_degradation: bool = False
) -> DjangoCanonicalAccountCreationConsumptionBackfill:
    return DjangoCanonicalAccountCreationConsumptionBackfill(
        preflight=_AllowPreflight(),
        allow_sqlite_test_degradation=allow_sqlite_test_degradation,
        write_authorization=_AllowWrite(),
    )


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
    assert dry.blocker_codes == ("production_postgresql_maintenance_lock_required",)
    assert (
        row.canonical_payload,
        row.content_hash,
        row.record_seal,
        row.ledger_seal,
    ) == immutable_before


@pytest.mark.django_db(transaction=True)
def test_backfill_write_rejects_sqlite_without_explicit_test_degradation() -> None:
    row = _seed_legacy_binding()
    with pytest.raises(CanonicalAccountCreationMaintenanceLockUnavailable, match="PostgreSQL"):
        _backfill().run(dry_run=False)
    row.refresh_from_db()
    assert row.consumption_claim_id is None


@pytest.mark.django_db(transaction=True)
def test_backfill_write_requires_explicit_authorization() -> None:
    _seed_legacy_binding()
    service = DjangoCanonicalAccountCreationConsumptionBackfill(
        preflight=_AllowPreflight(),
        allow_sqlite_test_degradation=True,
    )
    with pytest.raises(CanonicalAccountCreationConflict, match="authorization_unavailable"):
        service.run(dry_run=False)


@pytest.mark.django_db(transaction=True)
def test_backfill_links_legacy_claim_with_real_knowledge_clock_and_preserves_bytes() -> None:
    row = _seed_legacy_binding()
    immutable_before = (row.canonical_payload, row.content_hash, row.record_seal, row.ledger_seal)
    service = _backfill(allow_sqlite_test_degradation=True)

    report = service.run(dry_run=False)

    row.refresh_from_db()
    claim_row = CanonicalAccountCreationConsumptionClaimModel.objects.get()
    assert (report.created, report.legacy_linked, report.knowledge_updated) == (1, 1, 0)
    assert row.consumption_claim_id == claim_row.pk
    assert claim_row.knowledge_at is not None
    assert claim_row.knowledge_at >= claim_row.recorded_at
    assert (row.canonical_payload, row.content_hash, row.record_seal, row.ledger_seal) == (
        immutable_before
    )
    repository = DjangoCanonicalAccountCreationRepository()
    winner = repository.get_binding_winner(
        binding_id=row.binding_id,
        binding_version=row.binding_version,
        as_of=claim_row.knowledge_at,
    )
    assert winner is not None
    assert winner.binding.content_hash == row.content_hash
    assert winner.claim.content_hash == claim_row.content_hash


@pytest.mark.django_db(transaction=True)
def test_backfill_updates_existing_null_knowledge_and_is_idempotent() -> None:
    _seed_legacy_binding()
    service = _backfill(allow_sqlite_test_degradation=True)
    service.run(dry_run=False)
    table = connection.ops.quote_name(CanonicalAccountCreationConsumptionClaimModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {table} SET knowledge_at = NULL")  # noqa: S608

    repaired = service.run(dry_run=False)
    replay = service.run(dry_run=False)

    assert (repaired.knowledge_updated, repaired.created, repaired.legacy_linked) == (1, 0, 0)
    assert (replay.knowledge_updated, replay.created, replay.legacy_linked) == (0, 0, 0)
    assert CanonicalAccountCreationConsumptionClaimModel.objects.get().knowledge_at is not None


@pytest.mark.django_db(transaction=True)
def test_backfill_lost_binding_cas_rolls_back_claim_and_knowledge() -> None:
    row = _seed_legacy_binding()
    with patch(
        "apps.account.infrastructure.canonical_account_creation_consumption_backfill."
        "_compare_and_set_canonical_account_creation_binding_claim",
        return_value=0,
    ):
        with pytest.raises(CanonicalAccountCreationConflict, match="compare-and-swap lost"):
            _backfill(allow_sqlite_test_degradation=True).run(dry_run=False)

    row.refresh_from_db()
    assert row.consumption_claim_id is None
    assert CanonicalAccountCreationConsumptionClaimModel.objects.count() == 0


def test_backfill_rejects_implicit_alias_and_bool_substitution() -> None:
    with pytest.raises(ValueError, match="using"):
        DjangoCanonicalAccountCreationConsumptionBackfill(using=" default ")
    with pytest.raises(TypeError, match="exact bool"):
        _backfill().run(dry_run=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact bool"):
        DjangoCanonicalAccountCreationConsumptionBackfill(
            allow_sqlite_test_degradation=1  # type: ignore[arg-type]
        )
