"""Component proof for the zero-seed Evidence scope-source v1 ledger."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_evidence_scope_source_v1")
django.setup()

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.infrastructure.evidence_models import (
    EvidenceScopeSourceV1Model,
    _activate_evidence_uow,
    _claim_evidence_insert,
)
from apps.research.infrastructure.evidence_scope_source_v1_codec import (
    encode_evidence_scope_source_v1,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the target table, avoiding the full project migration graph."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((EvidenceScopeSourceV1Model,)):
            yield


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _source(
    *, version: str = "v1", previous: EvidenceScopeSourceV1 | None = None
) -> EvidenceScopeSourceV1:
    recorded_at = NOW if previous is None else previous.recorded_at + timedelta(minutes=1)
    valid_until = NOW + timedelta(hours=1)
    root_claim_hash = None
    if previous is None:
        root_claim_hash = root_claim_hash_for_evidence_scope_source_v1(
            source_id="scope-source-1",
            owner_id="owner-1",
            tenant_id="tenant-1",
            account_id="account-1",
            actor_id="actor-1",
            artifact=_artifact(),
        )
    return EvidenceScopeSourceV1(
        source_id="scope-source-1",
        source_version=version,
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=_artifact(),
        status="active",
        recorded_at=recorded_at,
        valid_until=valid_until,
        root_claim_hash=root_claim_hash,
        supersedes_content_hash=None if previous is None else previous.content_hash,
    )


def _row_values(source: EvidenceScopeSourceV1, *, predecessor_id: int | None) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "source_version": source.source_version,
        "owner_id": source.owner_id,
        "tenant_id": source.tenant_id,
        "account_id": source.account_id,
        "actor_id": source.actor_id,
        "artifact_owner": source.artifact.owner,
        "artifact_type": source.artifact.artifact_type,
        "artifact_id": source.artifact.artifact_id,
        "artifact_version": source.artifact.artifact_version,
        "artifact_content_hash": source.artifact.content_hash,
        "status": source.status,
        "recorded_at": source.recorded_at,
        "valid_until": source.valid_until,
        "root_claim_hash": source.root_claim_hash,
        "supersedes_content_hash": source.supersedes_content_hash,
        "predecessor_id": predecessor_id,
        "identity_hash": source.identity_hash,
        "content_hash": source.content_hash,
        "source_owner": source.owner,
        "source_artifact_type": source.artifact_type,
        "source_schema": source.schema,
        "permission": source.permission,
        "must_not_execute": source.must_not_execute,
        "execution_allowed": source.execution_allowed,
        "canonical_payload": encode_evidence_scope_source_v1(source),
        "persisted_at": source.recorded_at,
    }


def _insert(values: dict[str, object]) -> EvidenceScopeSourceV1Model:
    token = object()
    model = EvidenceScopeSourceV1Model(**values)
    with _activate_evidence_uow(token):
        with _claim_evidence_insert(
            token=token,
            model_type=EvidenceScopeSourceV1Model,
            expected_values=values,
        ):
            model.save(force_insert=True)
    return model


def test_migration_is_zero_seed_and_exposes_the_scope_source_table() -> None:
    assert EvidenceScopeSourceV1Model._default_manager.count() == 0
    assert EvidenceScopeSourceV1Model._meta.db_table in connection.introspection.table_names()

    migration_path = (
        Path(__file__).parents[3]
        / "apps"
        / "research"
        / "migrations"
        / "0028_evidence_scope_source_v1.py"
    )
    migration_text = migration_path.read_text(encoding="utf-8")
    assert migration_text.count("migrations.CreateModel(") == 1
    assert "RunPython" not in migration_text
    assert "RunSQL" not in migration_text


def test_private_exact_insert_supports_root_and_adjacent_successor() -> None:
    root = _source()
    root_row = _insert(_row_values(root, predecessor_id=None))
    successor = _source(version="v2", previous=root)
    successor_row = _insert(_row_values(successor, predecessor_id=root_row.pk))

    assert EvidenceScopeSourceV1Model._default_manager.count() == 2
    assert successor_row.predecessor_id == root_row.pk
    assert successor_row.root_claim_hash is None
    assert successor_row.supersedes_content_hash == root.content_hash


def test_unclaimed_and_all_mutation_shortcuts_are_rejected() -> None:
    source = _source()
    with pytest.raises(ValidationError, match="exact insert claim"):
        EvidenceScopeSourceV1Model(**_row_values(source, predecessor_id=None)).save(
            force_insert=True
        )

    row = _insert(_row_values(source, predecessor_id=None))
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(raw=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1Model._default_manager.update(status="revoked")
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1Model._default_manager.bulk_update([row], ["status"])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1Model._default_manager.bulk_create([row])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1Model._default_manager.all()._update([])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1Model._default_manager.all()._raw_delete("default")


def test_database_constraints_reject_clock_fixed_and_chain_tamper() -> None:
    source = _source()
    values = _row_values(source, predecessor_id=None)
    values["persisted_at"] = source.recorded_at + timedelta(seconds=1)
    with pytest.raises(IntegrityError):
        _insert(values)

    values = _row_values(source, predecessor_id=None)
    values["persisted_at"] = source.recorded_at
    values["execution_allowed"] = True
    with pytest.raises(IntegrityError):
        _insert(values)

    values = _row_values(source, predecessor_id=None)
    values["root_claim_hash"] = None
    values["supersedes_content_hash"] = None
    with pytest.raises(IntegrityError):
        _insert(values)
