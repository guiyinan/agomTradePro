"""Pure controlled-replay request and outcome contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.events.domain.entities import EventType
from apps.events.domain.replay import (
    ReplayEventResult,
    ReplayFilter,
    ReplaySummary,
    replay_fingerprint,
)


def test_replay_filter_requires_bounded_aware_input() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        ReplayFilter(EventType.DECISION_APPROVED, datetime.now(), now, 10)
    with pytest.raises(ValueError, match="start_at"):
        ReplayFilter(EventType.DECISION_APPROVED, now, now - timedelta(seconds=1), 10)
    with pytest.raises(ValueError, match="31 days"):
        ReplayFilter(EventType.DECISION_APPROVED, now - timedelta(days=32), now, 10)
    with pytest.raises(ValueError, match="limit"):
        ReplayFilter(EventType.DECISION_APPROVED, None, None, 1001)


def test_replay_fingerprint_is_stable_for_normalized_filter() -> None:
    request = ReplayFilter(EventType.DECISION_APPROVED, None, None, 20)

    assert replay_fingerprint("decision.approved", request) == replay_fingerprint(
        " decision.approved ", request
    )
    assert replay_fingerprint("decision.approved", request) != replay_fingerprint(
        "decision.rejected", request
    )


@pytest.mark.parametrize(
    ("results", "outcome"),
    [
        ([ReplayEventResult("1", "succeeded")], "completed"),
        (
            [
                ReplayEventResult("1", "succeeded"),
                ReplayEventResult("2", "failed", "handler_error", "safe"),
            ],
            "partial",
        ),
        ([ReplayEventResult("2", "failed", "handler_error", "safe")], "failed"),
    ],
)
def test_replay_summary_classifies_outcomes(results, outcome: str) -> None:
    summary = ReplaySummary.from_results(results)

    assert summary.outcome == outcome
    assert summary.attempted == len(results)
    assert summary.failed == sum(item.status == "failed" for item in results)
