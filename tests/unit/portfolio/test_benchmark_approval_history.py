"""Independent-account lifecycle invariants without manufacturing a usable receipt."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from apps.portfolio.domain.benchmark_approval_history import (
    BenchmarkApprovalConflict,
    BenchmarkApprovalEvent,
    BenchmarkApprovalHistory,
)
from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope


def _proposal() -> BenchmarkApprovalEvent:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return BenchmarkApprovalEvent(
        1,
        uuid4(),
        "submitted",
        BenchmarkScope("held-account", "acc-1", 7, "tenant-1", "owner-1"),
        uuid4(),
        1,
        "f" * 64,
        7,
        "owner",
        now,
        now + timedelta(hours=2),
        "",
        "{}",
    )


def _next(prior, event, action, actor_id):
    return replace(
        event,
        sequence=prior.sequence + 1,
        action=action,
        actor_user_id=actor_id,
        previous_hash=prior.content_hash,
        recorded_at=prior.recorded_at + timedelta(seconds=1),
    )


def test_pending_replacement_independent_approval_and_revoke_without_fallback():
    history = BenchmarkApprovalHistory()
    first = _proposal()
    history.accept(first)
    with pytest.raises(BenchmarkApprovalConflict, match="independent"):
        history.accept(_next(first, first, "approved", first.actor_user_id))
    approved = _next(first, first, "approved", 8)
    history.accept(approved)
    pending = _next(approved, replace(first, request_id=uuid4()), "submitted", 7)
    history.accept(pending)
    assert history.active == approved
    newer = _next(pending, replace(first, request_id=uuid4()), "submitted", 7)
    history.accept(newer)
    with pytest.raises(BenchmarkApprovalConflict, match="submission_replaced"):
        history.accept(_next(newer, pending, "approved", 8))
    winner = _next(newer, newer, "approved", 8)
    history.accept(winner)
    history.accept(_next(winner, winner, "revoked", 7))
    assert history.active is None


def test_crossed_scope_source_expiry_and_broken_chain_fail_closed():
    initial = _proposal()
    history = BenchmarkApprovalHistory()
    history.accept(initial)
    grant = _next(initial, initial, "approved", 8)
    for change in (
        {"scope": replace(initial.scope, tenant_id="other")},
        {"source_seal": "a" * 64},
        {"previous_hash": "b" * 64},
        {"sequence": 8},
        {"recorded_at": initial.valid_until},
    ):
        with pytest.raises(BenchmarkApprovalConflict):
            history.accept(replace(grant, **change))
    assert history.active is None
