"""Isolated database constraints for Account owner-assignment evidence v2."""

from __future__ import annotations

import ast
import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.migrations.state import ModelState, ProjectState

from apps.account.infrastructure.account_owner_assignment_evidence_v2_models import (
    AccountOwnerAssignmentEvidenceV2Model,
    AccountOwnerAssignmentSubjectV2Model,
    _activate_account_owner_assignment_evidence_v2_uow,
    _claim_account_owner_assignment_evidence_v2_insert,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _subject_values(*, suffix: str = "1") -> dict[str, object]:
    return {
        "owner": "account",
        "artifact_type": "account_owner_assignment_subject_v2",
        "schema": "account-owner-assignment-subject.v2",
        "subject_id": f"subject-{suffix}",
        "subject_version": "v1",
        "physical_observation_id": f"physical-{suffix}",
        "physical_observation_version": "v1",
        "physical_identity_hash": ("1" if suffix == "1" else "2") * 64,
        "physical_content_hash": ("3" if suffix == "1" else "4") * 64,
        "receipt_id": f"receipt-{suffix}",
        "receipt_version": "v1",
        "receipt_identity_hash": ("5" if suffix == "1" else "6") * 64,
        "receipt_content_hash": ("7" if suffix == "1" else "8") * 64,
        "account_namespace": "simulated",
        "account_id": f"account-{suffix}",
        "underlying_unified_account_namespace": "simulated-account-pk",
        "underlying_unified_account_id": int(suffix),
        "requested_at": _at(7),
        "valid_until": _at(9),
        "permission": "evidence_only",
        "status": "inactive",
        "canonical_payload": {"subject": suffix},
        "identity_hash": ("9" if suffix == "1" else "a") * 64,
        "content_hash": ("b" if suffix == "1" else "c") * 64,
        "upstream_binding_seal": "d" * 64,
        "fixed_authority_seal": "e" * 64,
        "record_seal": ("f" if suffix == "1" else "0") * 64,
        "ledger_seal": ("1" if suffix == "1" else "2") * 64,
        "persisted_at": _at(7),
    }


def _evidence_values(
    subject: AccountOwnerAssignmentSubjectV2Model,
    *,
    suffix: str = "1",
    predecessor: str | None = None,
    account_root: str | None = "3" * 64,
    underlying_root: str | None = "4" * 64,
) -> dict[str, object]:
    return {
        "subject_id": subject.pk,
        "subject_content_hash": subject.content_hash,
        "owner": "account",
        "artifact_type": "account_owner_assignment_evidence_v2",
        "schema": "account-owner-assignment-evidence.v2",
        "evidence_id": "evidence-chain",
        "evidence_version": f"v{suffix}",
        "identity_hash": ("5" if suffix == "1" else "6") * 64,
        "content_hash": ("7" if suffix == "1" else "8") * 64,
        "account_namespace": subject.account_namespace,
        "account_id": subject.account_id,
        "underlying_unified_account_namespace": subject.underlying_unified_account_namespace,
        "underlying_unified_account_id": subject.underlying_unified_account_id,
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 8,
        "approved_actor_id": "approver-9",
        "approved_user_id": 9,
        "approved_role": "account_owner_assignment_approver",
        "approved_kind": "human",
        "approved_is_staff": True,
        "approved_at": _at(7),
        "recorded_at": _at(8),
        "approval_valid_until": _at(9),
        "valid_until": _at(9),
        "supersedes_content_hash": predecessor,
        "account_root_claim_hash": account_root,
        "underlying_root_claim_hash": underlying_root,
        "permission": "evidence_only",
        "status": "inactive",
        "blocker_codes": ["account_owner_assignment_evidence_v2_not_integrated"],
        "canonical_payload": {"evidence": suffix},
        "subject_binding_seal": "9" * 64,
        "approver_binding_seal": "a" * 64,
        "mapping_binding_seal": "b" * 64,
        "fixed_authority_seal": "c" * 64,
        "record_seal": ("d" if suffix == "1" else "e") * 64,
        "ledger_seal": ("f" if suffix == "1" else "0") * 64,
        "persisted_at": _at(8),
    }


def _insert(model_type: type[models.Model], values: dict[str, object]) -> models.Model:
    token = object()
    with (
        _activate_account_owner_assignment_evidence_v2_uow(token),
        _claim_account_owner_assignment_evidence_v2_insert(
            token=token, model_type=model_type, expected_values=values
        ),
    ):
        return model_type._default_manager.create(**values)


@pytest.mark.django_db(transaction=True)
def test_private_claim_root_shape_and_mutation_guards() -> None:
    subject = _insert(AccountOwnerAssignmentSubjectV2Model, _subject_values())
    assert isinstance(subject, AccountOwnerAssignmentSubjectV2Model)
    evidence = _insert(AccountOwnerAssignmentEvidenceV2Model, _evidence_values(subject))
    assert isinstance(evidence, AccountOwnerAssignmentEvidenceV2Model)
    assert evidence.subject_id == subject.pk
    assert evidence.account_root_claim_hash and evidence.underlying_root_claim_hash

    with pytest.raises(ValidationError):
        AccountOwnerAssignmentSubjectV2Model(**_subject_values(suffix="2")).save()
    for action in (
        lambda: AccountOwnerAssignmentEvidenceV2Model.objects.update(status="active"),
        lambda: AccountOwnerAssignmentEvidenceV2Model.objects.all().delete(),
        lambda: evidence.save(update_fields=["status"]),
        lambda: evidence.delete(),
    ):
        with pytest.raises(ValidationError):
            action()


@pytest.mark.django_db(transaction=True)
def test_root_and_successor_columns_are_database_enforced() -> None:
    first = _insert(AccountOwnerAssignmentSubjectV2Model, _subject_values())
    assert isinstance(first, AccountOwnerAssignmentSubjectV2Model)
    _insert(AccountOwnerAssignmentEvidenceV2Model, _evidence_values(first))
    second = _insert(AccountOwnerAssignmentSubjectV2Model, _subject_values(suffix="2"))
    assert isinstance(second, AccountOwnerAssignmentSubjectV2Model)

    invalid = _evidence_values(
        second,
        suffix="2",
        predecessor=None,
        account_root="5" * 64,
        underlying_root=None,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _insert(AccountOwnerAssignmentEvidenceV2Model, invalid)

    successor = _evidence_values(
        second,
        suffix="2",
        predecessor="7" * 64,
        account_root=None,
        underlying_root=None,
    )
    assert _insert(AccountOwnerAssignmentEvidenceV2Model, successor).supersedes_content_hash


def test_dual_partial_unique_and_identity_constraints_are_declared() -> None:
    names = {
        constraint.name for constraint in AccountOwnerAssignmentEvidenceV2Model._meta.constraints
    }
    assert {
        "acct_own_v2_ev_id_uq",
        "acct_own_v2_acct_root_uq",
        "acct_own_v2_under_root_uq",
        "acct_own_v2_next_uq",
        "acct_own_v2_link_ck",
    } <= names
    assert AccountOwnerAssignmentEvidenceV2Model._meta.get_field("identity_hash").unique
    assert AccountOwnerAssignmentEvidenceV2Model._meta.get_field("content_hash").unique
    assert AccountOwnerAssignmentEvidenceV2Model._meta.get_field("subject_content_hash").unique
    assert AccountOwnerAssignmentEvidenceV2Model._meta.get_field("subject").unique


def test_0044_migration_is_schema_only() -> None:
    migration = Path("apps/account/migrations/0044_account_owner_assignment_evidence_v2_ledger.py")
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "CreateModel" in calls
    assert calls.isdisjoint({"RunPython", "RunSQL", "AddField", "AlterField"})


def test_0044_matches_the_current_two_model_state() -> None:
    migration_module = importlib.import_module(
        "apps.account.migrations.0044_account_owner_assignment_evidence_v2_ledger"
    )
    state = ProjectState()
    for operation in migration_module.Migration.operations:
        operation.state_forwards("account", state)

    for model in (AccountOwnerAssignmentSubjectV2Model, AccountOwnerAssignmentEvidenceV2Model):
        current = ModelState.from_model(model)
        historical = state.models[("account", model._meta.model_name)]
        current_options = {key: value for key, value in current.options.items() if key != "abstract"}
        assert current_options == historical.options
        assert set(current.fields) == set(historical.fields)
        for name, current_field in current.fields.items():
            assert current_field.deconstruct()[1:] == historical.fields[name].deconstruct()[1:]
