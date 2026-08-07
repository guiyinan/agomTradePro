"""Raw landing redaction and schema fingerprint tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.raw_landing import (
    RawPayload,
    SchemaFingerprint,
    raw_payload_record_digest,
)
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository

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


@pytest.mark.django_db
def test_raw_landing_retention_candidates_respect_row_deadline() -> None:
    repository = RawLandingRepository()
    fetched_at = NOW - timedelta(days=31)
    future = RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash="sha256:future-retention",
        schema_fingerprint="sha256:schema",
        payload={},
        fetched_at=fetched_at,
        retention_until=NOW + timedelta(days=1),
    )
    eligible = RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash="sha256:expired-retention",
        schema_fingerprint="sha256:schema",
        payload={},
        fetched_at=fetched_at,
        retention_until=NOW - timedelta(days=1),
    )
    repository.save(future)
    repository.save(eligible)

    rows = repository.list_expired(
        "market.raw",
        before=NOW - timedelta(days=30),
        now=NOW,
        limit=10,
    )

    assert [row.payload_id for row in rows] == [eligible.payload_id]


@pytest.mark.django_db
def test_raw_landing_is_immutable_and_delete_uses_full_record_cas() -> None:
    repository = RawLandingRepository()
    payload = RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash=f"sha256:{uuid4().hex}",
        schema_fingerprint="sha256:schema",
        payload={"value": 1},
        fetched_at=NOW - timedelta(days=31),
        retention_until=NOW - timedelta(days=1),
    )

    assert repository.save(payload) == payload
    assert repository.save(payload) == payload
    with pytest.raises(ValueError, match="raw_payload_immutable_conflict"):
        repository.save(replace(payload, payload={"value": 2}))

    assert (
        repository.delete_if_matches(
            payload,
            expected_record_digest="sha256:stale-plan",
            now=NOW,
        )
        == 0
    )
    assert (
        repository.delete_if_matches(
            payload,
            expected_record_digest=raw_payload_record_digest(payload),
            now=NOW,
        )
        == 1
    )
