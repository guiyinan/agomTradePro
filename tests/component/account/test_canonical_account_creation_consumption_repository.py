"""Closed-world component evidence for unified creation-consumption persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Recorder,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    PersistedCanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
)
from apps.account.infrastructure.allocated_physical_account_row_observation_v3_repository import (
    DjangoAllocatedPhysicalAccountRowObservationV3Repository,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
)
from apps.account.infrastructure.canonical_account_creation_consumption_repository import (
    DjangoCanonicalAccountCreationConsumptionRepository,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
    _claim_canonical_account_creation_insert,
)
from apps.account.infrastructure.canonical_account_creation_repository import (
    DjangoCanonicalAccountCreationRepository,
    _binding_values,
)
from tests.unit.account.test_canonical_account_creation import _allocation
from tests.unit.account.test_canonical_account_creation import _binding as _binding_v1
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding as _binding_v2
from tests.unit.account.test_canonical_account_creation_consumption import _claim


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return _at(30)


def _repository() -> DjangoCanonicalAccountCreationConsumptionRepository:
    return DjangoCanonicalAccountCreationConsumptionRepository(clock=_Clock())


def _seed_allocation(allocation: CanonicalAccountCreationAllocation) -> None:
    repository = DjangoCanonicalAccountCreationRepository(clock=_Clock())
    with repository.atomic():
        repository.append_allocation(allocation, recorded_at=allocation.allocated_at)


def _seed_v2_foreign_evidence(binding: CanonicalAccountCreationBindingV2) -> None:
    _seed_allocation(binding.allocation)
    root = binding.creation_root
    record = PersistedAllocatedPhysicalAccountRowObservationV3(
        observation=root,
        recorded_by=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id="creation-consumption-component"
        ),
    )
    repository = DjangoAllocatedPhysicalAccountRowObservationV3Repository(clock=_Clock())
    with repository.atomic():
        repository.append(
            record,
            expected_predecessor_hash=None,
            recorded_at=root.recorded_at,
        )


def _pair() -> tuple[
    CanonicalAccountCreationBindingV2,
    CanonicalAccountCreationConsumptionClaim,
]:
    binding = _binding_v2()
    claim = _claim(consumer_generation="v2", consumer=binding)
    return binding, claim


def _append_pair(
    repository: DjangoCanonicalAccountCreationConsumptionRepository,
    binding: CanonicalAccountCreationBindingV2,
    claim: CanonicalAccountCreationConsumptionClaim,
) -> tuple[CanonicalAccountCreationBindingV2, CanonicalAccountCreationConsumptionClaim]:
    return repository.append_with_consumption_claim(
        binding,
        claim,
        expected_allocation_content_hash=binding.allocation.content_hash,
        expected_account_claim_hash=binding.account_claim_hash,
        expected_underlying_claim_hash=binding.underlying_claim_hash,
        expected_creation_root_content_hash=binding.creation_root.content_hash,
        expected_consumption_claim_content_hash=claim.content_hash,
        recorded_at=binding.recorded_at,
    )


def _claim_selector(
    claim: CanonicalAccountCreationConsumptionClaim,
    **changes: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "claim_id": "absent-claim",
        "claim_version": "v9",
        "allocation_identity_hash": "0" * 64,
        "allocation_content_hash": "1" * 64,
        "consumer_identity_hash": "2" * 64,
        "consumer_content_hash": "3" * 64,
        "account_namespace": "absent-account",
        "account_id": "absent-id",
        "underlying_unified_account_namespace": "absent-row",
        "underlying_unified_account_id": 999,
        "physical_v2_content_hash": "4" * 64,
        "physical_v3_root_content_hash": "5" * 64,
        "as_of": _at(8),
    }
    values.update(changes)
    return values


@pytest.mark.django_db(transaction=True)
def test_v2_pair_roundtrip_first_winner_exact_pit_and_permanent_read() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)

    with repository.atomic():
        assert _append_pair(repository, binding, claim) == (binding, claim)
        assert _append_pair(repository, binding, claim) == (binding, claim)

    assert (
        repository.get_winner(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            as_of=_at(7),
        )
        is None
    )
    assert repository.get_winner(
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        as_of=_at(8),
    ) == PersistedCanonicalAccountCreationBindingV2(binding, claim)
    assert (
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=_at(30),
        )
        == binding
    )


@pytest.mark.django_db(transaction=True)
def test_every_independent_claim_anchor_finds_the_same_claim() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    with repository.atomic():
        _append_pair(repository, binding, claim)

    selectors = (
        {"claim_id": claim.claim_id, "claim_version": claim.claim_version},
        {"allocation_identity_hash": claim.allocation.identity_hash},
        {"allocation_content_hash": claim.allocation.content_hash},
        {"consumer_identity_hash": claim.consumer.identity_hash},
        {"consumer_content_hash": claim.consumer.content_hash},
        {"account_namespace": claim.account_namespace, "account_id": claim.account_id},
        {
            "underlying_unified_account_namespace": (claim.underlying_unified_account_namespace),
            "underlying_unified_account_id": claim.underlying_unified_account_id,
        },
        {"physical_v2_content_hash": claim.physical_v2_content_hash},
        {"physical_v3_root_content_hash": claim.physical_v3_root_content_hash},
    )
    for selector in selectors:
        assert (
            repository.get_consumption_claim_by_any_anchor(
                **_claim_selector(claim, **selector)  # type: ignore[arg-type]
            )
            == claim
        )


@pytest.mark.django_db(transaction=True)
def test_legacy_v1_without_claim_fails_closed_as_an_occupied_anchor() -> None:
    allocation = _allocation()
    binding: CanonicalAccountCreationBinding = _binding_v1(allocation=allocation)
    legacy = DjangoCanonicalAccountCreationRepository(clock=_Clock())
    with legacy.atomic():
        legacy.append_allocation(allocation, recorded_at=allocation.allocated_at)
        allocation_row = CanonicalAccountCreationAllocationModel._base_manager.get(
            content_hash=allocation.content_hash
        )
        values = _binding_values(binding, allocation_pk=allocation_row.pk)
        token = legacy._require_uow()
        with _claim_canonical_account_creation_insert(
            token=token,
            model_type=CanonicalAccountCreationBindingModel,
            expected_values=values,
        ):
            CanonicalAccountCreationBindingModel._default_manager.create(**values)

    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="legacy Binding-v1"):
        _repository().get_consumption_claim_by_any_anchor(
            **_claim_selector(
                _claim(),
                allocation_content_hash=allocation.content_hash,
            )  # type: ignore[arg-type]
        )


@pytest.mark.django_db(transaction=True)
def test_closed_world_unrelated_allocation_tamper_precedes_selector_filtering() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    with repository.atomic():
        _append_pair(repository, binding, claim)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE canonical_account_creation_allocation_ledger SET requester_actor_id = %s",
            ["tampered-actor"],
        )

    with pytest.raises(CanonicalAccountCreationBindingV2Corruption, match="allocation ledger"):
        repository.get_winner(
            binding_id="unrelated-binding",
            binding_version="v9",
            as_of=_at(8),
        )


@pytest.mark.django_db(transaction=True)
def test_private_uow_and_direct_model_inserts_are_rejected() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)

    with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="private UOW"):
        _append_pair(repository, binding, claim)
    with repository.atomic():
        with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="nested"):
            with repository.atomic():
                pass
    with pytest.raises(ValidationError):
        CanonicalAccountCreationConsumptionClaimModel.objects.create()
    with pytest.raises(ValidationError):
        CanonicalAccountCreationBindingV2Model.objects.create()


@pytest.mark.django_db(transaction=True)
def test_append_anchor_substitution_is_rejected_without_partial_rows() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    with repository.atomic():
        with pytest.raises(CanonicalAccountCreationBindingV2Conflict, match="anchors differ"):
            repository.append_with_consumption_claim(
                binding,
                claim,
                expected_allocation_content_hash="0" * 64,
                expected_account_claim_hash=binding.account_claim_hash,
                expected_underlying_claim_hash=binding.underlying_claim_hash,
                expected_creation_root_content_hash=binding.creation_root.content_hash,
                expected_consumption_claim_content_hash=claim.content_hash,
                recorded_at=binding.recorded_at,
            )
    assert CanonicalAccountCreationConsumptionClaimModel.objects.count() == 0
    assert CanonicalAccountCreationBindingV2Model.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_outer_transaction_rolls_back_claim_and_binding_together() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    with pytest.raises(RuntimeError, match="rollback"):
        with repository.atomic():
            _append_pair(repository, binding, claim)
            raise RuntimeError("rollback")
    assert CanonicalAccountCreationConsumptionClaimModel.objects.count() == 0
    assert CanonicalAccountCreationBindingV2Model.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_claim_link_hash_tamper_fails_closed() -> None:
    repository = _repository()
    binding, claim = _pair()
    _seed_v2_foreign_evidence(binding)
    with repository.atomic():
        _append_pair(repository, binding, claim)
    table = CanonicalAccountCreationBindingV2Model._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET consumption_claim_content_hash = %s',  # noqa: S608
            ["0" * 64],
        )

    with pytest.raises(CanonicalAccountCreationBindingV2Corruption, match="Binding-v2"):
        repository.get_exact_by_hash(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=binding.content_hash,
            as_of=_at(30),
        )
