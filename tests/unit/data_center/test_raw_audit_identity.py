from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _audit(**changes: object) -> RawAudit:
    values: dict[str, object] = {
        "provider_name": "provider-a",
        "capability": "macro",
        "request_params": {"indicator": "CN_CPI", "start": "2026-01-01"},
        "status": "ok",
        "row_count": 2,
        "fetched_at": NOW,
        "extra": {"source": "test"},
        "raw_audit_id": "17",
        "run_id": "run-1",
        "ingested_run_id": "ingested-1",
    }
    values.update(changes)
    return RawAudit(**values)  # type: ignore[arg-type]


def test_content_hash_is_canonical_and_binds_correlations() -> None:
    audit = _audit(extra={"z": 2, "a": 1})
    reordered = _audit(extra={"a": 1, "z": 2})

    first = raw_audit_content_hash(audit)
    assert first == raw_audit_content_hash(reordered)
    assert len(first) == 64

    bound = replace(audit, content_hash=first)
    reference = bound.exact_reference()
    assert reference.raw_audit_id == "17"
    assert reference.run_id == "run-1"
    assert reference.ingested_run_id == "ingested-1"
    assert reference.content_hash == first


def test_content_hash_changes_when_audited_content_changes() -> None:
    original = raw_audit_content_hash(_audit())
    changed_status = raw_audit_content_hash(_audit(status="error"))
    changed_run = raw_audit_content_hash(_audit(run_id="run-2"))

    assert changed_status != original
    assert changed_run != original


def test_legacy_row_cannot_become_fetch_event_reference() -> None:
    legacy = RawAudit(
        provider_name="provider-a",
        capability="macro",
        request_params={},
        status="ok",
        fetched_at=NOW,
        raw_audit_id="17",
    )

    with pytest.raises(ValueError, match="run_id"):
        legacy.exact_reference()


def test_reference_rejects_missing_or_noncanonical_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        _audit(content_hash="").exact_reference()
    with pytest.raises(ValueError, match="lowercase sha256"):
        _audit(content_hash="A" * 64).exact_reference()
