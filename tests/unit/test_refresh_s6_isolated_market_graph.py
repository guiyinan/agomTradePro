"""Isolated S6 current-market refresh launcher contracts."""

from datetime import UTC, date, datetime

import pytest

from scripts import refresh_s6_isolated_market_graph as launcher


def test_require_isolated_target_session_returns_resolved_date() -> None:
    """The launcher binds the exact ready session selected by the calendar resolver."""

    now = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)

    resolved = launcher._require_isolated_target_session(
        now,
        resolver=lambda _now: date(2026, 10, 13),
    )

    assert resolved == date(2026, 10, 13)


def test_require_isolated_target_session_blocks_without_provider_evidence() -> None:
    """The launcher stops before task execution when no ready session exists."""

    now = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="S6_GRAPH_REFRESH_TARGET_SESSION_UNAVAILABLE"):
        launcher._require_isolated_target_session(now, resolver=lambda _now: None)
