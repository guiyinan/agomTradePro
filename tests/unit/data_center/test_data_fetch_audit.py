from datetime import datetime, timezone

import pytest

from apps.audit.domain.system_audit_event import AuditOutcome
from apps.data_center.application.data_fetch_audit import (
    DataFetchAuditObservation,
    build_data_fetch_audit_event,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, 123456, tzinfo=timezone.utc)
RAW_HASH = "a" * 64


def _observation(**changes: object) -> DataFetchAuditObservation:
    values: dict[str, object] = {
        "provider_key": "provider-a",
        "capability": "macro.fetch",
        "dataset_key": "macro.pmi",
        "run_id": "run-1",
        "ingested_run_id": "ingested-1",
        "raw_audit_id": "raw-1",
        "raw_audit_version": "1",
        "raw_audit_content_hash": RAW_HASH,
        "outcome": AuditOutcome.SUCCESS,
        "row_count": 2,
        "occurred_at": NOW,
        "recorded_at": NOW,
    }
    values.update(changes)
    return DataFetchAuditObservation(**values)  # type: ignore[arg-type]


def test_builds_required_correlations_and_exact_raw_evidence() -> None:
    event = build_data_fetch_audit_event(_observation(), sequence_no=1, predecessor_hash=None)

    assert event.event_type == "data.fetch.completed"
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.correlations.run_id == "run-1"
    assert event.correlations.ingested_run_id == "ingested-1"
    assert event.evidence_refs[0].content_hash == RAW_HASH
    assert event.resource is not None
    assert event.resource.resource_id == "raw-1"


@pytest.mark.parametrize(
    ("outcome", "row_count", "error_class", "event_type"),
    [
        (AuditOutcome.NOOP, 0, None, "data.fetch.noop"),
        (AuditOutcome.FAILED, 0, "timeout", "data.fetch.failed"),
    ],
)
def test_maps_noop_and_failed_outcomes(
    outcome: AuditOutcome,
    row_count: int,
    error_class: str | None,
    event_type: str,
) -> None:
    event = build_data_fetch_audit_event(
        _observation(outcome=outcome, row_count=row_count, error_class=error_class),
        sequence_no=2,
        predecessor_hash=RAW_HASH,
    )
    assert event.event_type == event_type
    assert event.reason_codes == ("fetch_noop" if outcome is AuditOutcome.NOOP else "fetch_failed",)


def test_event_identity_is_stable_but_stream_state_is_explicit() -> None:
    first = build_data_fetch_audit_event(_observation(), sequence_no=1, predecessor_hash=None)
    replay = build_data_fetch_audit_event(_observation(), sequence_no=1, predecessor_hash=None)
    assert first.event_id == replay.event_id
    assert first.idempotency_key == replay.idempotency_key
    with pytest.raises(ValueError, match="sequence_no"):
        build_data_fetch_audit_event(_observation(), sequence_no=0, predecessor_hash=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": ""},
        {"raw_audit_content_hash": "A" * 64},
        {"outcome": AuditOutcome.SUCCESS, "row_count": 0},
        {"outcome": AuditOutcome.FAILED, "row_count": 0, "error_class": None},
    ],
)
def test_observation_rejects_missing_or_inconsistent_evidence(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)
