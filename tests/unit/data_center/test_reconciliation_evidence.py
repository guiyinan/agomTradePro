"""Persistence and Application Port tests for shadow reconciliation evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command

from apps.audit.application.data_conflict_audit import DataConflictAuditObservation
from apps.data_center.application.reconciliation import (
    RecordReconciliationEvidenceUseCase,
    reconciliation_evidence_content_hash,
)
from apps.data_center.domain.reconciliation import (
    ReconciliationClassification,
    ReconciliationDifference,
    ReconciliationReport,
)
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    DjangoReconciliationEvidenceUnitOfWork,
    ReconciliationEvidenceRepository,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _AuditWriter:
    """Typed collecting writer for the intended canonical conflict event."""

    def __init__(self) -> None:
        self.observations: list[DataConflictAuditObservation] = []
        self.fail = False

    @property
    def database_alias(self) -> str:
        return "default"

    def write(self, observation: DataConflictAuditObservation) -> None:
        if self.fail:
            raise RuntimeError("conflict audit writer failure")
        self.observations.append(observation)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _recorder(
    repository: ReconciliationEvidenceRepository | None = None,
    writer: _AuditWriter | None = None,
) -> tuple[
    RecordReconciliationEvidenceUseCase,
    ReconciliationEvidenceRepository,
    _AuditWriter,
]:
    evidence_repository = repository or ReconciliationEvidenceRepository()
    audit_writer = writer or _AuditWriter()
    return (
        RecordReconciliationEvidenceUseCase(
            evidence_repository,
            audit_writer=audit_writer,
            unit_of_work=DjangoReconciliationEvidenceUnitOfWork(
                evidence_repository,
                audit_writer,
            ),
            clock=_Clock(),
        ),
        evidence_repository,
        audit_writer,
    )


def _report() -> ReconciliationReport:
    """Build a report containing a resolved and an unresolved difference."""

    return ReconciliationReport(
        dataset_key="equity.price.bar",
        rows=(
            ReconciliationDifference(
                natural_key="000001.SZ|2026-08-01",
                classification=ReconciliationClassification.SAME,
                legacy_value={"close": 10.0},
                canonical_value={"close": 10.0},
            ),
            ReconciliationDifference(
                natural_key="000002.SZ|2026-08-01",
                classification=ReconciliationClassification.SEMANTIC_CONFLICT,
                legacy_value={"close": 10.0},
                canonical_value={"close": 11.0},
            ),
        ),
    )


def test_reconciliation_evidence_rejects_naive_observation_time() -> None:
    """Evidence must preserve a timezone-aware observation boundary."""

    from apps.data_center.domain.reconciliation import ReconciliationEvidence

    with pytest.raises(ValueError, match="timezone-aware"):
        ReconciliationEvidence(
            evidence_id=str(uuid4()),
            report=_report(),
            legacy_snapshot_hash="legacy-hash",
            canonical_snapshot_hash="canonical-hash",
            observed_at=datetime(2026, 8, 1, 12, 0),
        )


@pytest.mark.django_db
def test_reconciliation_evidence_round_trip_preserves_categories_and_hashes() -> None:
    """A persisted report remains queryable as typed evidence."""

    evidence_id = str(uuid4())
    observed_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    use_case, repository, _writer = _recorder()
    saved = use_case.execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=observed_at,
    )

    loaded = repository.get_latest("equity.price.bar")

    assert loaded == saved
    assert loaded is not None
    assert loaded.report.counts["same"] == 1
    assert loaded.report.counts["semantic_conflict"] == 1
    assert loaded.report.is_clean is False
    assert loaded.legacy_snapshot_hash == "legacy-hash"
    assert loaded.observed_at == observed_at


@pytest.mark.django_db
def test_reconciliation_evidence_save_replays_exact_identity_without_mutation() -> None:
    """An exact retry is idempotent but a conflicting retry cannot rewrite history."""

    repository = ReconciliationEvidenceRepository()
    use_case, _repository, _writer = _recorder(repository)
    evidence_id = str(uuid4())
    first = use_case.execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    second = use_case.execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    rows = repository.list_recent("equity.price.bar")
    assert first.evidence_id == second.evidence_id == evidence_id
    assert len(rows) == 1
    assert rows[0].legacy_snapshot_hash == "legacy-hash"

    with pytest.raises(ValueError, match="already contains a different snapshot"):
        use_case.execute(
            _report(),
            evidence_id=evidence_id,
            legacy_snapshot_hash="legacy-hash-v2",
            canonical_snapshot_hash="canonical-hash-v2",
            observed_at=datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
        )

    rows_after_conflict = repository.list_recent("equity.price.bar")
    assert len(rows_after_conflict) == 1
    assert rows_after_conflict[0] == first


@pytest.mark.django_db
def test_reconciliation_command_hashes_snapshots_and_persists_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The maintenance command produces reproducible evidence from JSON exports."""

    legacy_path = tmp_path / "legacy.json"
    canonical_path = tmp_path / "canonical.json"
    legacy_path.write_text('{"row-1": {"close": 10}}', encoding="utf-8")
    canonical_path.write_text('{"row-1": {"close": 10}}', encoding="utf-8")
    output = StringIO()
    evidence_id = str(uuid4())
    recorder, _repository, _writer = _recorder()

    def _make_recorder() -> RecordReconciliationEvidenceUseCase:
        return recorder

    monkeypatch.setattr(
        "apps.data_center.application.public.make_reconciliation_evidence_recorder",
        _make_recorder,
    )

    call_command(
        "record_data_center_reconciliation",
        "equity.price.bar",
        str(legacy_path),
        str(canonical_path),
        evidence_id=evidence_id,
        observed_at="2026-08-01T12:00:00+00:00",
        stdout=output,
    )

    loaded = ReconciliationEvidenceRepository().get_latest("equity.price.bar")
    assert loaded is not None
    assert loaded.evidence_id == evidence_id
    assert loaded.report.is_clean is True
    assert len(loaded.legacy_snapshot_hash) == 64
    assert "clean=True" in output.getvalue()
    assert f"legacy_hash={loaded.legacy_snapshot_hash}" in output.getvalue()
    assert f"canonical_hash={loaded.canonical_snapshot_hash}" in output.getvalue()
    assert 'classification_evidence=[{"classification":"same","natural_key":"row-1"}]' in (
        output.getvalue()
    )


@pytest.mark.django_db
def test_conflict_audit_and_evidence_share_one_unit_of_work() -> None:
    """The conflict event must reference the immutable row written atomically."""

    writer = _AuditWriter()
    use_case, _repository, _writer = _recorder(writer=writer)

    evidence = use_case.execute(
        _report(),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    assert evidence.report.is_clean is False
    assert len(writer.observations) == 1
    observation = writer.observations[0]
    assert observation.transition == "detected"
    assert observation.conflict_count == 1
    assert observation.previous_conflict_count is None
    assert observation.evidence_id == evidence.evidence_id
    assert observation.evidence_version == "1"
    assert observation.evidence_content_hash == reconciliation_evidence_content_hash(evidence)


def _clean_report() -> ReconciliationReport:
    return ReconciliationReport(
        dataset_key="equity.price.bar",
        rows=(
            ReconciliationDifference(
                natural_key="000001.SZ|2026-08-01",
                classification=ReconciliationClassification.SAME,
                legacy_value={"close": 10.0},
                canonical_value={"close": 10.0},
            ),
        ),
    )


@pytest.mark.django_db
def test_conflict_to_clean_emits_one_resolved_transition_with_previous_evidence() -> None:
    use_case, _repository, writer = _recorder()
    first = use_case.execute(
        _report(),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-conflict",
        canonical_snapshot_hash="canonical-conflict",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    resolved = use_case.execute(
        _clean_report(),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-clean",
        canonical_snapshot_hash="canonical-clean",
        observed_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )

    assert [item.transition for item in writer.observations] == ["detected", "resolved"]
    observation = writer.observations[1]
    assert observation.evidence_id == resolved.evidence_id
    assert observation.conflict_count == 0
    assert observation.previous_conflict_count == 1
    assert observation.previous_evidence_id == first.evidence_id
    assert observation.previous_evidence_content_hash == reconciliation_evidence_content_hash(first)


@pytest.mark.django_db
def test_clean_to_clean_persists_evidence_without_conflict_event() -> None:
    use_case, repository, writer = _recorder()

    use_case.execute(
        _clean_report(),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-clean-1",
        canonical_snapshot_hash="canonical-clean-1",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    use_case.execute(
        _clean_report(),
        evidence_id=str(uuid4()),
        legacy_snapshot_hash="legacy-clean-2",
        canonical_snapshot_hash="canonical-clean-2",
        observed_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
    )

    assert len(repository.list_recent("equity.price.bar")) == 2
    assert writer.observations == []


@pytest.mark.django_db(transaction=True)
def test_required_conflict_writer_failure_rolls_back_evidence() -> None:
    repository = ReconciliationEvidenceRepository()
    writer = _AuditWriter()
    writer.fail = True
    use_case, _repository, _writer = _recorder(repository, writer)

    with pytest.raises(RuntimeError, match="conflict audit writer failure"):
        use_case.execute(
            _report(),
            evidence_id=str(uuid4()),
            legacy_snapshot_hash="legacy-hash",
            canonical_snapshot_hash="canonical-hash",
            observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        )

    assert repository.get_latest("equity.price.bar") is None
