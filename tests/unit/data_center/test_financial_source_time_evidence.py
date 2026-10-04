"""Domain contracts for independently retained financial source-time evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimePrecision,
    FinancialSourceTimeWitness,
)

ANNOUNCED_AT = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 9, 1, 8, 5, tzinfo=UTC)
# 2026-09-01 00:00 Asia/Shanghai and the next calendar day start, in UTC.
DATE_ONLY_ANNOUNCED_AT = datetime(2026, 8, 31, 16, 0, tzinfo=UTC)
DATE_ONLY_AVAILABLE_AT = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
DATE_ONLY_COMPLETED_AT = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)


def _artifact() -> FinancialSourceTimeArtifactRef:
    return FinancialSourceTimeArtifactRef(
        capture_id=UUID("20000000-0000-4000-8000-000000000007"),
        location="financial-source-time/domain.bin",
        provider_name="provider-main",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code="000001.SZ",
        requested_announcement_date=date(2026, 9, 1),
        body_sha256="a" * 64,
        body_size_bytes=96,
        response_completed_at=AVAILABLE_AT,
        response_row_count=1,
        format_version="financial-source-time-artifact.v1",
        encryption_algorithm="fernet",
        encryption_key_ref="config_center.data02.test-key",
        encryption_key_version="v1",
    )


def _witness() -> FinancialSourceTimeWitness:
    return FinancialSourceTimeWitness(
        artifact_reference=_artifact(),
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        financial_native_row_id="provider-main:000001.SZ:20260630:roe",
        financial_announced_date=date(2026, 9, 1),
        source_native_row_id="provider-main:notice:000001.SZ:20260901:1",
        source_timezone="Asia/Shanghai",
        announced_at=ANNOUNCED_AT,
        available_at=AVAILABLE_AT,
        row_projection_sha256="b" * 64,
        governed_match_contract_id="provider-main.financial-announcement.exact",
        governed_match_contract_version="v1",
        governed_match_contract_sha256="c" * 64,
        matched_row_count=1,
        availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
        source_time_precision=FinancialSourceTimePrecision.EXACT,
    )


def test_source_time_witness_projects_exact_artifact_and_row_identity() -> None:
    witness = _witness()

    projection = witness.to_dict()

    assert projection["availability_basis"] == "provider_native_exact"
    assert projection["source_time_precision"] == "exact"
    assert projection["row_projection_sha256"] == "b" * 64
    assert projection["artifact_reference"] == _artifact().to_dict()


def _date_only_witness() -> FinancialSourceTimeWitness:
    artifact = replace(
        _artifact(),
        response_completed_at=DATE_ONLY_COMPLETED_AT,
    )
    return FinancialSourceTimeWitness(
        artifact_reference=artifact,
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        financial_native_row_id="akshare:000001.SZ:2026-06-30:2026-09-01",
        financial_announced_date=date(2026, 9, 1),
        source_native_row_id="akshare:000001.SZ:2026-06-30:2026-09-01",
        source_timezone="Asia/Shanghai",
        announced_at=DATE_ONLY_ANNOUNCED_AT,
        available_at=DATE_ONLY_AVAILABLE_AT,
        row_projection_sha256="b" * 64,
        governed_match_contract_id="akshare.financial-main-data.notice-date",
        governed_match_contract_version="2026-10-04.v1",
        governed_match_contract_sha256="c" * 64,
        matched_row_count=1,
        availability_basis=FinancialAvailabilityBasis.PROVIDER_DATE_NEXT_SESSION,
        source_time_precision=FinancialSourceTimePrecision.DATE,
    )


def test_date_only_witness_records_calendar_day_precision() -> None:
    """Date-only availability uses canonical Asia/Shanghai day starts."""

    witness = _date_only_witness()

    projection = witness.to_dict()

    assert projection["availability_basis"] == "provider_date_next_session"
    assert projection["source_time_precision"] == "date"
    assert projection["announced_at"] == "2026-08-31T16:00:00+00:00"
    assert projection["available_at"] == "2026-09-01T16:00:00+00:00"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_time_precision": FinancialSourceTimePrecision.EXACT},
        {"availability_basis": FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT},
        {"announced_at": DATE_ONLY_ANNOUNCED_AT + timedelta(seconds=1)},
        {"announced_at": DATE_ONLY_ANNOUNCED_AT - timedelta(days=1)},
        {"available_at": DATE_ONLY_AVAILABLE_AT + timedelta(seconds=1)},
        {"available_at": DATE_ONLY_ANNOUNCED_AT},
        {"available_at": DATE_ONLY_COMPLETED_AT + timedelta(seconds=1)},
        {"source_time_precision": "date"},
    ],
)
def test_date_only_witness_rejects_noncanonical_or_inconsistent_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_date_only_witness(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"capture_id": "not-a-uuid"},
        {"dataset_key": "equity.financial.fact"},
        {"requested_announcement_date": datetime(2026, 9, 1, tzinfo=UTC)},
        {"body_sha256": "invalid"},
        {"body_size_bytes": 0},
        {"response_row_count": 0},
        {"response_completed_at": datetime(2026, 9, 1, 8, 5)},
        {"provider_name": " provider-main"},
        {"location": "financial-source-time/domain.bin\n"},
    ],
)
def test_source_time_artifact_rejects_ambiguous_identity(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_artifact(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"artifact_reference": object()},
        {"native_asset_code": "600000.SH"},
        {"native_period_end": datetime(2026, 6, 30, tzinfo=UTC)},
        {"financial_announced_date": datetime(2026, 9, 1, tzinfo=UTC)},
        {"financial_announced_date": date(2026, 8, 31)},
        {"source_timezone": "Unknown/Zone"},
        {"source_native_row_id": "bad\nrow"},
        {"announced_at": datetime(2026, 8, 31, 8, 0, tzinfo=UTC)},
        {"available_at": ANNOUNCED_AT - timedelta(seconds=1)},
        {"available_at": AVAILABLE_AT + timedelta(seconds=1)},
        {"row_projection_sha256": "invalid"},
        {"governed_match_contract_sha256": "invalid"},
        {"matched_row_count": 0},
        {"matched_row_count": 2},
        {"availability_basis": "provider_native_exact"},
        {"availability_basis": FinancialAvailabilityBasis.PROVIDER_DATE_NEXT_SESSION},
        {"source_time_precision": FinancialSourceTimePrecision.DATE},
        {"source_time_precision": "exact"},
    ],
)
def test_source_time_witness_rejects_unbound_or_nonconservative_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_witness(), **changes)
