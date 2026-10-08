"""Compatibility tests for the retained cache lease and cursor primitives."""

from __future__ import annotations

import pytest
from django.core.cache.backends.locmem import LocMemCache

from apps.data_center.application import financial_refresh_lease as lease


def _cache() -> LocMemCache:
    """Return an isolated lease cache for each primitive contract test."""

    cache = LocMemCache("financial-refresh-lease-tests", {})
    cache.clear()
    return cache


def test_financial_refresh_lease_claims_renews_and_rejects_a_second_owner() -> None:
    cache = _cache()

    assert lease.claim_financial_refresh_lock(cache, "workflow-a") is True
    assert lease.claim_financial_refresh_lock(cache, "workflow-b") is False
    assert lease.claim_financial_refresh_lock(cache, "workflow-a") is True
    assert cache.get(lease.FINANCIAL_REFRESH_LOCK_KEY) == "workflow-a"


def test_financial_refresh_lease_loss_fails_closed_and_release_is_owner_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache()
    assert lease.claim_financial_refresh_lock(cache, "workflow-a") is True
    monkeypatch.setattr(cache, "touch", lambda *_args, **_kwargs: False)

    assert lease.claim_financial_refresh_lock(cache, "workflow-a") is False
    lease.release_financial_refresh_lock(cache, "workflow-b")
    assert cache.get(lease.FINANCIAL_REFRESH_LOCK_KEY) == "workflow-a"
    lease.release_financial_refresh_lock(cache, "workflow-a")
    assert cache.get(lease.FINANCIAL_REFRESH_LOCK_KEY) is None


def test_financial_refresh_checkpoint_resumes_only_for_the_same_workload() -> None:
    cache = _cache()
    arguments = {
        "next_offset": 2,
        "universe_hash": "a" * 64,
        "source": "akshare",
        "financial_periods": 8,
        "batch_size": 2,
    }
    lease.save_financial_refresh_progress(cache, **arguments)

    assert (
        lease.restore_financial_refresh_offset(
            cache,
            universe_hash="a" * 64,
            source="akshare",
            financial_periods=8,
            batch_size=2,
            total_assets=3,
        )
        == 2
    )
    assert (
        lease.restore_financial_refresh_offset(
            cache,
            universe_hash="b" * 64,
            source="akshare",
            financial_periods=8,
            batch_size=2,
            total_assets=3,
        )
        is None
    )


def test_financial_refresh_checkpoint_reports_complete_scope_and_can_be_cleared() -> None:
    cache = _cache()
    lease.save_financial_refresh_progress(
        cache,
        next_offset=3,
        universe_hash="c" * 64,
        source="akshare",
        financial_periods=8,
        batch_size=2,
    )

    assert lease.financial_refresh_checkpoint(
        offset=2,
        next_offset=3,
        total_assets=3,
        universe_hash="c" * 64,
    ) == {
        "offset": 2,
        "next_offset": 3,
        "total_assets": 3,
        "complete": True,
        "universe_hash": "c" * 64,
    }
    lease.clear_financial_refresh_progress(cache)
    assert cache.get(lease.FINANCIAL_REFRESH_PROGRESS_KEY) is None
