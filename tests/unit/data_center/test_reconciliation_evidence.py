"""Persistence and Application Port tests for shadow reconciliation evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command

from apps.data_center.application.reconciliation import RecordReconciliationEvidenceUseCase
from apps.data_center.domain.reconciliation import (
    ReconciliationClassification,
    ReconciliationDifference,
    ReconciliationReport,
)
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    ReconciliationEvidenceRepository,
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
    saved = RecordReconciliationEvidenceUseCase(ReconciliationEvidenceRepository()).execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=observed_at,
    )

    loaded = ReconciliationEvidenceRepository().get_latest("equity.price.bar")

    assert loaded == saved
    assert loaded is not None
    assert loaded.report.counts["same"] == 1
    assert loaded.report.counts["semantic_conflict"] == 1
    assert loaded.report.is_clean is False
    assert loaded.legacy_snapshot_hash == "legacy-hash"
    assert loaded.observed_at == observed_at


@pytest.mark.django_db
def test_reconciliation_evidence_save_is_idempotent_for_same_evidence_id() -> None:
    """Repeating a write updates one evidence record instead of duplicating it."""

    repository = ReconciliationEvidenceRepository()
    evidence_id = str(uuid4())
    first = RecordReconciliationEvidenceUseCase(repository).execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash",
        canonical_snapshot_hash="canonical-hash",
        observed_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    second = RecordReconciliationEvidenceUseCase(repository).execute(
        _report(),
        evidence_id=evidence_id,
        legacy_snapshot_hash="legacy-hash-v2",
        canonical_snapshot_hash="canonical-hash-v2",
        observed_at=datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
    )

    rows = repository.list_recent("equity.price.bar")
    assert first.evidence_id == second.evidence_id == evidence_id
    assert len(rows) == 1
    assert rows[0].legacy_snapshot_hash == "legacy-hash-v2"


@pytest.mark.django_db
def test_reconciliation_command_hashes_snapshots_and_persists_report(tmp_path) -> None:
    """The maintenance command produces reproducible evidence from JSON exports."""

    legacy_path = tmp_path / "legacy.json"
    canonical_path = tmp_path / "canonical.json"
    legacy_path.write_text('{"row-1": {"close": 10}}', encoding="utf-8")
    canonical_path.write_text('{"row-1": {"close": 10}}', encoding="utf-8")
    output = StringIO()
    evidence_id = str(uuid4())

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
