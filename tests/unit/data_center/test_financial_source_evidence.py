"""Typed financial source fields at the pure Domain boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)

SOURCE_HASH = "a" * 64
ANNOUNCED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
PERIOD_END = date(2026, 6, 30)


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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_record_id", 1, "must be text"),
        ("source_record_id", " padded", "cannot be padded"),
        ("raw_payload_hash", 1, "must be text"),
        ("raw_payload_hash", " padded", "cannot be padded"),
    ],
)
def test_financial_source_evidence_rejects_invalid_text_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    """Dynamic source fields are narrowed before entering decision logic."""

    with pytest.raises(ValueError, match=message):
        FinancialFactSourceEvidence(**{field: value})


def _artifact_reference(
    *,
    dataset_key: str = "equity.financial.fact",
    asset_code: str = "000001.SZ",
    period_ends: tuple[date, ...] = (PERIOD_END,),
    row_count: int = 1,
    basis: FinancialResponseScopeBasis = FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
) -> FinancialResponseArtifactRef:
    response_assets = (asset_code,) if row_count else ()
    response_periods = period_ends if row_count else ()
    return FinancialResponseArtifactRef(
        capture_id=UUID("20000000-0000-4000-8000-000000000005"),
        location="financial-response/domain-evidence.bin",
        evidence=FinancialResponseEvidence(
            body_sha256=SOURCE_HASH,
            body_size_bytes=128,
            response_completed_at=ANNOUNCED_AT,
            request_scope=FinancialRequestScope(
                provider_name="provider-main",
                dataset_key=dataset_key,
                asset_code=asset_code,
                period_limit=1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=response_assets,
                period_ends=response_periods,
                row_count=row_count,
            ),
            response_scope_basis=basis,
        ),
        format_version="financial-response-artifact.v1",
        encryption_algorithm="fernet",
        encryption_key_ref="config_center.data02.test-key",
        encryption_key_version="v1",
    )


def test_financial_decision_evidence_serializes_bound_identity() -> None:
    """The public projection exposes hashes and native identity without storage secrets."""

    evidence = FinancialFactDecisionEvidence(
        artifact_reference=_artifact_reference(),
        native_asset_code="000001.SZ",
        native_period_end=PERIOD_END,
        native_row_id="vendor-row-1",
    )

    assert evidence.to_dict() == {
        "capture_id": "20000000-0000-4000-8000-000000000005",
        "body_sha256": SOURCE_HASH,
        "body_scope": "batch_response_body",
        "response_scope_basis": "provider_body_verified",
        "native_asset_code": "000001.SZ",
        "native_period_end": "2026-06-30",
        "native_row_id": "vendor-row-1",
    }


@pytest.mark.parametrize(
    ("reference", "native_asset", "native_period", "native_row", "message"),
    [
        (
            _artifact_reference(dataset_key="other.dataset"),
            "000001.SZ",
            PERIOD_END,
            "row",
            "dataset",
        ),
        (
            _artifact_reference(basis=FinancialResponseScopeBasis.CALLER_DECLARED),
            "000001.SZ",
            PERIOD_END,
            "row",
            "body verified",
        ),
        (_artifact_reference(), "600000.SH", PERIOD_END, "row", "request asset"),
        (_artifact_reference(row_count=0), "000001.SZ", PERIOD_END, "row", "contains no rows"),
        (
            _artifact_reference(period_ends=(date(2026, 3, 31),)),
            "000001.SZ",
            PERIOD_END,
            "row",
            "outside response scope",
        ),
        (_artifact_reference(), "", PERIOD_END, "row", "native_asset_code"),
        (_artifact_reference(), "000001.SZ", PERIOD_END, " padded", "native_row_id"),
        (_artifact_reference(), "000001.SZ", datetime(2026, 6, 30), "row", "must be a date"),
    ],
)
def test_financial_decision_evidence_rejects_invalid_bindings(
    reference: FinancialResponseArtifactRef,
    native_asset: str,
    native_period: date,
    native_row: str,
    message: str,
) -> None:
    """Each decision-critical dimension fails closed independently."""

    with pytest.raises(ValueError, match=message):
        FinancialFactDecisionEvidence(
            artifact_reference=reference,
            native_asset_code=native_asset,
            native_period_end=native_period,
            native_row_id=native_row,
        )


def test_financial_decision_evidence_requires_a_typed_artifact_reference() -> None:
    """A mapping that resembles an artifact cannot cross the Domain boundary."""

    reference = _artifact_reference()
    with pytest.raises(ValueError, match="must be typed"):
        FinancialFactDecisionEvidence(
            artifact_reference=cast(
                FinancialResponseArtifactRef,
                replace(reference, location="valid").to_dict(),
            ),
            native_asset_code="000001.SZ",
            native_period_end=PERIOD_END,
            native_row_id="row",
        )
