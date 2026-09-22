"""Exact audit lookup and link decoding for financial source-time artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialSourceTimeArtifactRef,
)
from apps.data_center.infrastructure import provider_state_repositories
from apps.data_center.infrastructure.financial_source_time_audit import (
    SOURCE_TIME_AUDIT_LINK_KEY,
    SOURCE_TIME_AUDIT_LINK_SCHEMA,
    StrictFinancialSourceTimeAuditLinkVerifier,
    source_time_reference_from_audit,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository

CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000009")
COMPLETED_AT = datetime(2026, 8, 28, 7, 32, tzinfo=UTC)


def _reference() -> FinancialSourceTimeArtifactRef:
    return FinancialSourceTimeArtifactRef(
        capture_id=CAPTURE_ID,
        location="financial-source-time/20/20000000-0000-4000-8000-000000000009.bin",
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


def _audit() -> RawAudit:
    reference = _reference()
    audit = RawAudit(
        provider_name=reference.provider_name,
        capability="financial_source_time",
        request_params={},
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
        parser_version="synthetic-notice.v1",
        payload_size_bytes=reference.body_size_bytes,
    )
    return replace(audit, content_hash=raw_audit_content_hash(audit))


def test_source_time_audit_link_round_trips_exact_reference() -> None:
    audit = _audit()
    assert source_time_reference_from_audit(audit) == (_reference(), 7)
    assert StrictFinancialSourceTimeAuditLinkVerifier().verify_source_time(audit, _reference())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", None),
        ("capture_id", "not-a-uuid"),
        ("body_size_bytes", True),
        ("requested_announcement_date", "not-a-date"),
    ],
)
def test_source_time_audit_link_rejects_invalid_exact_fields(
    field: str,
    value: object,
) -> None:
    audit = _audit()
    link = dict(audit.extra[SOURCE_TIME_AUDIT_LINK_KEY])
    link[field] = value
    forged = replace(audit, extra={SOURCE_TIME_AUDIT_LINK_KEY: link})
    with pytest.raises((TypeError, ValueError)):
        source_time_reference_from_audit(forged)


def test_raw_audit_repository_lists_every_source_time_capture_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = object()
    second = object()

    class _Query:
        ordering: tuple[str, ...] = ()

        def order_by(self, *fields: str) -> _Query:
            self.ordering = fields
            return self

        def __iter__(self) -> Iterator[object]:
            return iter((first, second))

    class _Manager:
        filters: dict[str, object] = {}

        def __init__(self, query: _Query) -> None:
            self.query = query

        def filter(self, **filters: object) -> _Query:
            self.filters = filters
            return self.query

    query = _Query()
    manager = _Manager(query)

    class _RawAuditModelModule:
        objects = manager

    monkeypatch.setattr(provider_state_repositories, "RawAuditModel", _RawAuditModelModule)
    monkeypatch.setattr(
        RawAuditRepository,
        "_from_model",
        staticmethod(lambda model: "first" if model is first else "second"),
    )

    rows = RawAuditRepository().list_by_source_time_artifact_capture_id(CAPTURE_ID)

    assert rows == ["first", "second"]
    assert manager.filters == {
        "capability": "financial_source_time",
        "extra__financial_source_time_artifact__capture_id": str(CAPTURE_ID),
    }
    assert query.ordering == ("fetched_at", "pk")
