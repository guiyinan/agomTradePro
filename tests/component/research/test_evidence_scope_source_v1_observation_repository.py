"""Component proof for the read-only Evidence observation provider."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_evidence_scope_source_v1")
django.setup()

from django.db import connection

from apps.research.application.evidence_scope_source_v1_lifecycle import (
    EvidenceScopeSourceV1Observation,
    evidence_scope_source_v1_observation_hash,
)
from apps.research.domain.evidence_contracts import ArtifactRef
from apps.research.infrastructure.evidence_models import EvidenceScopeSourceV1ObservationModel
from apps.research.infrastructure.evidence_scope_source_v1_observation_codec import (
    encode_evidence_scope_source_v1_observation,
)
from apps.research.infrastructure.evidence_scope_source_v1_observation_repository import (
    DjangoEvidenceScopeSourceV1ObservationCorruption,
    DjangoEvidenceScopeSourceV1ObservationRepository,
    DjangoEvidenceScopeSourceV1ObservationUnavailable,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 23, 8, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _NaiveClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 23, 8)


class _FailingClock:
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the observation table and never seed it."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema((EvidenceScopeSourceV1ObservationModel,)):
            yield


def _artifact(identifier: str = "operator-1") -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="evidence_operator_spec",
        artifact_id=identifier,
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _observation(
    *,
    identifier: str = "observation-1",
    version: str = "v1",
    status: str = "active",
    recorded_at: datetime = NOW,
    valid_until: datetime | None = None,
) -> EvidenceScopeSourceV1Observation:
    value = EvidenceScopeSourceV1Observation(
        observation_id=identifier,
        observation_version=version,
        owner_id="owner-1",
        tenant_id="tenant-1",
        account_id="account-1",
        actor_id="actor-1",
        artifact=_artifact(identifier),
        status=status,
        recorded_at=recorded_at,
        valid_until=valid_until or recorded_at + timedelta(hours=1),
    )
    assert value.content_hash == evidence_scope_source_v1_observation_hash(value)
    return value


def _insert(
    value: EvidenceScopeSourceV1Observation,
    *,
    overrides: dict[str, object] | None = None,
) -> None:
    """Insert a test row through SQL, bypassing the production append guard."""

    payload = encode_evidence_scope_source_v1_observation(value)
    artifact = value.artifact
    values: dict[str, object] = {
        "observation_id": value.observation_id,
        "observation_version": value.observation_version,
        "owner_id": value.owner_id,
        "tenant_id": value.tenant_id,
        "account_id": value.account_id,
        "actor_id": value.actor_id,
        "artifact_owner": artifact.owner,
        "artifact_type": artifact.artifact_type,
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "artifact_content_hash": artifact.content_hash,
        "status": value.status,
        "recorded_at": value.recorded_at,
        "valid_until": value.valid_until,
        "canonical_payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "content_hash": value.content_hash,
    }
    if overrides:
        values.update(overrides)
    columns = tuple(values)
    table = connection.ops.quote_name(EvidenceScopeSourceV1ObservationModel._meta.db_table)
    quoted_columns = ", ".join(connection.ops.quote_name(column) for column in columns)
    placeholders = ", ".join("%s" for _ in columns)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders})",
            [values[column] for column in columns],
        )


def _read(value: EvidenceScopeSourceV1Observation, *, clock: object = _Clock()) -> object:
    return DjangoEvidenceScopeSourceV1ObservationRepository(
        clock=clock,  # type: ignore[arg-type]
    ).get_exact_current(
        observation_id=value.observation_id,
        observation_version=value.observation_version,
        expected_content_hash=value.content_hash,
        as_of=NOW,
    )


def test_zero_seed_is_empty_and_provider_has_no_write_surface() -> None:
    """The schema does not create authority observations or expose a writer."""

    value = _observation()
    assert _read(value) is None
    provider = DjangoEvidenceScopeSourceV1ObservationRepository(clock=_Clock())
    assert provider.unit_of_work_key == "django:default"
    assert not hasattr(provider, "append")
    assert not hasattr(provider, "atomic")


def test_exact_active_observation_round_trips_only_at_the_requested_identity() -> None:
    value = _observation()
    _insert(value)

    assert _read(value) == value
    assert (
        DjangoEvidenceScopeSourceV1ObservationRepository(clock=_Clock()).get_exact_current(
            observation_id=value.observation_id,
            observation_version="other-version",
            expected_content_hash=value.content_hash,
            as_of=NOW,
        )
        is None
    )
    assert (
        DjangoEvidenceScopeSourceV1ObservationRepository(clock=_Clock()).get_exact_current(
            observation_id=value.observation_id,
            observation_version=value.observation_version,
            expected_content_hash="b" * 64,
            as_of=NOW,
        )
        is None
    )


def test_recorded_at_future_is_not_visible_at_a_past_cutoff() -> None:
    value = _observation(recorded_at=NOW + timedelta(minutes=1))
    _insert(value)
    assert _read(value) is None


@pytest.mark.parametrize("status", ["revoked"])
def test_revoked_observation_is_not_resurrected(status: str) -> None:
    value = _observation(status=status)
    _insert(value)
    assert _read(value) is None


def test_expired_observation_is_not_resurrected() -> None:
    value = _observation(valid_until=NOW + timedelta(hours=1))
    _insert(value)
    provider = DjangoEvidenceScopeSourceV1ObservationRepository(
        clock=_Clock(NOW + timedelta(hours=2)),
    )
    assert (
        provider.get_exact_current(
            observation_id=value.observation_id,
            observation_version=value.observation_version,
            expected_content_hash=value.content_hash,
            as_of=NOW + timedelta(hours=1),
        )
        is None
    )


def test_future_as_of_and_unavailable_clock_fail_closed() -> None:
    value = _observation()
    for clock in (_Clock(), _NaiveClock(), _FailingClock()):
        provider = DjangoEvidenceScopeSourceV1ObservationRepository(
            clock=clock,  # type: ignore[arg-type]
        )
        if isinstance(clock, _Clock):
            with pytest.raises(
                DjangoEvidenceScopeSourceV1ObservationUnavailable,
                match="future",
            ):
                provider.get_exact_current(
                    observation_id=value.observation_id,
                    observation_version=value.observation_version,
                    expected_content_hash=value.content_hash,
                    as_of=NOW + timedelta(seconds=1),
                )
        else:
            with pytest.raises(DjangoEvidenceScopeSourceV1ObservationUnavailable):
                provider.get_exact_current(
                    observation_id=value.observation_id,
                    observation_version=value.observation_version,
                    expected_content_hash=value.content_hash,
                    as_of=NOW,
                )


def test_unrelated_header_tamper_is_detected_before_exact_selector() -> None:
    wanted = _observation()
    unrelated = _observation(identifier="observation-2")
    _insert(wanted)
    _insert(unrelated, overrides={"tenant_id": "tampered-tenant"})

    with pytest.raises(
        DjangoEvidenceScopeSourceV1ObservationCorruption,
        match="headers",
    ):
        _read(wanted)


def test_canonical_payload_tamper_is_detected_before_exact_selector() -> None:
    value = _observation()
    _insert(value)
    payload = encode_evidence_scope_source_v1_observation(value)
    payload["unexpected"] = True
    table = connection.ops.quote_name(EvidenceScopeSourceV1ObservationModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET canonical_payload = %s WHERE content_hash = %s",
            [json.dumps(payload, ensure_ascii=False, sort_keys=True), value.content_hash],
        )

    with pytest.raises(
        DjangoEvidenceScopeSourceV1ObservationCorruption,
        match="canonical payload",
    ):
        _read(value)


@pytest.mark.parametrize(
    "field, value",
    [
        ("observation_id", ""),
        ("observation_version", " "),
        ("expected_content_hash", "not-a-digest"),
    ],
)
def test_selector_validation_is_strict(field: str, value: str) -> None:
    observation = _observation()
    selectors: dict[str, object] = {
        "observation_id": observation.observation_id,
        "observation_version": observation.observation_version,
        "expected_content_hash": observation.content_hash,
        "as_of": NOW,
    }
    selectors[field] = value
    provider = DjangoEvidenceScopeSourceV1ObservationRepository(clock=_Clock())
    with pytest.raises(ValueError):
        provider.get_exact_current(**selectors)  # type: ignore[arg-type]
