"""Fail-closed decision evidence and point-in-time data safety contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_rhythm.application.input_snapshot_use_cases import (
    BuildDecisionInputSnapshotUseCase,
)
from tests.unit.data_center.test_pit_research_integrity import (
    test_manifest_bound_view_ignores_versions_added_after_freeze as _assert_manifest_freeze,
)
from tests.unit.data_center.test_pit_research_integrity import (
    test_manifest_bound_view_rejects_payload_tampering_after_freeze as _assert_tamper_detection,
)
from tests.unit.decision_rhythm.test_decision_input_snapshot import (
    InMemorySnapshotRepository,
    _request,
)
from tests.unit.decision_rhythm.test_decision_input_snapshot import (
    test_snapshot_cutover_requires_real_events_and_verified_manifest as _assert_cutover_evidence,
)


@pytest.mark.parametrize("unsafe_state", ["missing", "stale", "future"])
def test_unsafe_decision_evidence_fails_before_persistence(
    unsafe_state: str,
) -> None:
    """Missing, stale, or future evidence must not create a decision snapshot."""

    as_of = datetime(2026, 7, 22, tzinfo=UTC)
    request = _request(as_of)
    if unsafe_state == "missing":
        del request.components["risk"]
    elif unsafe_state == "stale":
        request.freshness["risk"] = {"is_stale": True}
    else:
        request.components["risk"]["as_of_time"] = (as_of + timedelta(seconds=1)).isoformat()
    repository = InMemorySnapshotRepository()

    with pytest.raises(ValueError):
        BuildDecisionInputSnapshotUseCase(repository).execute(request)

    assert repository.snapshot is None


@pytest.mark.django_db
def test_frozen_manifest_is_stable_and_detects_tampering() -> None:
    """A frozen PIT manifest ignores later versions and rejects altered evidence."""

    _assert_manifest_freeze()
    _assert_tamper_detection()


@pytest.mark.django_db
def test_snapshot_cutover_requires_verified_manifest_and_real_events(settings) -> None:
    """Production cutover rejects fabricated or missing decision evidence."""

    _assert_cutover_evidence(settings)
