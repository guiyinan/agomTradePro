"""Contract-neutral retention for provider-native financial source-time bodies."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from apps.data_center.application.financial_source_time_artifact import (
    FinancialSourceTimeArtifactAuditError,
    FinancialSourceTimeArtifactReplayConflictError,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.infrastructure.financial_source_time_artifact_repository import (
    FinancialSourceTimeArtifactRepository,
)
from apps.data_center.infrastructure.financial_source_time_audit import (
    source_time_reference_from_audit,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    FinancialSourceTimeBodyStore,
)

CAPTURE_ID = UUID("30000000-0000-4000-8000-000000000003")
BODY = b'{"notice_id":"notice-1","asset_code":"000001.SZ"}'
COMPLETED_AT = datetime(2026, 8, 28, 7, 32, tzinfo=UTC)
ANNOUNCEMENT_DATE = date(2026, 8, 28)


class _AuditRepository:
    def __init__(self, *, fail_log: bool = False) -> None:
        self.rows: list[RawAudit] = []
        self.fail_log = fail_log
        self.log_calls = 0

    def list_by_source_time_artifact_capture_id(self, capture_id: UUID) -> list[RawAudit]:
        return [
            row
            for row in self.rows
            if row.extra["financial_source_time_artifact"]["capture_id"] == str(capture_id)
        ]

    def log_source_time(self, audit: RawAudit) -> RawAudit:
        self.log_calls += 1
        if self.fail_log:
            raise RuntimeError("audit unavailable")
        persisted = replace(
            audit,
            raw_audit_id=str(self.log_calls),
            content_hash=raw_audit_content_hash(audit),
        )
        self.rows.append(persisted)
        return persisted


def _store(tmp_path: Path) -> FinancialSourceTimeBodyStore:
    return FinancialSourceTimeBodyStore(
        tmp_path,
        encryption_key=Fernet.generate_key(),
        encryption_key_ref="test/financial-source-time-key",
        encryption_key_version="test-v1",
        max_body_bytes=1024 * 1024,
    )


def _retain(
    repository: FinancialSourceTimeArtifactRepository,
    *,
    provider_id: int = 7,
    request_params: dict[str, object] | None = None,
):
    return repository.retain(
        capture_id=CAPTURE_ID,
        provider_name="provider-main",
        provider_id=provider_id,
        requested_asset_code="000001.SZ",
        requested_announcement_date=ANNOUNCEMENT_DATE,
        body=BODY,
        response_completed_at=COMPLETED_AT,
        response_row_count=1,
        request_params=request_params or {"api_name": "provider_notice", "asset_code": "000001.SZ"},
        parser_version="provider-notice.v1",
    )


def test_retention_persists_exact_encrypted_body_and_canonical_audit(tmp_path: Path) -> None:
    audits = _AuditRepository()
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), audits)

    retained = _retain(repository)

    assert retained.reference.body_sha256 == hashlib.sha256(BODY).hexdigest()
    assert retained.reference.requested_announcement_date == ANNOUNCEMENT_DATE
    assert retained.audit.response_payload_hash == retained.reference.body_sha256
    assert retained.audit.content_hash == raw_audit_content_hash(retained.audit)
    assert source_time_reference_from_audit(retained.audit) == (retained.reference, 7)
    assert repository.read(retained.reference) == BODY
    assert BODY not in next(tmp_path.rglob("*.bin")).read_bytes()
    assert "announced_at" not in retained.audit.extra["financial_source_time_artifact"]
    assert "available_at" not in retained.audit.extra["financial_source_time_artifact"]


def test_exact_replay_is_idempotent_and_changed_provider_id_conflicts(tmp_path: Path) -> None:
    audits = _AuditRepository()
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), audits)

    first = _retain(repository)
    replay = _retain(repository)

    assert replay == first
    assert audits.log_calls == 1
    assert len(audits.rows) == 1
    with pytest.raises(FinancialSourceTimeArtifactReplayConflictError):
        _retain(repository, provider_id=8)


def test_duplicate_audits_fail_closed_before_body_replay(tmp_path: Path) -> None:
    audits = _AuditRepository()
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), audits)
    first = _retain(repository)
    audits.rows.append(replace(first.audit, raw_audit_id="duplicate"))

    with pytest.raises(FinancialSourceTimeArtifactReplayConflictError):
        _retain(repository)


def test_audit_append_failure_exposes_verified_orphan(tmp_path: Path) -> None:
    audits = _AuditRepository(fail_log=True)
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), audits)

    with pytest.raises(FinancialSourceTimeArtifactAuditError) as caught:
        _retain(repository)

    orphan = repository.inspect_orphan(caught.value.reference)
    assert orphan.is_orphan is True
    assert orphan.is_ambiguous is False
    assert orphan.body_verified is True
    assert orphan.audit_count == 0
    assert BODY.decode() not in str(caught.value)


def test_retention_rejects_credential_shaped_request_dimensions(tmp_path: Path) -> None:
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), _AuditRepository())

    with pytest.raises(ValueError, match="credential"):
        _retain(repository, request_params={"authorization": "secret"})


def test_orphan_inspection_exposes_ambiguous_audit_cardinality(tmp_path: Path) -> None:
    audits = _AuditRepository()
    repository = FinancialSourceTimeArtifactRepository(_store(tmp_path), audits)
    retained = _retain(repository)
    audits.rows.append(replace(retained.audit, raw_audit_id="duplicate"))

    result = repository.inspect_orphan(retained.reference)

    assert result.is_orphan is False
    assert result.is_ambiguous is True
    assert result.audit_count == 2
