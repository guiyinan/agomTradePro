"""Isolated component evidence for the 0047 creation-consumption expand schema."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, migrations, models, transaction
from django.db.migrations.state import ModelState, ProjectState

from apps.account.infrastructure.allocated_physical_account_row_observation_v3_models import (
    AllocatedPhysicalAccountRowObservationV3Model,
)
from apps.account.infrastructure.canonical_account_creation_consumption_models import (
    CanonicalAccountCreationBindingV2Model,
    CanonicalAccountCreationConsumptionClaimModel,
    _activate_canonical_account_creation_consumption_uow,
    _claim_canonical_account_creation_consumption_insert,
)
from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
)
from tests.component.account.test_canonical_account_creation_models import (
    _allocation_values,
    _binding_values,
    _insert,
)


def _hash(character: str) -> str:
    return character * 64


def _claim_values(
    allocation: CanonicalAccountCreationAllocationModel,
    *,
    suffix: str = "1",
) -> dict[str, object]:
    return {
        "owner": "account",
        "artifact_type": "canonical_account_creation_consumption_claim",
        "schema": "canonical-account-creation-consumption-claim.v1",
        "claim_id": f"claim-{suffix}",
        "claim_version": "v1",
        "allocation_id": allocation.pk,
        "allocation_identity_hash": allocation.identity_hash,
        "allocation_content_hash": allocation.content_hash,
        "consumer_generation": "v1",
        "consumer_owner": "account",
        "consumer_artifact_type": "canonical_account_creation_binding",
        "consumer_schema": "canonical-account-creation-binding.v1",
        "consumer_id": f"binding-{suffix}",
        "consumer_version": "v1",
        "consumer_identity_hash": _hash("6" if suffix == "1" else "7"),
        "consumer_content_hash": _hash("8" if suffix == "1" else "9"),
        "account_namespace": "account",
        "account_id": allocation.canonical_account_id,
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": int(suffix),
        "physical_v2_content_hash": _hash("a" if suffix == "1" else "b"),
        "physical_v3_root_content_hash": None,
        "recorded_at": allocation.allocated_at,
        "permission": "evidence_only",
        "status": "inactive",
        "canonical_payload": {"claim": suffix},
        "identity_hash": _hash("c" if suffix == "1" else "d"),
        "content_hash": _hash("e" if suffix == "1" else "f"),
        "allocation_binding_seal": _hash("1"),
        "consumer_binding_seal": _hash("2"),
        "fixed_authority_seal": _hash("3"),
        "record_seal": _hash("4" if suffix == "1" else "5"),
        "ledger_seal": _hash("0" if suffix == "1" else "6"),
        "persisted_at": allocation.allocated_at,
    }


def _insert_consumption(model_type: type[models.Model], values: dict[str, object]) -> models.Model:
    token = object()
    with (
        _activate_canonical_account_creation_consumption_uow(token),
        _claim_canonical_account_creation_consumption_insert(
            token=token,
            model_type=model_type,
            expected_values=values,
        ),
    ):
        return model_type._default_manager.create(**values)


@pytest.mark.django_db(transaction=True)
def test_zero_seed_private_guards_and_nullable_v1_expansion() -> None:
    assert CanonicalAccountCreationConsumptionClaimModel.objects.count() == 0
    assert CanonicalAccountCreationBindingV2Model.objects.count() == 0
    allocation = _insert(CanonicalAccountCreationAllocationModel, _allocation_values())
    assert isinstance(allocation, CanonicalAccountCreationAllocationModel)
    binding_v1 = _insert(CanonicalAccountCreationBindingModel, _binding_values(allocation))
    assert isinstance(binding_v1, CanonicalAccountCreationBindingModel)
    assert binding_v1.consumption_claim_id is None

    values = _claim_values(allocation)
    with pytest.raises(ValidationError):
        CanonicalAccountCreationConsumptionClaimModel.objects.create(**values)
    with pytest.raises(ValidationError):
        CanonicalAccountCreationBindingV2Model.objects.create()
    claim = _insert_consumption(CanonicalAccountCreationConsumptionClaimModel, values)
    assert isinstance(claim, CanonicalAccountCreationConsumptionClaimModel)
    with pytest.raises(ValidationError):
        claim.save(update_fields=["canonical_payload"])
    with pytest.raises(ValidationError):
        CanonicalAccountCreationConsumptionClaimModel.objects.update(
            canonical_payload={"tampered": True}
        )
    with pytest.raises(ValidationError):
        CanonicalAccountCreationConsumptionClaimModel.objects.all().delete()


@pytest.mark.django_db(transaction=True)
def test_cross_generation_unique_anchors_and_branch_clock_checks() -> None:
    first = _insert(CanonicalAccountCreationAllocationModel, _allocation_values())
    second = _insert(CanonicalAccountCreationAllocationModel, _allocation_values("2"))
    assert isinstance(first, CanonicalAccountCreationAllocationModel)
    assert isinstance(second, CanonicalAccountCreationAllocationModel)
    _insert_consumption(CanonicalAccountCreationConsumptionClaimModel, _claim_values(first))

    duplicate_account = _claim_values(second, suffix="2")
    duplicate_account["account_id"] = first.canonical_account_id
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_consumption(
            CanonicalAccountCreationConsumptionClaimModel,
            duplicate_account,
        )

    invalid_branch = _claim_values(second, suffix="2")
    invalid_branch["physical_v3_root_content_hash"] = _hash("7")
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_consumption(
            CanonicalAccountCreationConsumptionClaimModel,
            invalid_branch,
        )

    invalid_clock = _claim_values(second, suffix="2")
    invalid_clock["persisted_at"] = second.valid_until
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert_consumption(
            CanonicalAccountCreationConsumptionClaimModel,
            invalid_clock,
        )


def test_0047_schema_state_is_pure_expand_and_matches_models() -> None:
    modules = [
        import_module("apps.account.migrations.0045_canonical_account_creation_ledger"),
        import_module(
            "apps.account.migrations.0046_allocated_physical_account_row_observation_v3_ledger"
        ),
        import_module("apps.account.migrations.0047_canonical_account_creation_consumption_expand"),
    ]
    migration = modules[-1].Migration
    assert migration.dependencies == [
        ("account", "0046_allocated_physical_account_row_observation_v3_ledger")
    ]
    assert [type(operation) for operation in migration.operations] == [
        migrations.CreateModel,
        migrations.CreateModel,
        migrations.AddField,
    ]
    assert not any(
        isinstance(operation, migrations.RunPython | migrations.RunSQL)
        for operation in migration.operations
    )

    state = ProjectState()
    for module in modules:
        for operation in module.Migration.operations:
            operation.state_forwards("account", state)
    for model in (
        CanonicalAccountCreationAllocationModel,
        CanonicalAccountCreationBindingModel,
        AllocatedPhysicalAccountRowObservationV3Model,
        CanonicalAccountCreationConsumptionClaimModel,
        CanonicalAccountCreationBindingV2Model,
    ):
        current = ModelState.from_model(model)
        historical = state.models[("account", model._meta.model_name)]
        current_options = {
            key: value for key, value in current.options.items() if key != "abstract"
        }
        assert current_options == historical.options
        assert set(current.fields) == set(historical.fields)
        for name, field in current.fields.items():
            assert field.deconstruct()[1:] == historical.fields[name].deconstruct()[1:]
