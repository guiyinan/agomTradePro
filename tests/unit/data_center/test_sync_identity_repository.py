"""SQLite component tests for the dormant sync identity persistence boundary."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.data_center.application.sync_identity import SyncExecutionIdentity
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.models import SyncExecutionIdentityModel


def _identity(**changes: object) -> SyncExecutionIdentity:
    values: dict[str, object] = {
        "run_id": str(uuid4()),
        "ingested_run_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "dataset_key": "macro.CN_CPI",
        "provider_name": "provider-a",
    }
    values.update(changes)
    payload = {
        "batch_id": values["batch_id"],
        "dataset_key": values["dataset_key"],
        "ingested_run_id": values["ingested_run_id"],
        "provider_name": values["provider_name"],
        "run_id": values["run_id"],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    identity_hash = hashlib.sha256(
        b"agomtradepro:data-center:sync-execution-identity:v1\0" + encoded
    ).hexdigest()
    return SyncExecutionIdentity(
        **{**values, "identity_hash": identity_hash}  # type: ignore[arg-type]
    )


@pytest.mark.django_db
def test_repository_persists_exact_identity_and_replays_idempotently() -> None:
    identity = _identity()
    repository = SyncExecutionIdentityRepository()

    first = repository.persist(identity)
    second = repository.persist(identity)

    assert first == identity
    assert second == identity
    assert repository.get_by_identity_hash(identity.identity_hash) == identity
    row = SyncExecutionIdentityModel._default_manager.get(identity_hash=identity.identity_hash)
    assert str(row.run_id) == identity.run_id
    assert str(row.ingested_run_id) == identity.ingested_run_id
    assert str(row.batch_id) == identity.batch_id

    row.dataset_key = "macro.tampered"
    with pytest.raises(ValidationError, match="append-only"):
        row.save(update_fields=["dataset_key"])
    with pytest.raises(ValidationError, match="append-only"):
        row.save()
    with pytest.raises(ValidationError, match="append-only"):
        row.save_base(raw=True)
    with pytest.raises(ValidationError, match="append-only"):
        row.delete()
    with pytest.raises(ValidationError, match="append-only"):
        SyncExecutionIdentityModel._default_manager.filter(
            identity_hash=identity.identity_hash
        ).update(dataset_key="macro.tampered")
    with pytest.raises(ValidationError, match="append-only"):
        SyncExecutionIdentityModel._default_manager.filter(
            identity_hash=identity.identity_hash
        ).delete()
    with pytest.raises(ValidationError, match="repository persistence"):
        SyncExecutionIdentityModel._default_manager.bulk_create([row])
    with pytest.raises(ValidationError, match="append-only"):
        SyncExecutionIdentityModel._default_manager.filter(
            identity_hash=identity.identity_hash
        ).bulk_update([row], ["dataset_key"])
    with pytest.raises(ValidationError, match="append-only"):
        SyncExecutionIdentityModel._default_manager.filter(
            identity_hash=identity.identity_hash
        )._raw_delete(using="default")


def test_identity_schema_has_no_generated_authoritative_fields() -> None:
    for field_name in (
        "identity_hash",
        "run_id",
        "ingested_run_id",
        "batch_id",
    ):
        assert not SyncExecutionIdentityModel._meta.get_field(field_name).has_default()


@pytest.mark.django_db
def test_repository_rejects_same_execution_ids_with_different_context() -> None:
    identity = _identity()
    conflicting = _identity(
        run_id=identity.run_id,
        ingested_run_id=identity.ingested_run_id,
        batch_id=identity.batch_id,
        dataset_key="macro.CPI",
    )
    repository = SyncExecutionIdentityRepository()
    repository.persist(identity)

    with pytest.raises(IntegrityError):
        repository.persist(conflicting)


@pytest.mark.django_db
def test_repository_restore_fails_closed_on_raw_context_tamper() -> None:
    identity = _identity()
    repository = SyncExecutionIdentityRepository()
    repository.persist(identity)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_center_sync_execution_identity "
            "SET dataset_key = %s WHERE identity_hash = %s",
            ["macro.tampered", identity.identity_hash],
        )

    with pytest.raises(ValueError, match="identity_hash"):
        repository.get_by_identity_hash(identity.identity_hash)


def test_repository_rejects_noncanonical_identity_hash_selector() -> None:
    with pytest.raises(ValueError, match="identity_hash"):
        SyncExecutionIdentityRepository().get_by_identity_hash("not-a-hash")
