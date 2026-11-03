"""Opt-in smoke test for the real governed-calendar acceptance helper."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.simulated_trading.domain.execution_settlement_primitives import (
    CalendarEvidenceValidationError,
)
from tests.support.ash07_real_calendar_publication import (
    RealCalendarPublicationLease,
    publish_real_calendar_for_acceptance,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CLOSED_SESSION_REASON = "settlement-bound simulated trades require an explicit open session"


@pytest.mark.skipif(
    os.environ.get("AGOM_RUN_ASH07_REAL_CALENDAR_SMOKE") != "1",
    reason="set AGOM_RUN_ASH07_REAL_CALENDAR_SMOKE=1 for real governed-calendar capture",
)
def test_real_governed_calendar_capture_and_consumer_smoke(tmp_path: Path) -> None:
    """Capture today's explicit SSE membership and verify its current consumer evidence."""

    assert_native_postgres_test_database()
    business_date = timezone.now().astimezone(_SHANGHAI).date()
    coverage_start = business_date - timedelta(days=7)
    coverage_end = business_date + timedelta(days=14)
    lease: RealCalendarPublicationLease | None = None
    try:
        try:
            lease = publish_real_calendar_for_acceptance(
                business_date=business_date,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
            )
        except CalendarEvidenceValidationError as error:
            if str(error) != _CLOSED_SESSION_REASON:
                raise
            _write_summary(
                tmp_path,
                {
                    "outcome": "explicit_current_sse_date_closed",
                    "business_date": business_date.isoformat(),
                    "coverage_start": coverage_start.isoformat(),
                    "coverage_end": coverage_end.isoformat(),
                    "calendar_reason": str(error),
                    "explanation": (
                        "The real published calendar marked this exact date closed; "
                        "no weekday or prior-session inference was used."
                    ),
                },
            )
            pytest.skip(f"real SSE calendar explicitly marks {business_date.isoformat()} closed")

        evidence = lease.calendar_evidence
        snapshot = lease.snapshot
        publication = evidence.publication
        if publication is None:
            raise AssertionError("published calendar evidence has no publication reference")
        if lease.market_session != business_date:
            raise AssertionError("consumer open-session result differs from the explicit SSE date")
        if lease.exchange != "SSE" or lease.timezone_name != "Asia/Shanghai":
            raise AssertionError("consumer calendar scope differs from the requested SSE binding")
        if snapshot.source_published_at is not None:
            raise AssertionError("unknown upstream publication time must remain unknown")

        raw_reference = snapshot.raw_reference
        _write_summary(
            tmp_path,
            {
                "outcome": "calendar_published_and_consumed",
                "purpose": "calendar_capture_consumer_smoke_only",
                "business_date": business_date.isoformat(),
                "coverage_start": coverage_start.isoformat(),
                "coverage_end": coverage_end.isoformat(),
                "actual_cutoff": _utc_text(lease.as_of),
                "consumer_session": lease.market_session.isoformat(),
                "next_open_session": lease.next_open_session.isoformat(),
                "dataset_key": lease.dataset_key,
                "exchange": lease.exchange,
                "timezone_name": lease.timezone_name,
                "response_age_limit_seconds": lease.calendar_response_max_age_seconds,
                "snapshot": {
                    "snapshot_id": snapshot.snapshot_id,
                    "content_hash": snapshot.content_hash,
                    "record_digest": snapshot.record_digest,
                    "first_seen_at": _utc_text(snapshot.first_seen_at),
                    "recorded_at": _utc_text(snapshot.recorded_at),
                    "source_published_at": None,
                },
                "publication": {
                    "publication_id": publication.publication_id,
                    "publication_hash": publication.publication_hash,
                    "fact_content_hash": publication.fact_content_hash,
                    "policy_hash": publication.policy_hash,
                    "published_at": _utc_text(publication.published_at),
                    "recorded_at": _utc_text(publication.recorded_at),
                    "valid_from": _utc_text(publication.reference_valid_from),
                    "valid_until": _utc_text(publication.reference_valid_until),
                },
                "raw_reference": {
                    "payload_id": raw_reference.payload_id,
                    "manifest_hash": raw_reference.payload_hash,
                    "record_digest": raw_reference.record_digest,
                    "body_sha256": raw_reference.body_sha256,
                    "retained_content_sha256": raw_reference.retained_content_sha256,
                    "response_completed_at": _utc_text(raw_reference.response_completed_at),
                },
                "evidence_hash": evidence.evidence_hash,
            },
        )
    finally:
        if lease is not None:
            lease.close()


def _write_summary(tmp_path: Path, value: dict[str, object]) -> None:
    """Write only public calendar IDs, hashes and clocks to pytest's temp path."""

    destination = tmp_path / "ash07-real-calendar-smoke.json"
    destination.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _utc_text(value: datetime) -> str:
    """Serialize only an explicitly aware datetime for the smoke summary."""

    if type(value) is not datetime:
        raise TypeError("calendar smoke clock must be an aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("calendar smoke clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
