"""Persistence contract for Data Center R1 evaluation actual evidence."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector

from apps.data_center.application.evaluation_actual_manifest import (
    EvaluationActualConflict,
    EvaluationActualCorruption,
    EvaluationActualUnavailable,
    MaterializeEvaluationActualManifestCommand,
    RegisterEvaluationActualSourceCommand,
)
from apps.data_center.domain.evaluation_actual_manifest import (
    ActualEvidenceIdentity,
    CanonicalEvaluationActualFact,
    CanonicalEvaluationActualGraph,
    EvaluationActualCoveragePolicy,
    EvaluationActualSourceDefinition,
    ExpectedActualMemberRule,
)
from apps.data_center.evaluation_actual_manifest_composition import (
    _build_django_evaluation_actual_test_runtime,
    _DjangoEvaluationActualTestRuntime,
    build_django_evaluation_actual_runtime,
)
from apps.data_center.infrastructure.evaluation_actual_manifest_models import (
    EvaluationActualManifestReceiptModel,
    EvaluationActualSourceDefinitionModel,
)
from apps.equity.application.forecast_baseline_materialize import VersionRef

pytestmark = pytest.mark.django_db(transaction=True)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
REGISTERED_AT = datetime(2025, 1, 1, 9, tzinfo=UTC)
CUTOFF = datetime(2025, 3, 3, 9, tzinfo=UTC)
VALID_UNTIL = datetime(2026, 1, 1, 9, tzinfo=UTC)
PERIOD_END = date(2025, 2, 28)


def _identity(prefix: str, digest: str) -> ActualEvidenceIdentity:
    return ActualEvidenceIdentity(
        stable_id=f"{prefix}:revenue:2025-02",
        version=f"{prefix}.v1",
        content_hash=digest,
    )


def _definition() -> EvaluationActualSourceDefinition:
    return EvaluationActualSourceDefinition.create(
        source_id="actual-source:600519",
        source_version="source.v1",
        owner="data_center",
        dataset="research.operating-actual.v1",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        calendar=ActualEvidenceIdentity(
            stable_id="calendar:monthly",
            version="calendar.v1",
            content_hash=HASH_A,
        ),
        knowledge_scope="public",
        expected_members=(
            ExpectedActualMemberRule(
                period_end=PERIOD_END,
                metric_code="revenue",
                member=_identity("member", HASH_B),
                vintage=_identity("vintage", HASH_C),
            ),
        ),
        coverage_policy=EvaluationActualCoveragePolicy(
            require_verified=True,
            minimum_coverage_ratio=Decimal("1"),
            maximum_missing_count=0,
            maximum_estimated_count=0,
            maximum_unknown_count=0,
        ),
        registered_at=REGISTERED_AT,
        valid_until=VALID_UNTIL,
    )


def _fact(*, value: Decimal = Decimal("104")) -> CanonicalEvaluationActualFact:
    return CanonicalEvaluationActualFact(
        dataset="research.operating-actual.v1",
        subject_code="600519.SH",
        industry_code="consumer-staples",
        period_end=PERIOD_END,
        metric_code="revenue",
        value=value,
        unit="CNY",
        source_fact=_identity("fact", HASH_D),
        revision_number=1,
        effective_at=datetime(2025, 2, 28, 9, tzinfo=UTC),
        available_at=datetime(2025, 3, 1, 9, tzinfo=UTC),
        member=_identity("member", HASH_B),
        vintage=_identity("vintage", HASH_C),
        quality="verified",
    )


def _graph(*, value: Decimal = Decimal("104")) -> CanonicalEvaluationActualGraph:
    definition = _definition()
    return CanonicalEvaluationActualGraph(
        source_definition=definition.identity,
        as_of_time=CUTOFF,
        knowledge_scope="public",
        facts=(_fact(value=value),),
    )


class _Clock:
    unit_of_work_key = "django:default"

    def now(self) -> datetime:
        return CUTOFF


class _DefinitionProvider:
    unit_of_work_key = "django:default"

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvaluationActualSourceDefinition | None:
        definition = _definition()
        if (
            source_id != definition.source_id
            or source_version != definition.source_version
            or as_of < definition.registered_at
        ):
            return None
        return definition


class _GraphProvider:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.value = Decimal("104")
        self.sequence: list[CanonicalEvaluationActualGraph | None] = []

    def get_exact(
        self,
        *,
        definition: EvaluationActualSourceDefinition,
        as_of: datetime,
    ) -> CanonicalEvaluationActualGraph | None:
        if self.sequence:
            return self.sequence.pop(0)
        graph = _graph(value=self.value)
        if definition.identity != graph.source_definition or as_of != CUTOFF:
            return None
        return graph


def _commands() -> tuple[
    RegisterEvaluationActualSourceCommand,
    MaterializeEvaluationActualManifestCommand,
]:
    return (
        RegisterEvaluationActualSourceCommand(
            source_id="actual-source:600519",
            source_version="source.v1",
            as_of=CUTOFF,
        ),
        MaterializeEvaluationActualManifestCommand(
            manifest_id="actual-manifest:600519:2025-02",
            manifest_version="manifest.v1",
            source_id="actual-source:600519",
            source_version="source.v1",
            as_of=CUTOFF,
        ),
    )


def _runtime(graph_provider: _GraphProvider) -> _DjangoEvaluationActualTestRuntime:
    return _build_django_evaluation_actual_test_runtime(
        definition_provider=_DefinitionProvider(),
        graph_provider=graph_provider,
        clock=_Clock(),
    )


def test_empty_production_read_is_none_and_mutation_is_inert() -> None:
    runtime = build_django_evaluation_actual_runtime()
    register, materialize = _commands()

    assert (
        runtime.actual_provider.get_actual_manifest(
            VersionRef(materialize.manifest_id, materialize.manifest_version),
            as_of=datetime.now(UTC),
        )
        is None
    )
    with pytest.raises(EvaluationActualUnavailable, match="canonical owner"):
        runtime.register_source.execute(register)
    with pytest.raises(EvaluationActualUnavailable, match="canonical owner"):
        runtime.materialize.execute(materialize)
    assert not hasattr(runtime.register_source, "_writer")
    assert not hasattr(runtime.materialize, "_writer")
    assert not hasattr(runtime.actual_provider, "_store")
    assert EvaluationActualSourceDefinitionModel._default_manager.count() == 0
    assert EvaluationActualManifestReceiptModel._default_manager.count() == 0


def test_private_synthetic_owner_builds_full_graph_and_exact_pit_projection() -> None:
    graph_provider = _GraphProvider()
    runtime = _runtime(graph_provider)
    register, materialize = _commands()

    source = runtime.register_source.execute(register)
    manifest = runtime.materialize.execute(materialize)
    snapshot = runtime.actual_provider.get_actual_manifest(
        VersionRef(manifest.manifest_id, manifest.manifest_version),
        as_of=CUTOFF,
    )

    assert source.definition == _definition()
    assert snapshot is not None
    assert snapshot.identity.content_hash == manifest.manifest_content_hash
    assert snapshot.actuals[0].pit_manifest_hash == manifest.manifest_content_hash
    assert snapshot.actuals[0].observation_hash
    assert snapshot.selected_versions_hash == manifest.selected_versions_hash
    assert (
        runtime.actual_provider.get_actual_manifest(
            VersionRef(manifest.manifest_id, manifest.manifest_version),
            as_of=CUTOFF - timedelta(microseconds=1),
        )
        is None
    )
    assert (
        runtime.actual_provider.get_actual_manifest(
            VersionRef(manifest.manifest_id, "manifest.v2"),
            as_of=CUTOFF,
        )
        is None
    )


def test_exact_replay_returns_winner_and_fork_conflicts_without_extra_rows() -> None:
    graph_provider = _GraphProvider()
    runtime = _runtime(graph_provider)
    register, materialize = _commands()

    first_source = runtime.register_source.execute(register)
    first_manifest = runtime.materialize.execute(materialize)
    assert runtime.register_source.execute(register) == first_source
    assert runtime.materialize.execute(materialize) == first_manifest

    graph_provider.value = Decimal("105")
    with pytest.raises(EvaluationActualConflict):
        runtime.materialize.execute(materialize)
    assert EvaluationActualSourceDefinitionModel._default_manager.count() == 1
    assert EvaluationActualManifestReceiptModel._default_manager.count() == 1


def test_graph_reread_substitution_rolls_back_the_outer_registration() -> None:
    graph_provider = _GraphProvider()
    runtime = _runtime(graph_provider)
    register, materialize = _commands()

    with pytest.raises(EvaluationActualUnavailable, match="changed"):
        with transaction.atomic():
            runtime.register_source.execute(register)
            graph_provider.sequence = [_graph(), _graph(value=Decimal("105"))]
            runtime.materialize.execute(materialize)

    assert EvaluationActualSourceDefinitionModel._default_manager.count() == 0
    assert EvaluationActualManifestReceiptModel._default_manager.count() == 0


def test_headers_are_live_checked_and_all_public_mutation_paths_are_guarded() -> None:
    runtime = _runtime(_GraphProvider())
    register, materialize = _commands()
    runtime.register_source.execute(register)
    runtime.materialize.execute(materialize)
    source = EvaluationActualSourceDefinitionModel._default_manager.get()
    receipt = EvaluationActualManifestReceiptModel._default_manager.get()

    for row in (source, receipt):
        with pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError):
            row.delete()
        with pytest.raises(ValidationError):
            type(row)._default_manager.filter(pk=row.pk).update(owner="other")
        with pytest.raises(ValidationError):
            type(row)._default_manager.filter(pk=row.pk).delete()
        with pytest.raises(ValidationError):
            type(row)._default_manager.bulk_create([row])
        with pytest.raises(ValidationError):
            type(row)._default_manager.create()
        with pytest.raises(ValidationError):
            row.save_base(force_update=True)
        private_queryset = type(row)._base_manager.filter(pk=row.pk)
        with pytest.raises(ValidationError):
            private_queryset._raw_delete("default")
        with pytest.raises(ValidationError):
            private_queryset._update([])
        with pytest.raises(ValidationError):
            private_queryset._batched_insert([], [], 1)

    collector = Collector(using="default")
    collector.collect([receipt])
    with pytest.raises(ValidationError):
        with transaction.atomic():
            collector.delete()
    assert EvaluationActualManifestReceiptModel._default_manager.count() == 1

    receipt.canonical_payload = {
        **receipt.canonical_payload,
        "receipt_hash": "e" * 64,
    }
    with pytest.raises(ValidationError):
        receipt.save(update_fields=["canonical_payload"])
    assert (
        runtime.repository.get_manifest(
            manifest_id=materialize.manifest_id,
            manifest_version=materialize.manifest_version,
            as_of=CUTOFF,
        )
        is not None
    )


def test_corrupt_payload_is_not_returned_as_an_exact_snapshot() -> None:
    runtime = _runtime(_GraphProvider())
    register, materialize = _commands()
    runtime.register_source.execute(register)
    runtime.materialize.execute(materialize)
    row = EvaluationActualManifestReceiptModel._default_manager.get()
    corrupted = {**row.canonical_payload, "receipt_hash": "e" * 64}
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_center_evaluation_actual_manifest "
            "SET canonical_payload = %s WHERE id = %s",
            [json.dumps(corrupted), row.pk],
        )

    with pytest.raises(EvaluationActualCorruption):
        runtime.repository.get_manifest(
            manifest_id=materialize.manifest_id,
            manifest_version=materialize.manifest_version,
            as_of=CUTOFF,
        )
