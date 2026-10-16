"""Contract tests for the source dataset bound into a formal calendar member."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    create_calendar_formal_publication_seal,
)

_NOW = datetime(2026, 10, 16, 4, 0, 10, tzinfo=UTC)
_CALENDAR_DATE = date(2026, 10, 16)
_FORMAL_DATASET = DatasetKey("test.exchange_calendar", "contract-1", "schema-1")
_OTHER_RAW_DATASET = DatasetKey("tushare.calendar.raw", "1.0", "1.0")


def _snapshot_with_raw_dataset(dataset: DatasetKey) -> ExchangeCalendarSnapshot:
    """Build an immutable one-day snapshot carrying the selected raw dataset."""

    response_at = _NOW - timedelta(seconds=10)
    raw_reference = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", _CALENDAR_DATE, _CALENDAR_DATE
        ),
        original_body_retained=True,
        response_completed_at=response_at,
        provider_name="tushare",
        dataset_key=dataset.value,
        transport="direct",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SSE",
        coverage_start=_CALENDAR_DATE,
        coverage_end=_CALENDAR_DATE,
        days=(
            ExchangeCalendarDay(
                exchange="SSE",
                calendar_date=_CALENDAR_DATE,
                is_open=True,
                previous_open_date=date(2026, 10, 15),
            ),
        ),
        provider_name="tushare",
        raw_reference=raw_reference,
        first_seen_at=response_at,
        source_published_at=None,
    )
    return make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=response_at + timedelta(seconds=1),
    )


def test_formal_calendar_seal_rejects_raw_payload_from_another_dataset() -> None:
    """A calendar member cannot bind retained bytes from a different dataset."""

    snapshot = _snapshot_with_raw_dataset(_OTHER_RAW_DATASET)
    policy = PublicationPolicy(
        dataset=_FORMAL_DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fetched_at", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-policy-1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-placeholder",
        dataset_key=_FORMAL_DATASET.value,
        natural_key=f"SSE:{_CALENDAR_DATE.isoformat()}:{_CALENDAR_DATE.isoformat()}",
        source=snapshot.provider_name,
        source_record_id=snapshot.snapshot_id,
        fact_table="data_center_exchange_calendar_snapshot_fact",
        fact_pk=snapshot.snapshot_id,
        observed_at=None,
        raw_payload_hash=snapshot.candidate.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=snapshot.first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    member_reference = CalendarPublicationMemberReference(
        member=member,
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )

    with pytest.raises(CalendarFormalPublicationError) as exc_info:
        create_calendar_formal_publication_seal(
            dataset=_FORMAL_DATASET,
            exchange=snapshot.exchange,
            calendar_response_max_age_seconds=60,
            contract_recorded_at=_NOW - timedelta(days=2),
            policy=policy,
            policy_recorded_at=_NOW - timedelta(days=1),
            snapshot=snapshot,
            member_reference=member_reference,
        )

    assert exc_info.value.code == "CALENDAR_FORMAL_MEMBER_RAW_DATASET_MISMATCH"
