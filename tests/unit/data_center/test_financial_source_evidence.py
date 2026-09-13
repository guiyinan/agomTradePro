"""Typed financial source fields at the pure Domain boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence

SOURCE_HASH = "a" * 64
ANNOUNCED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


def _fact(*, source_evidence: FinancialFactSourceEvidence | None = None) -> FinancialFact:
    """Build one fact without inventing an availability boundary."""

    return FinancialFact(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="revenue",
        value=123.45,
        unit="CNY",
        source="provider-main",
        source_evidence=source_evidence,
    )


def test_financial_source_evidence_round_trips_existing_source_fields() -> None:
    """A complete typed witness preserves all three existing source fields."""

    evidence = FinancialFactSourceEvidence(
        announced_at=ANNOUNCED_AT,
        source_record_id="vendor-record-1",
        raw_payload_hash=SOURCE_HASH,
    )

    fact = _fact(source_evidence=evidence)

    assert fact.source_evidence == evidence
    assert fact.to_dict()["source_evidence"] == {
        "announced_at": ANNOUNCED_AT.isoformat(),
        "source_record_id": "vendor-record-1",
        "raw_payload_hash": SOURCE_HASH,
    }


def test_partial_source_evidence_never_invents_availability_or_announcement() -> None:
    """A raw hash alone remains partial and cannot populate source timestamps."""

    evidence = FinancialFactSourceEvidence(raw_payload_hash=SOURCE_HASH)

    fact = _fact(source_evidence=evidence)

    assert not evidence.is_complete
    assert fact.available_at is None
    payload = fact.to_dict()
    assert payload["available_at"] is None
    assert payload["source_evidence"] == {
        "announced_at": None,
        "source_record_id": None,
        "raw_payload_hash": SOURCE_HASH,
    }


def test_financial_source_evidence_rejects_naive_announcement() -> None:
    """The Domain boundary rejects a source timestamp without timezone proof."""

    with pytest.raises(ValueError, match="timezone-aware"):
        FinancialFactSourceEvidence(
            announced_at=datetime(2026, 9, 14, 8, 0),
            source_record_id="vendor-record-1",
            raw_payload_hash=SOURCE_HASH,
        )
