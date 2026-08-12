"""Tests for the first fail-closed legacy output adapter."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.dtos import QuoteResponse
from apps.research.application.data_center_evidence_adapter import (
    build_quote_legacy_evidence_summary,
)

NOW = datetime(2026, 8, 13, 9, tzinfo=UTC)


def _quote() -> QuoteResponse:
    return QuoteResponse(
        asset_code="000001.SZ",
        snapshot_at=NOW - timedelta(minutes=5),
        fetched_at=NOW - timedelta(minutes=4),
        current_price=12.5,
        open=12.1,
        high=12.6,
        low=12.0,
        prev_close=12.2,
        volume=1000.0,
        source="test-provider",
        age_minutes=5,
        is_stale=False,
        freshness_status="fresh",
        must_not_use_for_decision=False,
        blocked_reason="",
        max_age_hours=4.0,
    )


def test_quote_adapter_is_content_bound_and_fail_closed() -> None:
    first = build_quote_legacy_evidence_summary(_quote(), evaluated_at=NOW)
    changed = build_quote_legacy_evidence_summary(
        replace(_quote(), current_price=12.6), evaluated_at=NOW
    )

    assert first.output_owner == "data_center"
    assert first.output_artifact_type == "market_quote"
    assert first.output_artifact_id == "000001.SZ"
    assert first.claim_kind == "observation"
    assert first.method_kind == "identity"
    assert first.research_family == "legacy"
    assert first.governance_state == "research_only"
    assert first.permission == "display_only"
    assert first.blocker_codes == ("evidence.legacy_unverified",)
    assert first.track_record_availability == "unavailable"
    assert first.must_not_use_for_decision is True
    assert first.must_not_execute is True
    assert first.output_content_hash != changed.output_content_hash
    assert first.envelope_content_hash != changed.envelope_content_hash


@pytest.mark.parametrize(
    "quote",
    [
        replace(_quote(), snapshot_at=NOW.replace(tzinfo=None)),
        replace(_quote(), fetched_at=NOW.replace(tzinfo=None)),
        replace(_quote(), snapshot_at=NOW + timedelta(seconds=1)),
        replace(_quote(), fetched_at=NOW + timedelta(seconds=1)),
        replace(_quote(), current_price=float("nan")),
        replace(_quote(), max_age_hours=float("inf")),
    ],
)
def test_quote_adapter_rejects_unverifiable_inputs(quote: QuoteResponse) -> None:
    with pytest.raises(ValueError):
        build_quote_legacy_evidence_summary(quote, evaluated_at=NOW)
