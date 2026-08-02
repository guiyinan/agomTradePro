"""Raw landing redaction and schema fingerprint tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.raw_landing import RawPayload, SchemaFingerprint

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


def test_raw_payload_requires_redaction_and_retention_order() -> None:
    with pytest.raises(ValueError, match="redacted"):
        RawPayload(
            payload_id=str(uuid4()),
            dataset_key="equity.quote.snapshot",
            provider_name="tushare",
            payload_hash="sha256:payload",
            schema_fingerprint="sha256:schema",
            payload={"token": "should-not-persist"},
            fetched_at=NOW,
            redacted=False,
        )
    with pytest.raises(ValueError, match="retention_until"):
        RawPayload(
            payload_id=str(uuid4()),
            dataset_key="equity.quote.snapshot",
            provider_name="tushare",
            payload_hash="sha256:payload-2",
            schema_fingerprint="sha256:schema",
            payload={},
            fetched_at=NOW,
            retention_until=NOW - timedelta(seconds=1),
        )


def test_schema_fingerprint_observation_is_time_ordered() -> None:
    fingerprint = SchemaFingerprint(
        fingerprint="sha256:schema",
        dataset_key="equity.quote.snapshot",
        provider_name="tushare",
        fields=("ts_code", "price"),
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    assert fingerprint.sample_count == 1
