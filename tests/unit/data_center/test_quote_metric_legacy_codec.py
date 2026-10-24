"""Golden hashes captured from the pre-metric 9b8 quote implementation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
)
from apps.data_center.infrastructure.publication_fact_legacy_payload import (
    quote_snapshot_payload_hash,
)


@pytest.mark.parametrize(
    ("with_raw_evidence", "canonical_hash"),
    [
        (True, "5acaa148357e59326ecd59f8a61488f39ab71381a0ed13627594d5574dfe02c6"),
        (False, "776504859e3998c627067b65b2786203c57c716d5dfe1da5332296d5afee1929"),
    ],
)
def test_null_quote_metric_preserves_pre_metric_golden_hashes(
    with_raw_evidence: bool, canonical_hash: str
) -> None:
    """The new nullable field must not change either historical digest codec."""

    row = QuoteSnapshotModel(
        id=42,
        asset_code="600000.SH",
        snapshot_at=datetime.fromisoformat("2026-10-23T15:00:00+08:00"),
        fetched_at=datetime.fromisoformat("2026-10-23T07:00:01+00:00"),
        current_price=Decimal("10.1200"),
        open=Decimal("10.0000"),
        high=Decimal("10.2300"),
        low=Decimal("9.9900"),
        prev_close=Decimal("10.0100"),
        volume=Decimal("123456.00"),
        amount=Decimal("1248888.72"),
        bid=None,
        ask=Decimal("10.1300"),
        source="fixture-vendor",
        extra={"note": "历史凭据", "nested": {"missing": None, "values": [0, 1, "原文"]}},
        contract_version="1.0",
        schema_version="1.0",
        source_record_id="captured-response-row-42" if with_raw_evidence else "",
        raw_payload_hash="b" * 64 if with_raw_evidence else "",
        quality_status="accepted",
        revision_number=3,
        ingested_run_id=(
            UUID("12345678-1234-5678-1234-567812345678") if with_raw_evidence else None
        ),
    )
    # Constants came from the actual pre-change codecs, before model adoption.
    # This assertion never derives the expected digest using the current helper.
    assert canonical_fact_content_hash(row) == canonical_hash
    assert quote_snapshot_payload_hash(row) == (
        "b0bd688c31e61c5a5cf5bcffdd22c1c8756cb8c53c1bb26a988e7c7e2e9c7ecf"
    )
