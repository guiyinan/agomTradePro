from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime

import django
import pytest

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_account_actor_authority_source_v3"
django.setup()

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction

from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountAuthenticationContextSourceV3Model,
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountUserAuthoritySourceV3Model,
    _activate_account_actor_authority_raw_source_v3_uow,
    _claim_account_actor_authority_raw_source_v3_insert,
)

ANCHORS = (
    AccountAuthenticationContextSourceV3AnchorModel,
    AccountUserAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3AnchorModel,
)
LEDGERS = (
    AccountAuthenticationContextSourceV3Model,
    AccountUserAuthoritySourceV3Model,
    AccountRbacAuthoritySourceV3Model,
)


def _insert_anchor(model_type: type[models.Model], source_id: str) -> models.Model:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    row = model_type(source_id=source_id, root_claim_hash="a" * 64, created_at=now)
    token = object()
    with _activate_account_actor_authority_raw_source_v3_uow(token):
        with _claim_account_actor_authority_raw_source_v3_insert(
            token=token,
            model_type=model_type,
            expected_values={
                "source_id": source_id,
                "root_claim_hash": "a" * 64,
                "created_at": now,
            },
        ):
            row.save(force_insert=True)
    return row


def _ledger_row(
    model_type: type[models.Model], anchor: models.Model, **changes: object
) -> models.Model:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    fixed = {
        AccountAuthenticationContextSourceV3Model: (
            "account_authentication_context_source_v3",
            "account.authentication_context_source.v3",
        ),
        AccountUserAuthoritySourceV3Model: (
            "account_user_authority_source_v3",
            "account.user_authority_source.v3",
        ),
        AccountRbacAuthoritySourceV3Model: (
            "account_rbac_authority_source_v3",
            "account.rbac_authority_source.v3",
        ),
    }[model_type]
    values: dict[str, object] = {
        "anchor": anchor,
        "predecessor": None,
        "owner": "account",
        "artifact_type": fixed[0],
        "schema": fixed[1],
        "permission": "attestation_only",
        "status": "inactive",
        "must_not_execute": True,
        "execution_allowed": False,
        "source_id": anchor.source_id,
        "source_version": "v1",
        "observed_at": now,
        "recorded_at": now,
        "valid_until": now.replace(hour=1),
        "root_claim_hash": anchor.root_claim_hash,
        "supersedes_content_hash": None,
        "identity_hash": "1" * 64,
        "facts_seal": "2" * 64,
        "clock_seal": "3" * 64,
        "chain_seal": "4" * 64,
        "fixed_authority_seal": "5" * 64,
        "record_seal": "6" * 64,
        "content_hash": "7" * 64,
        "recorded_by_service_id": "account-raw-authority-recorder-v3",
        "recorded_by_role": "account_actor_authority_raw_recorder",
        "recorded_by_kind": "service",
        "recorded_by_is_automated": True,
        "recorder_binding_seal": "8" * 64,
        "ledger_seal": "9" * 64,
        "canonical_payload": {},
        "persisted_at": now,
    }
    if model_type is AccountAuthenticationContextSourceV3Model:
        values.update(
            principal_id="principal-41",
            user_id=41,
            actor_id="django-user:41",
            is_authenticated=True,
            authority_state="authenticated",
            authenticated_at=now,
            principal_seal="b" * 64,
        )
    elif model_type is AccountUserAuthoritySourceV3Model:
        values.update(
            user_id=41,
            actor_id="django-user:41",
            is_active=True,
            is_staff=False,
            is_superuser=False,
            authority_state="current",
            user_seal="b" * 64,
        )
    else:
        values.update(
            user_id=41,
            actor_id="django-user:41",
            rbac_role="owner",
            authority_state="current",
            rbac_seal="b" * 64,
        )
    values.update(changes)
    return model_type(**values)


def _claimed_insert(row: models.Model) -> None:
    expected = {
        field.name: getattr(row, field.name)
        for field in row._meta.concrete_fields
        if field.name != "id"
    }
    token = object()
    with _activate_account_actor_authority_raw_source_v3_uow(token):
        with _claim_account_actor_authority_raw_source_v3_insert(
            token=token, model_type=type(row), expected_values=expected
        ):
            row.save(force_insert=True)


@pytest.fixture(autouse=True)
def _schema() -> None:
    with connection.schema_editor() as editor:
        for model_type in ANCHORS:
            editor.create_model(model_type)
        for model_type in LEDGERS:
            editor.create_model(model_type)
    yield
    with connection.schema_editor() as editor:
        for model_type in reversed(LEDGERS):
            editor.delete_model(model_type)
        for model_type in reversed(ANCHORS):
            editor.delete_model(model_type)


def test_schema_has_three_independent_non_json_only_anchor_ledgers() -> None:
    assert all(model_type.objects.count() == 0 for model_type in (*ANCHORS, *LEDGERS))
    expected_concrete = {
        AccountAuthenticationContextSourceV3Model: {
            "principal_id",
            "user_id",
            "actor_id",
            "is_authenticated",
            "authority_state",
            "authenticated_at",
            "principal_seal",
        },
        AccountUserAuthoritySourceV3Model: {
            "user_id",
            "actor_id",
            "is_active",
            "is_staff",
            "is_superuser",
            "authority_state",
            "user_seal",
        },
        AccountRbacAuthoritySourceV3Model: {
            "user_id",
            "actor_id",
            "rbac_role",
            "authority_state",
            "rbac_seal",
        },
    }
    common = {
        "source_id",
        "source_version",
        "observed_at",
        "recorded_at",
        "valid_until",
        "root_claim_hash",
        "supersedes_content_hash",
        "identity_hash",
        "facts_seal",
        "clock_seal",
        "chain_seal",
        "fixed_authority_seal",
        "record_seal",
        "content_hash",
        "canonical_payload",
        "recorded_by_service_id",
        "recorded_by_role",
        "recorded_by_kind",
        "recorded_by_is_automated",
        "recorder_binding_seal",
        "ledger_seal",
        "persisted_at",
    }
    for model_type, specific in expected_concrete.items():
        names = {field.name for field in model_type._meta.fields}
        assert common | specific <= names
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
        assert isinstance(model_type._meta.get_field("anchor"), models.ForeignKey)
        assert model_type._meta.get_field("anchor").remote_field.on_delete is models.PROTECT
        assert isinstance(model_type._meta.get_field("predecessor"), models.OneToOneField)
        assert model_type._meta.get_field("predecessor").remote_field.on_delete is models.PROTECT


@pytest.mark.parametrize("model_type", ANCHORS)
def test_every_anchor_requires_private_uow_exact_claim_and_blocks_mutation(
    model_type: type[models.Model],
) -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    source_id = model_type.__name__
    row = model_type(source_id=source_id, root_claim_hash="a" * 64, created_at=now)
    with pytest.raises(ValidationError):
        row.save()
    token = object()
    with _activate_account_actor_authority_raw_source_v3_uow(token):
        with pytest.raises(ValidationError):
            with _claim_account_actor_authority_raw_source_v3_insert(
                token=token,
                model_type=model_type,
                expected_values={"source_id": "substituted"},
            ):
                row.save(force_insert=True)
        with _claim_account_actor_authority_raw_source_v3_insert(
            token=token,
            model_type=model_type,
            expected_values={
                "source_id": source_id,
                "root_claim_hash": "a" * 64,
                "created_at": now,
            },
        ):
            row.save(force_insert=True)
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        model_type.objects.all().update(created_at=now)
    with pytest.raises(ValidationError):
        model_type.objects.all().delete()
    with pytest.raises(ValidationError):
        model_type.objects.bulk_create([])


def test_private_uow_and_insert_claim_cannot_be_nested() -> None:
    token = object()
    with _activate_account_actor_authority_raw_source_v3_uow(token):
        with pytest.raises(ValidationError, match="cannot be nested"):
            with _activate_account_actor_authority_raw_source_v3_uow(object()):
                pass
        with _claim_account_actor_authority_raw_source_v3_insert(
            token=token,
            model_type=AccountAuthenticationContextSourceV3AnchorModel,
            expected_values={"source_id": "auth-context-1"},
        ):
            with pytest.raises(ValidationError, match="cannot be nested"):
                with _claim_account_actor_authority_raw_source_v3_insert(
                    token=token,
                    model_type=AccountAuthenticationContextSourceV3AnchorModel,
                    expected_values={"source_id": "auth-context-1"},
                ):
                    pass


@pytest.mark.parametrize("model_type", LEDGERS)
def test_every_ledger_blocks_direct_bulk_raw_update_and_delete_paths(
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
        model_type.objects.all().update(owner="substituted")
    with pytest.raises(ValidationError):
        model_type.objects.all().delete()


@pytest.mark.parametrize(
    ("anchor_type", "ledger_type"),
    (
        (
            AccountAuthenticationContextSourceV3AnchorModel,
            AccountAuthenticationContextSourceV3Model,
        ),
        (AccountUserAuthoritySourceV3AnchorModel, AccountUserAuthoritySourceV3Model),
        (AccountRbacAuthoritySourceV3AnchorModel, AccountRbacAuthoritySourceV3Model),
    ),
)
def test_every_ledger_accepts_only_a_private_claimed_constraint_valid_insert(
    anchor_type: type[models.Model], ledger_type: type[models.Model]
) -> None:
    anchor = _insert_anchor(anchor_type, f"source-{ledger_type.__name__}")
    row = _ledger_row(ledger_type, anchor)

    _claimed_insert(row)

    assert ledger_type.objects.get().pk == row.pk


@pytest.mark.parametrize(
    ("anchor_type", "ledger_type", "changes"),
    (
        (
            AccountAuthenticationContextSourceV3AnchorModel,
            AccountAuthenticationContextSourceV3Model,
            {"user_id": 0},
        ),
        (
            AccountUserAuthoritySourceV3AnchorModel,
            AccountUserAuthoritySourceV3Model,
            {"user_id": 0},
        ),
        (
            AccountRbacAuthoritySourceV3AnchorModel,
            AccountRbacAuthoritySourceV3Model,
            {"rbac_role": "administrator"},
        ),
    ),
)
def test_database_rejects_invalid_positive_user_or_noncanonical_role(
    anchor_type: type[models.Model],
    ledger_type: type[models.Model],
    changes: dict[str, object],
) -> None:
    anchor = _insert_anchor(anchor_type, f"invalid-{ledger_type.__name__}")
    row = _ledger_row(ledger_type, anchor, **changes)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _claimed_insert(row)

    assert ledger_type.objects.count() == 0


def test_each_ledger_has_fixed_state_clock_xor_and_source_constraints() -> None:
    expected = {
        AccountAuthenticationContextSourceV3Model: {
            "acct_auth3_source_uq",
            "acct_auth3_fixed_ck",
            "acct_auth3_state_ck",
            "acct_auth3_auth_clock_ck",
            "acct_auth3_user_ck",
            "acct_auth3_root_xor_ck",
            "acct_auth3_clock_ck",
        },
        AccountUserAuthoritySourceV3Model: {
            "acct_user3_source_uq",
            "acct_user3_fixed_ck",
            "acct_user3_state_ck",
            "acct_user3_user_ck",
            "acct_user3_root_xor_ck",
            "acct_user3_clock_ck",
        },
        AccountRbacAuthoritySourceV3Model: {
            "acct_rbac3_source_uq",
            "acct_rbac3_fixed_ck",
            "acct_rbac3_state_ck",
            "acct_rbac3_role_ck",
            "acct_rbac3_user_ck",
            "acct_rbac3_root_xor_ck",
            "acct_rbac3_clock_ck",
        },
    }
    for model_type, names in expected.items():
        assert {constraint.name for constraint in model_type._meta.constraints} == names


def test_0052_is_schema_only_and_creates_exactly_six_models() -> None:
    module = importlib.import_module(
        "apps.account.migrations.0052_account_actor_authority_raw_source_v3_ledgers"
    )
    operation_names = [type(operation).__name__ for operation in module.Migration.operations]
    assert operation_names.count("CreateModel") == 6
    assert "RunPython" not in operation_names
    assert "RunSQL" not in operation_names
    assert module.Migration.dependencies == [("account", "0051_actor_authority_source_v3_ledgers")]
