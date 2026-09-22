"""Database evidence for exact-one financial source-time RawAudit claims."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import UUID

import pytest
from django.db import close_old_connections, connection

from apps.data_center.application.financial_source_time_artifact import (
    SOURCE_TIME_AUDIT_CAPABILITY,
    SOURCE_TIME_AUDIT_LINK_KEY,
    SOURCE_TIME_AUDIT_LINK_SCHEMA,
)
from apps.data_center.domain.entities import RawAudit
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialSourceTimeArtifactRef,
)
from apps.data_center.infrastructure.financial_source_time_audit_repository import (
    DjangoFinancialSourceTimeArtifactAuditRepository,
)
from apps.data_center.infrastructure.models import (
    FinancialSourceTimeAuditClaimModel,
    RawAuditModel,
)

pytestmark = pytest.mark.django_db(transaction=True)

CAPTURE_ID = UUID("40000000-0000-4000-8000-000000000004")
COMPLETED_AT = datetime(2026, 8, 28, 7, 32, tzinfo=UTC)


def _audit(*, parser_version: str = "provider-notice.v1") -> RawAudit:
    """Build one complete candidate for repository persistence."""

    reference = FinancialSourceTimeArtifactRef(
        capture_id=CAPTURE_ID,
        location="financial-source-time/40/40000000-0000-4000-8000-000000000004.bin",
        provider_name="provider-main",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code="000001.SZ",
        requested_announcement_date=date(2026, 8, 28),
        body_sha256="a" * 64,
        body_size_bytes=42,
        response_completed_at=COMPLETED_AT,
        response_row_count=1,
        format_version="financial-source-time-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    return RawAudit(
        provider_name=reference.provider_name,
        capability=SOURCE_TIME_AUDIT_CAPABILITY,
        request_params={"asset_code": "000001.SZ"},
        status="ok",
        row_count=reference.response_row_count,
        fetched_at=reference.response_completed_at,
        extra={
            SOURCE_TIME_AUDIT_LINK_KEY: {
                "schema": SOURCE_TIME_AUDIT_LINK_SCHEMA,
                **reference.to_dict(),
                "provider_id": 7,
            }
        },
        response_payload_hash=reference.body_sha256,
        redacted=True,
        parser_version=parser_version,
        payload_size_bytes=reference.body_size_bytes,
    )


def test_source_time_claim_replays_one_audit_and_rejects_drift() -> None:
    repository = DjangoFinancialSourceTimeArtifactAuditRepository()

    first = repository.log_source_time(_audit())
    replay = repository.log_source_time(_audit())

    assert replay.raw_audit_id == first.raw_audit_id
    assert RawAuditModel.objects.filter(capability=SOURCE_TIME_AUDIT_CAPABILITY).count() == 1
    claim = FinancialSourceTimeAuditClaimModel.objects.get(capture_id=CAPTURE_ID)
    assert str(claim.audit_id) == first.raw_audit_id
    with pytest.raises(ValueError, match="conflicts"):
        repository.log_source_time(_audit(parser_version="provider-notice.v2"))


def test_concurrent_source_time_replay_has_one_raw_audit() -> None:
    """Prove concurrent identical writers converge on one persistent identity."""

    barrier = Barrier(2)

    def _retain(_: int) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return (
                DjangoFinancialSourceTimeArtifactAuditRepository()
                .log_source_time(_audit())
                .raw_audit_id
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        identities = list(executor.map(_retain, (1, 2)))

    assert len(set(identities)) == 1
    assert RawAuditModel.objects.filter(capability=SOURCE_TIME_AUDIT_CAPABILITY).count() == 1
    assert FinancialSourceTimeAuditClaimModel.objects.filter(capture_id=CAPTURE_ID).count() == 1
