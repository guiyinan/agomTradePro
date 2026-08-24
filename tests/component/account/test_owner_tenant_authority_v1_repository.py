"""Component coverage for the append-only owner/tenant authority ledger."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.account.application.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1Corruption,
)
from apps.account.infrastructure.owner_tenant_authority_v1_models import (
    OwnerTenantAuthorityV1Model,
)
from apps.account.infrastructure.owner_tenant_authority_v1_repository import (
    DjangoOwnerTenantAuthorityV1Repository,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _at
from tests.unit.account.test_owner_tenant_authority_v1 import _authority


class _Clock:
    def now(self) -> datetime:
        return _at(12)


@pytest.mark.django_db(transaction=True)
def test_root_successor_roundtrip_and_no_revoked_fallback() -> None:
    repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
    root = _authority()
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=root.recorded_at,
            )
            == root
        )
    with repository.atomic():
        assert (
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=root.recorded_at,
            )
            == root
        )
    revoked = _authority(
        authority_version="v2",
        status="revoked",
        approved_at=_at(10),
        recorded_at=_at(10),
        valid_until=_at(12),
        supersedes_content_hash=root.content_hash,
    )
    with repository.atomic():
        assert (
            repository.append(
                revoked,
                expected_predecessor_hash=root.content_hash,
                recorded_at=revoked.recorded_at,
            )
            == revoked
        )
    assert OwnerTenantAuthorityV1Model.objects.count() == 2
    assert repository.get_head(authority_id=root.authority_id, as_of=_at(11)) == revoked
    assert (
        repository.get_exact(
            authority_id=root.authority_id,
            authority_version=root.authority_version,
            expected_content_hash=root.content_hash,
            as_of=_at(11),
        )
        == root
    )


@pytest.mark.django_db(transaction=True)
def test_private_insert_guard_and_caller_rollback() -> None:
    repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
    root = _authority()
    with pytest.raises(ValidationError):
        OwnerTenantAuthorityV1Model().save()
    with pytest.raises(RuntimeError, match="caller rollback"):
        with repository.atomic():
            repository.append(
                root,
                expected_predecessor_hash=None,
                recorded_at=root.recorded_at,
            )
            raise RuntimeError("caller rollback")
    assert OwnerTenantAuthorityV1Model.objects.count() == 0
    with repository.atomic():
        repository.append(
            root,
            expected_predecessor_hash=None,
            recorded_at=root.recorded_at,
        )
    assert OwnerTenantAuthorityV1Model.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_unrelated_row_tamper_fails_closed_before_selector() -> None:
    repository = DjangoOwnerTenantAuthorityV1Repository(clock=_Clock())
    root = _authority()
    with repository.atomic():
        repository.append(
            root,
            expected_predecessor_hash=None,
            recorded_at=root.recorded_at,
        )
    table = connection.ops.quote_name(OwnerTenantAuthorityV1Model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET tenant_id = %s",  # noqa: S608
            ["tenant-tampered"],
        )
    with pytest.raises(OwnerTenantAuthorityV1Corruption, match="substituted"):
        repository.get_winner(
            authority_id="unrelated-authority",
            authority_version="v0",
            as_of=_at(11),
        )


def test_0055_is_schema_only_zero_seed() -> None:
    migration = import_module("apps.account.migrations.0055_owner_tenant_authority_v1").Migration
    assert migration.dependencies == [("account", "0054_normalize_physical_v2_fixed_constraint")]
    assert migration.operations
    assert all(
        type(operation).__name__ not in {"RunPython", "RunSQL"}
        for operation in migration.operations
    )
