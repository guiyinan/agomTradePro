"""Pure exact-storage identity contracts; all source values are synthetic."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from apps.data_center.domain.financial_next_session_witness import (
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from tests.unit.data_center.test_financial_next_session_witness import _witness


def _statutory_witness() -> FinancialNextSessionSourceTimeWitnessV3:
    """Replace only the storage-kind identity of an existing synthetic witness."""

    original = _witness()
    assert type(original) is FinancialNextSessionSourceTimeWitnessV3
    source = original.governance.official_source
    reference = StatutorySourceBodyReference(
        capture_id=source.capture_id,
        reference=f"statutory-source-body:///v1/{source.capture_id}.body",
        body_sha256=source.body_sha256,
        body_size_bytes=source.body_size_bytes,
    )
    identity = FinancialStatutorySourceIdentity(
        issuer="synthetic-exchange",
        document_id="synthetic-opening-rule",
        source_version="synthetic.v1",
        source_revision_sha256="b" * 64,
        source_uri=source.source_uri,
        body_reference=reference,
        first_seen_at=source.first_seen_at,
        revision_recorded_at=source.recorded_at,
        capture_observed_at=source.first_seen_at,
        recorded_at=source.recorded_at,
    )
    return replace(original, governance=replace(original.governance, official_source=identity))


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("issuer", ""),
        ("document_id", " padded"),
        ("source_version", "v" * 121),
        ("source_uri", "http://example.test/rule"),
        ("source_uri", "https://user:password@example.test/rule"),
        ("source_uri", "https://example.test/rule#fragment"),
        ("source_revision_sha256", "invalid"),
        ("body_reference", object()),
        ("first_seen_at", datetime(2026, 1, 1)),
        ("revision_recorded_at", datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))),
    ],
)
def test_statutory_source_identity_rejects_invalid_native_storage_and_clock_fields(
    field: str,
    replacement: object,
) -> None:
    """A typed reference still validates every external field before domain use."""

    source = _statutory_witness().governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    with pytest.raises((ValueError, TypeError)):
        replace(source, **{field: replacement})


@pytest.mark.parametrize("field", ["first_seen_at", "revision_recorded_at", "recorded_at"])
def test_statutory_source_identity_rejects_reversed_knowledge_clocks(field: str) -> None:
    """No caller can make a capture precede observation or revision recording."""

    source = _statutory_witness().governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    value = (
        source.capture_observed_at - timedelta(seconds=1)
        if field == "recorded_at"
        else source.recorded_at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError):
        replace(source, **{field: value})
