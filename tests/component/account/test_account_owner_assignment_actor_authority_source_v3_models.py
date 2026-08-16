from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import django
import pytest

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_account_actor_authority_source_v3"
django.setup()

from django.core.exceptions import ValidationError

from apps.account.infrastructure.account_owner_assignment_actor_authority_source_v3_models import (
    AccountOwnerAssignmentActorAuthoritySourceV3Model,
    AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
    _activate_account_owner_assignment_actor_authority_source_v3_uow,
    _claim_account_owner_assignment_actor_authority_source_v3_insert,
)
from tests.support.isolated_schema import isolated_schema


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(
            (
                AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel,
                AccountOwnerAssignmentActorAuthoritySourceV3Model,
            )
        ):
            yield


def test_schema_is_zero_seed_and_has_two_append_only_models() -> None:
    assert AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.count() == 0
    assert AccountOwnerAssignmentActorAuthoritySourceV3Model.objects.count() == 0
    assert {
        constraint.name
        for constraint in AccountOwnerAssignmentActorAuthoritySourceV3Model._meta.constraints
    } == {
        "acct_aav3_source_uq",
        "acct_aav3_fixed_ck",
        "acct_aav3_state_ck",
        "acct_aav3_root_xor_ck",
        "acct_aav3_clock_ck",
    }


def test_root_lock_requires_private_uow_exact_claim_and_is_immutable() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    row = AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel(
        source_id="authority-1", root_claim_hash="a" * 64, created_at=now
    )
    with pytest.raises(ValidationError):
        row.save()
    token = object()
    values = {"source_id": "authority-1", "root_claim_hash": "a" * 64, "created_at": now}
    with (
        _activate_account_owner_assignment_actor_authority_source_v3_uow(token),
        _claim_account_owner_assignment_actor_authority_source_v3_insert(
            token=token, model_type=type(row), expected_values=values
        ),
    ):
        row.save(force_insert=True)
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.update(created_at=now)
    with pytest.raises(ValidationError):
        AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel.objects.all().delete()


def test_migration_is_schema_only_two_create_models() -> None:
    import importlib

    module = importlib.import_module(
        "apps.account.migrations.0051_actor_authority_source_v3_ledgers"
    )
    assert [type(operation).__name__ for operation in module.Migration.operations] == [
        "CreateModel",
        "CreateModel",
    ]
    assert module.Migration.dependencies == [
        ("account", "0050_account_owner_assignment_evidence_v3_ledgers")
    ]
