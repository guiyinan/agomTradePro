"""Financial publication policy3 source provenance contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    publication_fact_reference_for_dataset,
)

ANNOUNCED_AT = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
AVAILABLE_AT = ANNOUNCED_AT + timedelta(minutes=5)
FETCHED_AT = AVAILABLE_AT + timedelta(minutes=5)
PUBLISHED_AT = FETCHED_AT + timedelta(minutes=5)
FINANCIAL_DATASET = "equity.financial.fact"
SOURCE_HASH = "a" * 64


def _row(
    *,
    announced_at: datetime | None = ANNOUNCED_AT,
    available_at: datetime | None = AVAILABLE_AT,
    fetched_at: datetime | None = FETCHED_AT,
    source_record_id: str = "provider-record-1",
    raw_payload_hash: str = SOURCE_HASH,
    extra: dict[str, object] | None = None,
) -> FinancialFactModel:
    """Build an unsaved ORM row with explicit source provenance fields."""

    return FinancialFactModel(
        pk=1,
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="quarterly",
        metric_code="revenue",
        value=Decimal("123.4500"),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 9),
        fetched_at=fetched_at,
        extra=extra if extra is not None else {"raw_payload_scope": "record_response_body"},
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
        announced_at=announced_at,
        available_at=available_at,
    )


def _policy(version: str, required_evidence: tuple[str, ...]) -> PublicationPolicy:
    """Build a financial policy with the requested immutable version."""

    return PublicationPolicy(
        dataset=DatasetKey(FINANCIAL_DATASET, "1.0", "1.0"),
        minimum_coverage_ratio=1.0,
        allow_partial=True,
        conflict_action="quarantine",
        required_evidence=required_evidence,
        retention_days=3650,
        policy_version=version,
    )


def _policy3() -> PublicationPolicy:
    """Return the strict financial policy3 evidence contract."""

    return _policy(
        "3",
        (
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
            "source_record_id",
            "published_at",
            "raw_payload_hash",
            "raw_payload_scope",
        ),
    )


def _policy2() -> PublicationPolicy:
    """Return the archived versioned contract that used normalized fallback evidence."""

    return _policy(
        "2",
        (
            "source",
            "observed_at",
            "available_at",
            "fetched_at",
            "payload_hash",
            "fact_content_hash",
        ),
    )


def test_policy3_accepts_only_original_financial_source_evidence() -> None:
    """A complete ORM source witness maps announced_at to published_at."""

    reference = publication_fact_reference_for_dataset(
        _row(),
        dataset_key=FINANCIAL_DATASET,
        require_verified_source_evidence=True,
    )

    assert reference.source_record_id == "provider-record-1"
    assert reference.raw_payload_hash == SOURCE_HASH
    assert reference.raw_payload_scope == "record_response_body"
    assert reference.source_published_at == ANNOUNCED_AT
    validate_publication_evidence(_policy3(), [reference], published_at=PUBLISHED_AT)


def test_policy3_rejects_missing_source_record_id_without_natural_key_fallback() -> None:
    """A blank source record ID cannot be replaced with the natural key."""

    with pytest.raises(ValueError, match="source_record_id"):
        publication_fact_reference_for_dataset(
            _row(source_record_id=""),
            dataset_key=FINANCIAL_DATASET,
            require_verified_source_evidence=True,
        )


def test_policy3_rejects_missing_raw_hash_without_normalized_row_fallback() -> None:
    """A blank raw hash cannot be replaced with the normalized row digest."""

    with pytest.raises(ValueError, match="raw_payload_hash"):
        publication_fact_reference_for_dataset(
            _row(raw_payload_hash=""),
            dataset_key=FINANCIAL_DATASET,
            require_verified_source_evidence=True,
        )


def test_policy3_rejects_announcement_after_source_availability() -> None:
    """A source announcement after availability is an impossible witness."""

    with pytest.raises(ValueError, match="announced_at"):
        publication_fact_reference_for_dataset(
            _row(announced_at=AVAILABLE_AT + timedelta(seconds=1)),
            dataset_key=FINANCIAL_DATASET,
            require_verified_source_evidence=True,
        )


def test_policy2_keeps_normalized_fallback_for_legacy_rows() -> None:
    """Archived policy2 can still read rows written before source provenance."""

    row = _row(
        announced_at=None,
        source_record_id="",
        raw_payload_hash="",
        extra={},
    )
    reference = publication_fact_reference_for_dataset(row, dataset_key=FINANCIAL_DATASET)

    assert reference.source_record_id == reference.natural_key
    assert reference.raw_payload_hash
    assert reference.source_published_at is None
    assert reference.raw_payload_scope == ""
    validate_publication_evidence(_policy2(), [reference], published_at=PUBLISHED_AT)
