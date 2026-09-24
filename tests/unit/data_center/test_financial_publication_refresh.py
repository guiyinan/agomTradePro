"""Evidence-complete scheduled financial publication refresh contracts."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache

from apps.data_center.application import tasks
from core.exceptions import InvalidInputError


@pytest.fixture(autouse=True)
def _clear_refresh_state() -> None:
    cache.delete(tasks._FINANCIAL_REFRESH_LOCK_KEY)
    cache.delete(tasks._FINANCIAL_REFRESH_PROGRESS_KEY)


@pytest.fixture
def _financial_runtime(monkeypatch):
    authority = SimpleNamespace(
        actor_id="service:data02",
        authority_source_id="config-center",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="a" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    monkeypatch.setattr(
        tasks,
        "preflight_data_reliability_audit_runtime",
        lambda **_: authority,
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ", "000003.SZ"],
    )
    sync = SimpleNamespace(
        execute=lambda _: SimpleNamespace(stored_count=4),
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_financial_use_case", lambda: sync)
    coordinator = SimpleNamespace(
        execute=lambda **_: SimpleNamespace(published_count=12),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: coordinator,
    )
    return sync, coordinator


def test_financial_refresh_rejects_invalid_input_before_provider_access(monkeypatch) -> None:
    provider = monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider access"),
    )

    result = tasks.refresh_financial_publications_batch_task.run(batch_size=0)

    assert provider is None
    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    assert result["stored"] == 0


def test_financial_refresh_blocks_without_current_authority(monkeypatch) -> None:
    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable

    monkeypatch.setattr(
        tasks,
        "preflight_data_reliability_audit_runtime",
        lambda **_: (_ for _ in ()).throw(
            SystemAuditCompositionUnavailable(
                "unavailable",
                reason_code="authority_unavailable",
            )
        ),
    )

    result = tasks.refresh_financial_publications_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["stored"] == 0


def test_financial_refresh_schedules_next_exact_batch(
    monkeypatch,
    _financial_runtime,
) -> None:
    continuation = monkeypatch.setattr(
        tasks.refresh_financial_publications_batch_task,
        "apply_async",
        lambda **_: SimpleNamespace(id="next-task"),
    )

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
    )

    assert continuation is None
    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["stored"] == 8
    assert result["published"] == 0
    assert result["continuation_task_id"] == "next-task"
    assert result["checkpoint"]["next_offset"] == 2
    assert cache.get(tasks._FINANCIAL_REFRESH_LOCK_KEY)


def test_financial_refresh_publishes_only_after_full_universe(
    monkeypatch,
    _financial_runtime,
) -> None:
    result = tasks.refresh_financial_publications_batch_task.run(batch_size=3)

    assert result["outcome"] == "success"
    assert result["requested"] == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert result["stored"] == 12
    assert result["published"] == 12
    assert result["publication_updated"] is True
    assert result["checkpoint"]["complete"] is True


def test_financial_refresh_reports_partial_failure_without_publishing(
    monkeypatch,
    _financial_runtime,
) -> None:
    sync, _ = _financial_runtime
    calls = 0

    def execute(_request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("provider unavailable")
        return SimpleNamespace(stored_count=4)

    sync.execute = execute
    publication = monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: pytest.fail("publication attempted"),
    )

    result = tasks.refresh_financial_publications_batch_task.run(batch_size=3)

    assert publication is None
    assert result["outcome"] == "partial"
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["published"] == 0


def test_financial_refresh_reports_zero_output_as_failure(
    _financial_runtime,
) -> None:
    sync, _ = _financial_runtime
    sync.execute = lambda _: SimpleNamespace(stored_count=0)

    result = tasks.refresh_financial_publications_batch_task.run(batch_size=3)

    assert result["outcome"] == "failed"
    assert result["succeeded"] == 0
    assert result["failed"] == 3
    assert result["stored"] == 0


def test_financial_refresh_exposes_source_evidence_block(
    _financial_runtime,
) -> None:
    sync, _ = _financial_runtime
    sync.execute = lambda _: (_ for _ in ()).throw(
        InvalidInputError(
            "source evidence missing",
            code="FINANCIAL_SOURCE_EVIDENCE_REQUIRED",
        )
    )

    result = tasks.refresh_financial_publications_batch_task.run(batch_size=3)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "financial_evidence"
    assert result["blocked_reason"] == "financial_source_evidence_required"
    assert result["must_not_use_for_decision"] is True
