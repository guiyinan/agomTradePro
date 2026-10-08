"""Fail-closed contracts for the retired generic financial refresh task."""

from __future__ import annotations

import pytest

from apps.data_center.application import tasks


def test_financial_refresh_rejects_invalid_input_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid compatibility-task input never reaches legacy or new provider ports."""

    monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider lookup must not run"),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_financial_use_case",
        lambda: pytest.fail("generic financial backfill must not be composed"),
    )

    result = tasks.refresh_financial_publications_batch_task.run(batch_size=0)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    assert result["stored"] == 0


def test_financial_refresh_fails_closed_before_legacy_provider_or_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old Tushare-capable entry point cannot bypass receipt and ceiling gates."""

    monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("legacy provider lookup must not run"),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_financial_use_case",
        lambda: pytest.fail("generic backfill must not be composed"),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: pytest.fail("publication must remain untouched"),
    )

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=3,
        source="tushare",
        auto_continue=True,
    )

    assert result["outcome"] == "blocked"
    assert result["stage"] == "capacity"
    assert result["blocked_reason"] == "financial_capacity_receipt_required"
    assert result["requested"] == 0
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["stored"] == 0
    assert result["published"] == 0
