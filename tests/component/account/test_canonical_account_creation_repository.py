"""Closed-world behavior of the canonical Account creation repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from django.db import connection

from apps.account.application.canonical_account_creation import (
    CanonicalAccountCreationConflict,
    CanonicalAccountCreationCorruption,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
)
from tests.unit.account.test_canonical_account_creation import _allocation, _binding


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _at(30)


def _repository() -> DjangoCanonicalAccountCreationRepository:
    return DjangoCanonicalAccountCreationRepository(clock=_Clock())


def _append_allocation() -> CanonicalAccountCreationAllocation:
    value = _allocation()
    repository = _repository()
    with repository.atomic():
        return repository.append_allocation(value, recorded_at=value.allocated_at)


def _append_binding() -> tuple[CanonicalAccountCreationAllocation, CanonicalAccountCreationBinding]:
    allocation = _allocation()
    binding = _binding(allocation=allocation)
    repository = _repository()
    with repository.atomic():
        persisted_allocation = repository.append_allocation(
            allocation, recorded_at=allocation.allocated_at
        )
        persisted_binding = repository.append_binding(
            binding,
            expected_allocation_content_hash=allocation.content_hash,
            expected_account_claim_hash=binding.account_claim_hash,
            expected_underlying_claim_hash=binding.underlying_claim_hash,
            expected_physical_content_hash=binding.physical_observation.content_hash,
            recorded_at=binding.recorded_at,
        )
    return persisted_allocation, persisted_binding


@pytest.mark.django_db(transaction=True)
def test_allocation_roundtrip_request_exact_and_pit() -> None:
    allocation = _allocation()
    repository = _repository()
    with repository.atomic():
        assert (
            repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
            == allocation
        )
        assert (
            repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
            == allocation
        )

    assert (
        repository.get_allocation_winner(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            as_of=_at(1),
        )
        == allocation
    )
    assert (
        repository.get_allocation_winner(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            as_of=datetime(2026, 8, 1, 11, tzinfo=UTC),
        )
        is None
    )
    assert (
        repository.get_allocation_by_request(
            requester_actor_id=allocation.requested_by.actor_id,
            requester_user_id=allocation.requested_by.user_id,
            request_fingerprint_hash=allocation.request_fingerprint_hash,
            as_of=_at(2),
        )
        == allocation
    )
    assert (
        repository.get_exact_allocation(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_content_hash=allocation.content_hash,
            as_of=_at(2),
        )
        == allocation
    )


@pytest.mark.django_db(transaction=True)
def test_binding_consumes_allocation_without_expiry_fallback_and_all_anchors_find_it() -> None:
    allocation = _allocation()
    binding = _binding(allocation=allocation)
    repository = _repository()
    with repository.atomic():
        repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
    assert (
        repository.get_current_unconsumed_allocation(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_content_hash=allocation.content_hash,
            as_of=_at(2),
        )
        == allocation
    )
    assert (
        repository.get_current_unconsumed_allocation(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_content_hash=allocation.content_hash,
            as_of=_at(20),
        )
        is None
    )
    with repository.atomic():
        assert (
            repository.append_binding(
                binding,
                expected_allocation_content_hash=allocation.content_hash,
                expected_account_claim_hash=binding.account_claim_hash,
                expected_underlying_claim_hash=binding.underlying_claim_hash,
                expected_physical_content_hash=binding.physical_observation.content_hash,
                recorded_at=binding.recorded_at,
            )
            == binding
        )
    assert (
        repository.get_current_unconsumed_allocation(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            expected_content_hash=allocation.content_hash,
            as_of=_at(8),
        )
        is None
    )
    assert (
        repository.get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=_at(6),
        )
        is None
    )
    assert (
        repository.get_exact_binding(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=_at(8),
        )
        == binding
    )

    selectors = [
        (allocation.content_hash, "none", "none", "none", 999, "0" * 64),
        (
            "0" * 64,
            binding.account_namespace_claim,
            binding.account_id_claim,
            "none",
            999,
            "0" * 64,
        ),
        (
            "0" * 64,
            "none",
            "none",
            binding.underlying_unified_account_namespace_claim,
            binding.underlying_unified_account_id_claim,
            "0" * 64,
        ),
        ("0" * 64, "none", "none", "none", 999, binding.physical_observation.content_hash),
    ]
    for (
        allocation_hash,
        account_ns,
        account_id,
        underlying_ns,
        underlying_id,
        physical_hash,
    ) in selectors:
        assert (
            repository.get_binding_by_any_anchor(
                allocation_content_hash=allocation_hash,
                account_namespace=account_ns,
                account_id=account_id,
                underlying_unified_account_namespace=underlying_ns,
                underlying_unified_account_id=underlying_id,
                physical_content_hash=physical_hash,
                as_of=_at(8),
            )
            == binding
        )


@pytest.mark.django_db(transaction=True)
def test_allocation_and_binding_anchor_first_winners_conflict() -> None:
    allocation = _allocation()
    repository = _repository()
    with repository.atomic():
        repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
        conflicting = replace(
            allocation,
            allocation_id="allocation-other",
            allocation_version="v2",
            identity_hash="",
            content_hash="",
        )
        with pytest.raises(CanonicalAccountCreationConflict, match="anchor"):
            repository.append_allocation(conflicting, recorded_at=conflicting.allocated_at)

    binding = _binding(allocation=allocation)
    with repository.atomic():
        repository.append_binding(
            binding,
            expected_allocation_content_hash=allocation.content_hash,
            expected_account_claim_hash=binding.account_claim_hash,
            expected_underlying_claim_hash=binding.underlying_claim_hash,
            expected_physical_content_hash=binding.physical_observation.content_hash,
            recorded_at=binding.recorded_at,
        )
        conflicting_binding = replace(
            binding,
            binding_id="binding-other",
            binding_version="v2",
            identity_hash="",
            content_hash="",
        )
        with pytest.raises(CanonicalAccountCreationConflict, match="anchor"):
            repository.append_binding(
                conflicting_binding,
                expected_allocation_content_hash=allocation.content_hash,
                expected_account_claim_hash=conflicting_binding.account_claim_hash,
                expected_underlying_claim_hash=conflicting_binding.underlying_claim_hash,
                expected_physical_content_hash=(
                    conflicting_binding.physical_observation.content_hash
                ),
                recorded_at=conflicting_binding.recorded_at,
            )


@pytest.mark.django_db(transaction=True)
def test_closed_world_detects_header_and_canonical_payload_tampering() -> None:
    allocation = _allocation()
    _append_allocation()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE canonical_account_creation_allocation_ledger SET allocation_id = %s",
            ["tampered"],
        )
    with pytest.raises(CanonicalAccountCreationCorruption, match="ledger mismatch"):
        _repository().get_allocation_winner(
            allocation_id=allocation.allocation_id,
            allocation_version=allocation.allocation_version,
            as_of=_at(2),
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_detects_nested_binding_payload_tampering() -> None:
    _, binding = _append_binding()
    assert hasattr(binding, "content_hash")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE canonical_account_creation_binding_ledger SET canonical_payload = %s",
            ['{"tampered":true}'],
        )
    with pytest.raises(CanonicalAccountCreationCorruption, match="payload corrupt"):
        _repository().get_binding_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=_at(8),
        )


@pytest.mark.django_db(transaction=True)
def test_repository_transaction_rolls_back_both_tables() -> None:
    allocation = _allocation()
    binding = _binding(allocation=allocation)
    repository = _repository()
    with pytest.raises(RuntimeError, match="rollback"):
        with repository.atomic():
            repository.append_allocation(allocation, recorded_at=allocation.allocated_at)
            repository.append_binding(
                binding,
                expected_allocation_content_hash=allocation.content_hash,
                expected_account_claim_hash=binding.account_claim_hash,
                expected_underlying_claim_hash=binding.underlying_claim_hash,
                expected_physical_content_hash=binding.physical_observation.content_hash,
                recorded_at=binding.recorded_at,
            )
            raise RuntimeError("rollback")
    assert CanonicalAccountCreationAllocationModel.objects.count() == 0
    assert CanonicalAccountCreationBindingModel.objects.count() == 0
