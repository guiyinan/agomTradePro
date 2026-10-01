"""Pure-domain tests for candidate RawAudit manifest identity and hashing."""

from __future__ import annotations

from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
)

PUBLICATION_ID = "f1e76a4d-b1e3-4cdc-bb12-2129fc3a3f90"
PUBLICATION_HASH = "a" * 64
PUBLICATION_RUN_ID = "76235a4b-3c31-45c5-8a2c-50d111136e4b"


def _reference(
    raw_audit_id: str,
    *,
    run_id: str = "eb8ef399-0fd1-4b98-92dc-1d6a9ed6d7e8",
    ingested_run_id: str = "e0f83191-7c1c-4c0b-93a7-319087d25ce2",
) -> CandidateRawAuditReference:
    return CandidateRawAuditReference(
        raw_audit_id=raw_audit_id,
        version="1",
        content_hash=str(int(raw_audit_id)).zfill(64),
        provider_name="provider-main",
        capability="historical_price",
        run_id=run_id,
        ingested_run_id=ingested_run_id,
    )


def _manifest(
    references: tuple[CandidateRawAuditReference, ...] = (_reference("2"), _reference("1")),
    *,
    task_attempt_id: str = "market-refresh-task-attempt-4",
    manifest_id: str = "40172406-38bf-4e03-a3d1-3de5c4cf1317",
) -> CandidateRawAuditManifest:
    return CandidateRawAuditManifest.create(
        publication_id=PUBLICATION_ID,
        publication_hash=PUBLICATION_HASH,
        run_id=PUBLICATION_RUN_ID,
        dataset_key="equity.daily_price",
        publication_key="2026-09-30",
        task_attempt_id=task_attempt_id,
        raw_audits=references,
        manifest_id=manifest_id,
    )


def test_manifest_sorts_references_and_binds_publication_and_task_attempt() -> None:
    first = _manifest()
    second = _manifest((_reference("1"), _reference("2")))

    assert [item.raw_audit_id for item in first.raw_audits] == ["1", "2"]
    assert first.raw_audit_count == 2
    assert first.raw_audit_hash == second.raw_audit_hash
    assert first.manifest_hash == second.manifest_hash
    assert (
        first.manifest_hash
        == _manifest(manifest_id="a35cfa0f-394d-479f-90b1-932cb9e04058").manifest_hash
    )
    assert _manifest(task_attempt_id="market-refresh-task-attempt-5").manifest_hash != (
        first.manifest_hash
    )


def test_manifest_rejects_empty_or_duplicate_raw_audit_sets() -> None:
    try:
        _manifest(())
    except CandidateRawAuditManifestError as exc:
        assert "requires RawAudit references" in str(exc)
    else:
        raise AssertionError("empty RawAudit set should be rejected")

    try:
        _manifest((_reference("1"), _reference("1")))
    except CandidateRawAuditManifestError as exc:
        assert "must be unique" in str(exc)
    else:
        raise AssertionError("duplicate RawAudit references should be rejected")


def test_reference_fails_closed_without_exact_run_and_ingestion_identity() -> None:
    try:
        _reference("3", ingested_run_id="")
    except CandidateRawAuditManifestError as exc:
        assert "ingested_run_id must be a UUID" in str(exc)
    else:
        raise AssertionError("unbound historical RawAudit must be rejected")


def test_manifest_requires_explicit_task_attempt_identity() -> None:
    try:
        _manifest(task_attempt_id=" ")
    except CandidateRawAuditManifestError as exc:
        assert "task_attempt_id" in str(exc)
    else:
        raise AssertionError("missing task attempt must be rejected")
