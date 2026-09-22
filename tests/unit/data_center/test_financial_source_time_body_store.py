"""Authenticated storage for independently retained source-time bytes."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialSourceTimeArtifactRef,
)
from apps.data_center.infrastructure.financial_source_time_body_store import (
    ENCRYPTION_ALGORITHM,
    FORMAT_VERSION,
    FinancialSourceTimeArtifactError,
    FinancialSourceTimeBodyStore,
    source_time_location_for,
)

CAPTURE_ID = UUID("20000000-0000-4000-8000-000000000010")
BODY = b'{"rows":[{"notice_id":"notice-1"}]}'


def _reference(*, key_version: str = "v1") -> FinancialSourceTimeArtifactRef:
    return FinancialSourceTimeArtifactRef(
        capture_id=CAPTURE_ID,
        location=source_time_location_for(CAPTURE_ID),
        provider_name="provider-main",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code="000001.SZ",
        requested_announcement_date=date(2026, 8, 28),
        body_sha256=hashlib.sha256(BODY).hexdigest(),
        body_size_bytes=len(BODY),
        response_completed_at=datetime(2026, 8, 28, 7, 32, tzinfo=UTC),
        response_row_count=1,
        format_version=FORMAT_VERSION,
        encryption_algorithm=ENCRYPTION_ALGORITHM,
        encryption_key_ref="config/financial-key",
        encryption_key_version=key_version,
    )


def _store(root: Path, key: bytes) -> FinancialSourceTimeBodyStore:
    return FinancialSourceTimeBodyStore(
        root,
        encryption_key=key,
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
        max_body_bytes=1024,
    )


def test_store_read_and_inspect_exact_authenticated_body(tmp_path: Path) -> None:
    store = _store(tmp_path, Fernet.generate_key())
    reference = _reference()

    assert store.store(reference, BODY) == reference
    assert store.store(reference, BODY) == reference
    assert store.inspect(reference) == reference
    assert store.read(reference) == BODY


@pytest.mark.parametrize(
    "reference",
    [
        replace(_reference(), location="financial-source-time/../escape.bin"),
        replace(_reference(), encryption_key_version="v2"),
        replace(_reference(), body_sha256="f" * 64),
        replace(_reference(), body_size_bytes=len(BODY) + 1),
    ],
)
def test_store_rejects_reference_or_body_substitution(
    tmp_path: Path,
    reference: FinancialSourceTimeArtifactRef,
) -> None:
    store = _store(tmp_path, Fernet.generate_key())
    with pytest.raises(FinancialSourceTimeArtifactError):
        store.store(reference, BODY)


def test_reader_rejects_another_key_and_truncated_ciphertext(tmp_path: Path) -> None:
    first = _store(tmp_path, Fernet.generate_key())
    reference = _reference()
    first.store(reference, BODY)

    with pytest.raises(FinancialSourceTimeArtifactError):
        _store(tmp_path, Fernet.generate_key()).read(reference)

    path = tmp_path / Path(*reference.location.split("/"))
    encrypted = path.read_bytes()
    path.write_bytes(encrypted[: len(encrypted) // 2])
    with pytest.raises(FinancialSourceTimeArtifactError):
        first.read(reference)
