from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_account_actor_authority_source_v3")
django.setup()

from django.core.exceptions import ValidationError
from django.db import connection, models

from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_models import (
    AccountRbacAuthorityMutationBindingV3Model,
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
    _activate_account_rbac_authority_mutation_binding_v3_uow,
    _claim_account_rbac_authority_mutation_binding_v3_insert,
)

RAW_MODELS = (AccountRbacAuthoritySourceV3AnchorModel, AccountRbacAuthoritySourceV3Model)
NEW_MODELS = (
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
    AccountRbacAuthorityMutationBindingV3Model,
)


@pytest.fixture(autouse=True)
def _schema() -> None:
    with connection.schema_editor() as editor:
        for model_type in (*RAW_MODELS, *NEW_MODELS):
            editor.create_model(model_type)
    yield
    with connection.schema_editor() as editor:
        for model_type in reversed((*RAW_MODELS, *NEW_MODELS)):
            editor.delete_model(model_type)


def _claim_insert(row: models.Model) -> None:
    expected = {
        field.name: getattr(row, field.name)
        for field in row._meta.concrete_fields
        if field.name != "id"
    }
    token = object()
    with _activate_account_rbac_authority_mutation_binding_v3_uow(token):
        with _claim_account_rbac_authority_mutation_binding_v3_insert(
            token=token, model_type=type(row), expected_values=expected
        ):
            row.save(force_insert=True)


def test_schema_is_zero_seed_and_keeps_exact_profile_and_binding_columns() -> None:
    assert all(model_type.objects.count() == 0 for model_type in (*RAW_MODELS, *NEW_MODELS))
    binding_names = {
        field.name for field in AccountRbacAuthorityMutationBindingV3Model._meta.fields
    }
    assert {
        "epoch",
        "authority_source",
        "predecessor",
        "mutation_id",
        "mutation_kind",
        "source_id",
        "source_version",
        "old_profile_id",
        "old_profile_version",
        "old_profile_content_hash",
        "profile_id",
        "profile_version",
        "profile_content_hash",
        "operator_user_id",
        "operator_authority_hash",
        "issuer_service_id",
        "authority_source_content_hash",
        "binding_root_claim_hash",
        "binding_supersedes_content_hash",
        "source_root_claim_hash",
        "source_supersedes_content_hash",
        "canonical_payload",
        "ledger_seal",
        "persisted_at",
    } <= binding_names
    for model_type in NEW_MODELS:
        names = {field.name for field in model_type._meta.fields}
        assert names.isdisjoint(
            {
                "session_key",
                "session_data",
                "cookie",
                "csrf_token",
                "password",
                "password_hash",
                "token",
            }
        )


@pytest.mark.parametrize("model_type", NEW_MODELS)
def test_every_model_requires_private_exact_insert_and_blocks_mutation(
    model_type: type[models.Model],
) -> None:
    row = model_type()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(raw=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        model_type.objects.bulk_create([])
    with pytest.raises(ValidationError):
        model_type.objects.all().update()
    with pytest.raises(ValidationError):
        model_type.objects.all().delete()


def test_private_uow_and_claim_are_non_nestable() -> None:
    token = object()
    with _activate_account_rbac_authority_mutation_binding_v3_uow(token):
        with pytest.raises(ValidationError, match="cannot be nested"):
            with _activate_account_rbac_authority_mutation_binding_v3_uow(object()):
                pass
        with _claim_account_rbac_authority_mutation_binding_v3_insert(
            token=token,
            model_type=AccountRbacAuthorityProfileV3AnchorModel,
            expected_values={"profile_id": "profile-1"},
        ):
            with pytest.raises(ValidationError, match="cannot be nested"):
                with _claim_account_rbac_authority_mutation_binding_v3_insert(
                    token=token,
                    model_type=AccountRbacAuthorityProfileV3AnchorModel,
                    expected_values={"profile_id": "profile-1"},
                ):
                    pass


def test_profile_anchor_exact_claim_roundtrip() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    row = AccountRbacAuthorityProfileV3AnchorModel(
        profile_id="profile-1",
        user_id=41,
        subject_actor_id="django-user:41",
        root_claim_hash="a" * 64,
        created_at=now,
    )
    _claim_insert(row)
    assert AccountRbacAuthorityProfileV3AnchorModel.objects.get(pk=row.pk).profile_id == "profile-1"


def test_migration_is_schema_only_and_has_four_concrete_models() -> None:
    module = importlib.import_module(
        "apps.account.migrations.0053_account_rbac_authority_mutation_binding_v3"
    )
    operation_names = [type(operation).__name__ for operation in module.Migration.operations]
    assert operation_names.count("CreateModel") == 4
    assert "RunPython" not in operation_names
    assert "RunSQL" not in operation_names
    assert module.Migration.dependencies == [
        ("account", "0052_account_actor_authority_raw_source_v3_ledgers")
    ]


def test_foreign_keys_are_protect_and_predecessors_are_one_to_one() -> None:
    for model_type in (
        AccountRbacAuthorityMutationBindingV3Model,
        AccountRbacAuthorityProfileV3VersionModel,
    ):
        predecessor = model_type._meta.get_field("predecessor")
        assert isinstance(predecessor, models.OneToOneField)
        assert predecessor.remote_field.on_delete is models.PROTECT
    binding = AccountRbacAuthorityMutationBindingV3Model
    for name in ("epoch", "authority_source"):
        field = binding._meta.get_field(name)
        assert isinstance(field, models.ForeignKey | models.OneToOneField)
        assert field.remote_field.on_delete is models.PROTECT
