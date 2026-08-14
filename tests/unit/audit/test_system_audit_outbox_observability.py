from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.audit.application.system_audit_outbox_observability import (
    GetSystemAuditOutboxBacklogCommand,
    GetSystemAuditOutboxBacklogUseCase,
    SystemAuditOutboxBacklogCorruption,
    SystemAuditOutboxBacklogSnapshot,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _snapshot(**overrides: object) -> SystemAuditOutboxBacklogSnapshot:
    values: dict[str, object] = {
        "as_of": NOW,
        "pending_count": 1,
        "due_pending_count": 1,
        "claimed_count": 1,
        "expired_claimed_count": 0,
        "failed_count": 2,
        "delivered_count": 3,
        "oldest_backlog_at": NOW - timedelta(minutes=10),
        "oldest_claimed_at": NOW - timedelta(minutes=2),
    }
    values.update(overrides)
    return SystemAuditOutboxBacklogSnapshot(**values)


def test_snapshot_exposes_bounded_counts_and_non_negative_ages() -> None:
    snapshot = _snapshot()

    assert snapshot.backlog_count == 2
    assert snapshot.oldest_backlog_age_seconds == pytest.approx(600.0)
    assert snapshot.oldest_claimed_age_seconds == pytest.approx(120.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pending_count", -1),
        ("due_pending_count", 2),
        ("expired_claimed_count", 2),
        ("oldest_backlog_at", None),
    ],
)
def test_snapshot_rejects_inconsistent_state(field: str, value: object) -> None:
    overrides: dict[str, object] = {field: value}
    if field == "oldest_backlog_at":
        overrides.update(pending_count=0, claimed_count=0, due_pending_count=0)
    elif field == "due_pending_count":
        overrides.update(pending_count=1)
    elif field == "expired_claimed_count":
        overrides.update(claimed_count=1)
    with pytest.raises(ValueError):
        _snapshot(**overrides)


def test_snapshot_rejects_naive_observation_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _snapshot(as_of=datetime.now())


@pytest.mark.parametrize("field", ["oldest_backlog_at", "oldest_claimed_at"])
def test_snapshot_rejects_future_age_clock(field: str) -> None:
    with pytest.raises(ValueError, match="after as_of"):
        _snapshot(**{field: NOW + timedelta(seconds=1)})


def test_backlog_use_case_preserves_exact_observation_cutoff() -> None:
    snapshot = _snapshot()

    class Reader:
        def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
            assert as_of == NOW
            return snapshot

    result = GetSystemAuditOutboxBacklogUseCase(Reader()).execute(
        GetSystemAuditOutboxBacklogCommand(as_of=NOW)
    )

    assert result == snapshot


def test_backlog_use_case_rejects_reader_cutoff_substitution() -> None:
    snapshot = _snapshot(as_of=NOW + timedelta(seconds=1))

    class Reader:
        def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
            del as_of
            return snapshot

    with pytest.raises(SystemAuditOutboxBacklogCorruption, match="cutoff"):
        GetSystemAuditOutboxBacklogUseCase(Reader()).execute(
            GetSystemAuditOutboxBacklogCommand(as_of=NOW)
        )


def test_empty_snapshot_has_no_age_or_backlog() -> None:
    snapshot = replace(
        _snapshot(),
        pending_count=0,
        due_pending_count=0,
        claimed_count=0,
        expired_claimed_count=0,
        oldest_backlog_at=None,
        oldest_claimed_at=None,
    )

    assert snapshot.backlog_count == 0
    assert snapshot.oldest_backlog_age_seconds is None
    assert snapshot.oldest_claimed_age_seconds is None
