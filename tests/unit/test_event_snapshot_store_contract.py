"""Regression coverage for aggregate event-store snapshots."""

import pytest

from apps.events.domain.entities import AggregateSnapshot
from apps.events.infrastructure.event_store import SnapshotStore


@pytest.mark.django_db
def test_snapshot_store_round_trips_aggregate_state() -> None:
    store = SnapshotStore()
    snapshot_id = store.save_snapshot(
        aggregate_type="research_run",
        aggregate_id="run-1",
        version=3,
        state={"status": "completed", "result_id": "result-1"},
    )

    assert snapshot_id is not None
    latest = store.get_latest_snapshot("research_run", "run-1")
    exact = store.get_snapshot("research_run", "run-1", version=3)

    assert isinstance(latest, AggregateSnapshot)
    assert exact == latest
    assert latest.snapshot_id == snapshot_id
    assert latest.version == 3
    assert latest.state == {"status": "completed", "result_id": "result-1"}
