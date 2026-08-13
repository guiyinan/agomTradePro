"""Isolated schema and mutation guards for canonical Account creation ledgers."""

from __future__ import annotations

import ast
import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.migrations.state import ModelState, ProjectState

from apps.account.infrastructure.canonical_account_creation_models import (
    CanonicalAccountCreationAllocationModel,
    CanonicalAccountCreationBindingModel,
    _activate_canonical_account_creation_uow,
    _claim_canonical_account_creation_insert,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _allocation_values(suffix: str = "1") -> dict[str, object]:
    return {
        "owner": "account",
        "artifact_type": "canonical_account_creation_allocation",
        "schema": "canonical-account-creation-allocation.v1",
        "allocation_id": f"allocation-{suffix}",
        "allocation_version": "v1",
        "canonical_account_namespace": "account",
        "canonical_account_id": f"acct-{suffix}",
        "requested_row_user_id": int(suffix),
        "requested_raw_account_type": "SIMULATED",
        "intended_underlying_unified_account_namespace": "simulated-account-row",
        "request_fingerprint_hash": suffix * 64,
        "requester_actor_id": f"actor-{suffix}",
        "requester_user_id": int(suffix),
        "requester_role": "account_creator",
        "requester_kind": "human",
        "requester_is_authenticated": True,
        "allocated_at": _at(1),
        "valid_until": _at(9),
        "recorded_service_id": "account-identity-allocator",
        "recorded_role": "canonical_account_identity_allocator",
        "recorded_kind": "service",
        "recorded_is_automated": True,
        "intended_purpose": "simulated_account_create",
        "permission": "identity_allocation_only",
        "status": "inactive",
        "canonical_payload": {"allocation": suffix},
        "identity_hash": ("a" if suffix == "1" else "b") * 64,
        "content_hash": ("c" if suffix == "1" else "d") * 64,
        "requester_binding_seal": "e" * 64,
        "recorder_binding_seal": "f" * 64,
        "fixed_authority_seal": "1" * 64,
        "record_seal": ("2" if suffix == "1" else "3") * 64,
        "ledger_seal": ("4" if suffix == "1" else "5") * 64,
        "persisted_at": _at(1),
    }


def _binding_values(allocation: CanonicalAccountCreationAllocationModel) -> dict[str, object]:
    return {
        "allocation_id": allocation.pk,
        "allocation_content_hash": allocation.content_hash,
        "owner": "account",
        "artifact_type": "canonical_account_creation_binding",
        "schema": "canonical-account-creation-binding.v1",
        "binding_id": "binding-1",
        "binding_version": "v1",
        "physical_observation_id": "physical-1",
        "physical_observation_version": "v1",
        "physical_identity_hash": "6" * 64,
        "physical_content_hash": "7" * 64,
        "account_namespace_claim": "account",
        "account_id_claim": allocation.canonical_account_id,
        "underlying_unified_account_namespace_claim": "simulated-account-row",
        "underlying_unified_account_id_claim": 1,
        "recorded_service_id": "account-creation-binder",
        "recorded_role": "canonical_account_creation_binder",
        "recorded_kind": "service",
        "recorded_is_automated": True,
        "recorded_at": _at(2),
        "valid_until": _at(8),
        "account_claim_hash": "8" * 64,
        "underlying_claim_hash": "9" * 64,
        "permission": "identity_binding_evidence_only",
        "status": "inactive",
        "binding_state": "pending_owner_approval",
        "owner_assignment_state": "unknown",
        "canonical_payload": {"binding": "1"},
        "identity_hash": "a" * 64,
        "content_hash": "b" * 64,
        "allocation_binding_seal": "c" * 64,
        "physical_binding_seal": "d" * 64,
        "recorder_binding_seal": "e" * 64,
        "fixed_authority_seal": "f" * 64,
        "record_seal": "0" * 64,
        "ledger_seal": "1" * 64,
        "persisted_at": _at(2),
    }


def _insert(model_type: type[models.Model], values: dict[str, object]) -> models.Model:
    token = object()
    with (
        _activate_canonical_account_creation_uow(token),
        _claim_canonical_account_creation_insert(
            token=token, model_type=model_type, expected_values=values
        ),
    ):
        return model_type._default_manager.create(**values)


@pytest.mark.django_db(transaction=True)
def test_zero_seed_private_claim_and_mutation_guards() -> None:
    assert CanonicalAccountCreationAllocationModel.objects.count() == 0
    assert CanonicalAccountCreationBindingModel.objects.count() == 0
    allocation = _insert(CanonicalAccountCreationAllocationModel, _allocation_values())
    assert isinstance(allocation, CanonicalAccountCreationAllocationModel)
    binding = _insert(CanonicalAccountCreationBindingModel, _binding_values(allocation))
    assert isinstance(binding, CanonicalAccountCreationBindingModel)
    with pytest.raises(ValidationError):
        CanonicalAccountCreationAllocationModel(**_allocation_values("2")).save()
    unclaimed = CanonicalAccountCreationAllocationModel(**_allocation_values("2"))
    for action in (
        lambda: CanonicalAccountCreationBindingModel.objects.update(status="active"),
        lambda: CanonicalAccountCreationBindingModel.objects.all().delete(),
        lambda: CanonicalAccountCreationAllocationModel.objects.bulk_create([unclaimed]),
        lambda: CanonicalAccountCreationAllocationModel.objects.all().bulk_create([unclaimed]),
        lambda: CanonicalAccountCreationBindingModel.objects.bulk_update(
            [binding], ["status"]
        ),
        lambda: binding.save_base(raw=True),
        lambda: binding.save(update_fields=["status"]),
        lambda: binding.delete(),
    ):
        with pytest.raises(ValidationError):
            action()


@pytest.mark.django_db(transaction=True)
def test_database_uniqueness_and_clock_constraints() -> None:
    allocation = _insert(CanonicalAccountCreationAllocationModel, _allocation_values())
    assert isinstance(allocation, CanonicalAccountCreationAllocationModel)
    duplicate = _allocation_values("2")
    duplicate["canonical_account_id"] = allocation.canonical_account_id
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert(CanonicalAccountCreationAllocationModel, duplicate)
    invalid = _allocation_values("2")
    invalid["persisted_at"] = _at(2)
    with pytest.raises(IntegrityError), transaction.atomic():
        _insert(CanonicalAccountCreationAllocationModel, invalid)


def test_0045_is_schema_only_and_matches_current_model_state() -> None:
    path = Path("apps/account/migrations/0045_canonical_account_creation_ledger.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint({"RunPython", "RunSQL", "AddField", "AlterField"})
    assert (
        sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "CreateModel"
        )
        == 2
    )
    module = importlib.import_module(
        "apps.account.migrations.0045_canonical_account_creation_ledger"
    )
    state = ProjectState()
    for operation in module.Migration.operations:
        operation.state_forwards("account", state)
    for model in (CanonicalAccountCreationAllocationModel, CanonicalAccountCreationBindingModel):
        current = ModelState.from_model(model)
        historical = state.models[("account", model._meta.model_name)]
        current_options = {
            key: value for key, value in current.options.items() if key != "abstract"
        }
        assert current_options == historical.options
        assert set(current.fields) == set(historical.fields)
        for name, field in current.fields.items():
            assert field.deconstruct()[1:] == historical.fields[name].deconstruct()[1:]
