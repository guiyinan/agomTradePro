"""Component proof for the zero-seed scope-source observation ledger."""

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

from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1Observation,
    evidence_scope_source_v1_observation_hash,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.infrastructure.evidence_models import (
    EvidenceScopeSourceV1ObservationModel,
    _activate_evidence_uow,
    _claim_evidence_insert,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the observation table and keep every test zero-seed."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((EvidenceScopeSourceV1ObservationModel,)):
            yield


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id="operator-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _observation(
    *,
    version: str = "v1",
    status: str = "active",
    recorded_at: datetime = NOW,
    valid_until: datetime = NOW + timedelta(hours=1),
) -> EvidenceScopeSourceV1Observation:
    candidate = EvidenceScopeSourceV1Observation(
        observation_id="observation-1",
        observation_version=version,
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=_artifact(),
        status=status,
        recorded_at=recorded_at,
        valid_until=valid_until,
    )
    assert candidate.content_hash == evidence_scope_source_v1_observation_hash(candidate)
    return candidate


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_payload(observation: EvidenceScopeSourceV1Observation) -> dict[str, object]:
    return {
        "account_id": observation.account_id,
        "actor_id": observation.actor_id,
        "artifact": observation.artifact.to_payload(),
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "owner_id": observation.owner_id,
        "recorded_at": _utc_text(observation.recorded_at),
        "status": observation.status,
        "tenant_id": observation.tenant_id,
        "valid_until": _utc_text(observation.valid_until),
    }


def _row_values(observation: EvidenceScopeSourceV1Observation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "owner_id": observation.owner_id,
        "tenant_id": observation.tenant_id,
        "account_id": observation.account_id,
        "actor_id": observation.actor_id,
        "artifact_owner": observation.artifact.owner,
        "artifact_type": observation.artifact.artifact_type,
        "artifact_id": observation.artifact.artifact_id,
        "artifact_version": observation.artifact.artifact_version,
        "artifact_content_hash": observation.artifact.content_hash,
        "status": observation.status,
        "recorded_at": observation.recorded_at,
        "valid_until": observation.valid_until,
        "canonical_payload": _canonical_payload(observation),
        "content_hash": observation.content_hash,
    }


def _insert(values: dict[str, object]) -> EvidenceScopeSourceV1ObservationModel:
    token = object()
    model = EvidenceScopeSourceV1ObservationModel(**values)
    with _activate_evidence_uow(token):
        with _claim_evidence_insert(
            token=token,
            model_type=EvidenceScopeSourceV1ObservationModel,
            expected_values=values,
        ):
            model.save(force_insert=True)
    return model


def test_migration_is_zero_seed_and_exposes_only_the_observation_table() -> None:
    assert EvidenceScopeSourceV1ObservationModel._default_manager.count() == 0
    assert (
        EvidenceScopeSourceV1ObservationModel._meta.db_table
        in connection.introspection.table_names()
    )

    migration_path = (
        Path(__file__).parents[3]
        / "apps"
        / "research"
        / "migrations"
        / "0029_evidence_scope_source_v1_observation_ledger.py"
    )
    migration_text = migration_path.read_text(encoding="utf-8")
    assert migration_text.count("migrations.CreateModel(") == 1
    assert "RunPython" not in migration_text
    assert "RunSQL" not in migration_text
    assert "default=" not in migration_text


def test_exact_insert_round_trips_all_dto_scalars_and_canonical_payload() -> None:
    observation = _observation()
    row = _insert(_row_values(observation))

    assert EvidenceScopeSourceV1ObservationModel._default_manager.count() == 1
    assert row.observation_id == observation.observation_id
    assert row.observation_version == observation.observation_version
    assert row.owner_id == observation.owner_id
    assert row.tenant_id == observation.tenant_id
    assert row.account_id == observation.account_id
    assert row.actor_id == observation.actor_id
    assert row.artifact_owner == observation.artifact.owner
    assert row.artifact_type == observation.artifact.artifact_type
    assert row.artifact_id == observation.artifact.artifact_id
    assert row.artifact_version == observation.artifact.artifact_version
    assert row.artifact_content_hash == observation.artifact.content_hash
    assert row.status == observation.status
    assert row.recorded_at == observation.recorded_at
    assert row.valid_until == observation.valid_until
    assert row.canonical_payload == _canonical_payload(observation)
    assert row.content_hash == observation.content_hash


def test_duplicate_identity_and_content_hash_are_rejected() -> None:
    observation = _observation()
    _insert(_row_values(observation))

    duplicate_identity = _row_values(observation)
    duplicate_identity["content_hash"] = "b" * 64
    with pytest.raises(IntegrityError):
        _insert(duplicate_identity)

    duplicate_content = _row_values(_observation(version="v2"))
    duplicate_content["content_hash"] = observation.content_hash
    with pytest.raises(IntegrityError):
        _insert(duplicate_content)


def test_database_constraints_reject_clock_status_and_artifact_tamper() -> None:
    values = _row_values(_observation())
    values["valid_until"] = NOW
    with pytest.raises(IntegrityError):
        _insert(values)

    values = _row_values(_observation(version="v2"))
    values["status"] = "unknown"
    with pytest.raises(IntegrityError):
        _insert(values)

    values = _row_values(_observation(version="v3"))
    values["artifact_owner"] = "account"
    with pytest.raises(IntegrityError):
        _insert(values)


def test_unclaimed_and_all_mutation_shortcuts_are_rejected() -> None:
    observation = _observation()
    values = _row_values(observation)
    with pytest.raises(ValidationError, match="exact insert claim"):
        EvidenceScopeSourceV1ObservationModel(**values).save(force_insert=True)

    row = _insert(values)
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(raw=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1ObservationModel._default_manager.update(status="revoked")
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1ObservationModel._default_manager.bulk_update([row], ["status"])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1ObservationModel._default_manager.bulk_create([row])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1ObservationModel._default_manager.all()._update([])
    with pytest.raises(ValidationError):
        EvidenceScopeSourceV1ObservationModel._default_manager.all()._raw_delete("default")
