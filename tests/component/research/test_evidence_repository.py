"""Component proof for append-only Research Evidence persistence."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import django
import pytest
from django.core.exceptions import ValidationError
from django.db import connection

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_evidence_repository")
django.setup()

from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    DependencyFlag,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    GovernanceState,
    MethodKind,
    MetricDirection,
    TrackRecordSnapshot,
)
from apps.research.infrastructure.evidence_models import (
    EvidenceEnvelopeModel,
    EvidenceOperatorSpecModel,
    EvidenceTrackRecordModel,
)
from apps.research.infrastructure.evidence_repository import (
    DjangoEvidenceRepository,
    EvidenceRepositoryClock,
    EvidenceRepositoryConflict,
    EvidenceRepositoryCorruption,
    EvidenceRepositoryUnavailable,
    _build_evidence_store,
)
from tests.support.isolated_schema import isolated_schema

NOW = datetime(2026, 8, 12, 8, tzinfo=UTC)
LATER = NOW + timedelta(days=30)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _NaiveClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 12, 8)


class _FailingClock:
    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    """Create only the three evidence tables used by this component module."""

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(
            (EvidenceOperatorSpecModel, EvidenceTrackRecordModel, EvidenceEnvelopeModel)
        ):
            yield


def _artifact(identifier: str, digest: str) -> ArtifactRef:
    return ArtifactRef("research", "scenario_forecast", identifier, "v1", digest * 64)


def _spec() -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="scenario-forecast",
        operator_version="v1",
        research_family="scenario",
        output_artifact_type="scenario_forecast",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=("features",),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=True,
        activated_at=NOW - timedelta(days=1),
        valid_until=LATER,
    )


def _track() -> TrackRecordSnapshot:
    artifact = _artifact("forecast-1", "a")
    return TrackRecordSnapshot(
        snapshot_id="track-1",
        snapshot_version="v1",
        artifact=artifact,
        target="scenario-probability",
        horizon="21d",
        sample_policy_id="oos-policy",
        sample_policy_version="v1",
        evaluated_at=NOW - timedelta(minutes=1),
        valid_until=LATER,
        eligible=10,
        resolved=10,
        unresolved=0,
        censored=0,
        invalidated=0,
        n_eff=Decimal(10),
        coverage=Decimal(1),
        market_regimes=("growth",),
        primary_metric_code="brier",
        primary_metric_unit="score",
        metric_direction=MetricDirection.LOWER_IS_BETTER,
        primary_metric_value=Decimal("0.17"),
        benchmark_metric_value=Decimal("0.22"),
        skill_delta=Decimal("0.05"),
        confidence_interval_low=Decimal("0.01"),
        confidence_interval_high=Decimal("0.09"),
        drift_detected=False,
        promotion_ref=ArtifactRef("research", "promotion", "p1", "v1", "b" * 64),
        outcome_refs=(),
        content_hash="",
    )


def _envelope() -> EvidenceEnvelope:
    spec = _spec()
    return EvidenceEnvelope(
        output_artifact=_artifact("forecast-1", "a"),
        operator_spec_ref=spec.artifact_ref,
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        research_family="scenario",
        governance_state=GovernanceState.RESEARCH_ONLY,
        permission=DecisionPermission.DISPLAY_ONLY,
        lineage=(spec.artifact_ref,),
        dependency_flags=frozenset({DependencyFlag.ESTIMATED_INPUT}),
        track_record_ref=_track().artifact_ref,
        blockers=(),
        evaluated_at=NOW,
        valid_until=LATER,
        content_hash="",
    )


def test_private_store_round_trips_three_exact_idempotent_winners() -> None:
    """All ledger types append once, replay exactly, and support public PIT reads."""

    store = _build_evidence_store()
    spec, track, envelope = _spec(), _track(), _envelope()
    with store.atomic():
        assert store.append_operator_spec(spec, recorded_at=NOW) == spec
        assert store.append_operator_spec(spec, recorded_at=NOW) == spec
        assert store.append_track_record(track, recorded_at=NOW) == track
        assert store.append_track_record(track, recorded_at=NOW) == track
        assert store.append_envelope(envelope, recorded_at=NOW) == envelope
        assert store.append_envelope(envelope, recorded_at=NOW) == envelope

    assert EvidenceOperatorSpecModel._default_manager.count() == 1
    assert EvidenceTrackRecordModel._default_manager.count() == 1
    assert EvidenceEnvelopeModel._default_manager.count() == 1
    reader = DjangoEvidenceRepository()
    assert (
        reader.get_operator_spec(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            expected_content_hash=spec.content_hash,
            as_of=NOW,
        )
        == spec
    )
    assert (
        reader.get_track_record(
            snapshot_id=track.snapshot_id,
            snapshot_version=track.snapshot_version,
            expected_content_hash=track.content_hash,
            as_of=NOW,
        )
        == track
    )
    output = envelope.output_artifact
    assert (
        reader.get_envelope(
            output_owner=output.owner,
            output_artifact_type=output.artifact_type,
            output_artifact_id=output.artifact_id,
            output_artifact_version=output.artifact_version,
            expected_content_hash=envelope.content_hash,
            as_of=NOW,
        )
        == envelope
    )


def test_identity_forks_fail_closed_without_second_rows() -> None:
    """Same stable identity with different canonical content is a conflict."""

    store = _build_evidence_store()
    spec, track, envelope = _spec(), _track(), _envelope()
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=NOW)
        store.append_track_record(track, recorded_at=NOW)
        store.append_envelope(envelope, recorded_at=NOW)
        with pytest.raises(EvidenceRepositoryConflict, match="forks"):
            store.append_operator_spec(
                replace(spec, requires_track_record=False, content_hash=""), recorded_at=NOW
            )
        with pytest.raises(EvidenceRepositoryConflict, match="forks"):
            store.append_track_record(
                replace(track, drift_detected=True, content_hash=""), recorded_at=NOW
            )
        with pytest.raises(EvidenceRepositoryConflict, match="forks"):
            store.append_envelope(
                replace(envelope, valid_until=LATER - timedelta(days=1), content_hash=""),
                recorded_at=NOW,
            )

    assert EvidenceOperatorSpecModel._default_manager.count() == 1
    assert EvidenceTrackRecordModel._default_manager.count() == 1
    assert EvidenceEnvelopeModel._default_manager.count() == 1


@pytest.mark.parametrize(
    "model_type",
    [EvidenceOperatorSpecModel, EvidenceTrackRecordModel, EvidenceEnvelopeModel],
)
def test_every_orm_mutation_and_delete_shortcut_is_rejected(model_type: type) -> None:
    """Model, QuerySet, manager, bulk, private and raw-save paths cannot mutate rows."""

    store = _build_evidence_store()
    with store.atomic():
        store.append_operator_spec(_spec(), recorded_at=NOW)
        store.append_track_record(_track(), recorded_at=NOW)
        store.append_envelope(_envelope(), recorded_at=NOW)
    row = model_type._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base(raw=True)
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        model_type._default_manager.update(content_hash="0" * 64)
    with pytest.raises(ValidationError):
        model_type._default_manager.bulk_update([row], ["content_hash"])
    with pytest.raises(ValidationError):
        model_type._default_manager.bulk_create([row], update_conflicts=True)
    with pytest.raises(ValidationError):
        model_type._default_manager.all()._update([])
    with pytest.raises(ValidationError):
        model_type._default_manager.all()._raw_delete("default")


def test_raw_sql_header_tamper_is_detected_by_strict_restore() -> None:
    """Database-side substitution cannot be published as valid Domain evidence."""

    store = _build_evidence_store()
    spec = _spec()
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=NOW)
    table = connection.ops.quote_name(EvidenceOperatorSpecModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET research_family = %s WHERE content_hash = %s",
            ["tampered", spec.content_hash],
        )
    with pytest.raises(EvidenceRepositoryCorruption, match="headers"):
        DjangoEvidenceRepository().get_operator_spec(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            expected_content_hash=spec.content_hash,
            as_of=NOW,
        )


def test_public_reader_and_unclaimed_model_are_write_inert() -> None:
    """Public construction exposes no writer and direct inserts lack the claim."""

    reader = DjangoEvidenceRepository()
    assert not hasattr(reader, "append_operator_spec")
    with pytest.raises(ValidationError, match="insert claim"):
        EvidenceOperatorSpecModel(operator_id="forbidden").save(force_insert=True)


def test_public_reader_rejects_future_pit_cutoff() -> None:
    """A caller cannot query evidence from a server-future cutoff."""

    reader = DjangoEvidenceRepository(clock=_Clock())
    with pytest.raises(ValueError, match="future evidence as_of"):
        reader.get_operator_spec(
            operator_id="operator-1",
            operator_version="v1",
            expected_content_hash="a" * 64,
            as_of=NOW + timedelta(seconds=1),
        )


def test_append_rejects_future_recorded_at_for_every_ledger_without_rows() -> None:
    """Caller-supplied persistence clocks cannot move beyond the repository clock."""

    store = _build_evidence_store(clock=_Clock())
    spec, track, envelope = _spec(), _track(), _envelope()
    future = NOW + timedelta(seconds=1)
    with store.atomic():
        with pytest.raises(EvidenceRepositoryConflict, match="recorded_at.*future"):
            store.append_operator_spec(spec, recorded_at=future)
        with pytest.raises(EvidenceRepositoryConflict, match="recorded_at.*future"):
            store.append_track_record(track, recorded_at=future)
        with pytest.raises(EvidenceRepositoryConflict, match="recorded_at.*future"):
            store.append_envelope(envelope, recorded_at=future)
    assert EvidenceOperatorSpecModel._default_manager.count() == 0
    assert EvidenceTrackRecordModel._default_manager.count() == 0
    assert EvidenceEnvelopeModel._default_manager.count() == 0


@pytest.mark.parametrize("clock", [_NaiveClock(), _FailingClock()])
def test_append_fails_closed_when_server_clock_is_unavailable(
    clock: EvidenceRepositoryClock,
) -> None:
    """A malformed or unavailable server clock cannot authorize evidence writes."""

    store = _build_evidence_store(clock=clock)
    with store.atomic():
        with pytest.raises(EvidenceRepositoryUnavailable, match="server clock"):
            store.append_operator_spec(_spec(), recorded_at=NOW)
    assert EvidenceOperatorSpecModel._default_manager.count() == 0
