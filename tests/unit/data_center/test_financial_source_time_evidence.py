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
    FinancialSourceTimeWitness,
)

ANNOUNCED_AT = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
AVAILABLE_AT = datetime(2026, 9, 1, 8, 5, tzinfo=UTC)


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
    )


def test_source_time_witness_projects_exact_artifact_and_row_identity() -> None:
    witness = _witness()

    projection = witness.to_dict()

    assert projection["availability_basis"] == "provider_native_exact"
    assert projection["row_projection_sha256"] == "b" * 64
    assert projection["artifact_reference"] == _artifact().to_dict()


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
    ],
)
def test_source_time_witness_rejects_unbound_or_nonconservative_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        replace(_witness(), **changes)
