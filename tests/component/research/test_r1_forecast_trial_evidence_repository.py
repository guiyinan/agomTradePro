"""SQLite component evidence for the Research R1 trial preregistration ledger."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models.deletion import Collector

from apps.equity.application.forecast_baseline_materialize import VersionRef
from apps.research.application.r1_forecast_trial_evidence import (
    R1ForecastTrialEvidenceUnavailable,
)
from apps.research.domain.r1_forecast_trial_evidence import R1ForecastTrialDefinition
from apps.research.infrastructure.r1_forecast_trial_evidence_models import (
    R1ForecastTrialEvidenceLedgerModel,
)
from apps.research.infrastructure.r1_forecast_trial_evidence_repository import (
    R1ForecastTrialEvidenceConflict,
    R1ForecastTrialEvidenceCorruption,
)
from apps.research.r1_forecast_trial_evidence_composition import (
    _build_private_r1_forecast_trial_evidence_runtime,
    build_r1_forecast_trial_evidence_runtime,
)
from tests.unit.research.test_r1_forecast_trial_evidence import (
    ORIGIN,
    _BaselineProvider,
    _Clock,
    _command,
    _DefinitionProvider,
    _graph,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _private_runtime(
    definition: R1ForecastTrialDefinition | None = None,
):
    spec, artifact, default_definition = _graph()
    return _build_private_r1_forecast_trial_evidence_runtime(
        definition_provider=_DefinitionProvider(
            default_definition if definition is None else definition,
            unit_of_work_key="django:default",
        ),
        baseline_provider=_BaselineProvider(
            spec,
            artifact,
            unit_of_work_key="django:default",
        ),
        clock=_Clock(unit_of_work_key="django:default"),
    )


def _definition_version(
    definition: R1ForecastTrialDefinition,
    version: str,
) -> R1ForecastTrialDefinition:
    return R1ForecastTrialDefinition.create(
        definition_id=definition.definition_id,
        definition_version=version,
        baseline_spec_id=definition.baseline_spec_id,
        baseline_spec_version=definition.baseline_spec_version,
        baseline_spec_content_hash=definition.baseline_spec_content_hash,
        baseline_artifact_id=definition.baseline_artifact_id,
        baseline_artifact_version=definition.baseline_artifact_version,
        baseline_artifact_content_hash=definition.baseline_artifact_content_hash,
        split_spec_hash=definition.split_spec_hash,
        parameter_hash=definition.parameter_hash,
        calendar_id=definition.calendar_id,
        calendar_version=definition.calendar_version,
        calendar_schedule_hash=definition.calendar_schedule_hash,
        expected_period_ends=definition.expected_period_ends,
        metric_codes=definition.metric_codes,
        evaluation_policy=definition.evaluation_policy,
        activated_at=definition.activated_at,
        valid_until=definition.valid_until,
    )


def test_private_runtime_roundtrip_exact_pit_and_equity_projection() -> None:
    runtime = _private_runtime()

    receipt = runtime.registration.execute(_command())
    projected = runtime.equity_provider.get_trial(
        VersionRef(receipt.evidence_id, receipt.evidence_version),
        as_of=ORIGIN,
    )

    assert projected is not None
    assert projected.identity.content_hash == receipt.content_hash
    assert projected.baseline_spec_content_hash == receipt.definition.baseline_spec_content_hash
    assert projected.evaluation_policy == receipt.definition.evaluation_policy
    assert (
        runtime.equity_provider.get_trial(VersionRef(receipt.evidence_id, "missing"), as_of=ORIGIN)
        is None
    )
    assert (
        runtime.repository.get_exact(
            evidence_id=receipt.evidence_id,
            evidence_version=receipt.evidence_version,
            as_of=receipt.definition.activated_at - timedelta(seconds=1),
        )
        is None
    )


def test_identical_winner_version_fork_and_conflicting_fork_are_exact() -> None:
    spec, artifact, definition = _graph()
    runtime = _private_runtime(definition)
    first = runtime.registration.execute(_command())
    assert runtime.registration.execute(_command()) == first
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 1

    definition_v2 = _definition_version(definition, "v2")
    runtime_v2 = _build_private_r1_forecast_trial_evidence_runtime(
        definition_provider=_DefinitionProvider(definition_v2, unit_of_work_key="django:default"),
        baseline_provider=_BaselineProvider(spec, artifact, unit_of_work_key="django:default"),
        clock=_Clock(unit_of_work_key="django:default"),
    )
    fork_command = replace(
        _command(),
        evidence_version="v2",
        definition_version="v2",
    )
    second = runtime_v2.registration.execute(fork_command)
    assert second.evidence_version == "v2"
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 2

    conflicting = replace(fork_command, evidence_version="v1")
    with pytest.raises(R1ForecastTrialEvidenceConflict):
        runtime_v2.registration.execute(conflicting)
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 2


def test_owner_graph_replacement_and_outer_rollback_leave_zero_rows() -> None:
    spec, artifact, definition = _graph()
    changed = _definition_version(definition, "v2")
    runtime = _build_private_r1_forecast_trial_evidence_runtime(
        definition_provider=_DefinitionProvider(
            definition,
            reads=(definition, changed),
            unit_of_work_key="django:default",
        ),
        baseline_provider=_BaselineProvider(spec, artifact, unit_of_work_key="django:default"),
        clock=_Clock(unit_of_work_key="django:default"),
    )
    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="changed"):
        runtime.registration.execute(_command())
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 0

    class _Rollback(Exception):
        pass

    with pytest.raises(_Rollback), transaction.atomic():
        _private_runtime().registration.execute(_command())
        raise _Rollback
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 0


def test_public_runtime_is_inert_read_only_and_empty_db_means_r1_blocked() -> None:
    runtime = build_r1_forecast_trial_evidence_runtime()

    assert not hasattr(runtime.repository, "append")
    assert runtime.equity_provider.__slots__ == ("_repository",)
    assert (
        runtime.equity_provider.get_trial(VersionRef("research-trial-001", "v1"), as_of=ORIGIN)
        is None
    )
    with pytest.raises(R1ForecastTrialEvidenceUnavailable, match="production-inert"):
        runtime.registration.execute(_command())
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 0


def test_orm_queryset_bulk_and_collector_mutation_guards() -> None:
    runtime = _private_runtime()
    runtime.registration.execute(_command())
    row = R1ForecastTrialEvidenceLedgerModel.objects.get()

    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.save_base()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R1ForecastTrialEvidenceLedgerModel.objects.update(evidence_version="fork")
    with pytest.raises(ValidationError):
        R1ForecastTrialEvidenceLedgerModel.objects.all().delete()
    with pytest.raises(ValidationError):
        R1ForecastTrialEvidenceLedgerModel.objects.bulk_create(
            [R1ForecastTrialEvidenceLedgerModel()]
        )
    collector = Collector(using="default")
    collector.collect([row])
    with pytest.raises(ValidationError):
        collector.delete()
    assert R1ForecastTrialEvidenceLedgerModel.objects.count() == 1


def test_header_substitution_is_detected_by_exact_reader() -> None:
    runtime = _private_runtime()
    receipt = runtime.registration.execute(_command())
    table = R1ForecastTrialEvidenceLedgerModel._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "{table}" SET definition_content_hash = %s WHERE evidence_id = %s',
            ["0" * 64, receipt.evidence_id],
        )

    with pytest.raises(R1ForecastTrialEvidenceCorruption, match="header"):
        runtime.repository.get_exact(
            evidence_id=receipt.evidence_id,
            evidence_version=receipt.evidence_version,
            as_of=ORIGIN,
        )
