"""Evidence-complete scheduled financial publication refresh contracts."""

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache.backends.locmem import LocMemCache

from apps.data_center.application import financial_refresh_lease, tasks
from core.exceptions import InvalidInputError


@pytest.fixture(autouse=True)
def _clear_refresh_state(monkeypatch) -> None:
    """Use an isolated in-memory cache so these tests never touch Redis."""

    isolated_cache = LocMemCache("financial-publication-refresh-tests", {})
    isolated_cache.clear()
    monkeypatch.setattr(tasks, "cache", isolated_cache)


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
        tasks.audit_integration,
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
        tasks.audit_integration,
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
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY)


def test_financial_refresh_continuation_renews_its_owned_lease(
    monkeypatch,
    _financial_runtime,
) -> None:
    owner = "scheduled-financial-workflow"
    tasks.cache.set(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY, owner, timeout=1)
    original_touch = tasks.cache.touch
    touched: list[tuple[str, int | None]] = []

    def record_touch(key: str, timeout: int | None = None) -> bool:
        touched.append((key, timeout))
        return original_touch(key, timeout=timeout)

    monkeypatch.setattr(tasks.cache, "touch", record_touch)

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=3,
        auto_continue=True,
        workflow_id=owner,
    )

    assert result["outcome"] == "success"
    assert touched == [
        (
            financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY,
            financial_refresh_lease.FINANCIAL_REFRESH_LOCK_LEASE_TTL,
        )
    ]
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY) is None


def test_financial_refresh_fails_closed_when_lease_renewal_fails(
    monkeypatch,
    _financial_runtime,
) -> None:
    owner = "scheduled-financial-workflow"
    sync, _ = _financial_runtime
    sync.execute = lambda _: pytest.fail("provider called without a renewed lease")
    tasks.cache.set(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY, owner, timeout=30)
    monkeypatch.setattr(tasks.cache, "touch", lambda *_args, **_kwargs: False)

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
        workflow_id=owner,
    )

    assert result["outcome"] == "blocked"
    assert result["stage"] == "lock"
    assert result["blocked_reason"] == "financial_refresh_lock_lost"
    assert result["must_not_use_for_decision"] is True
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY) == owner


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


def test_financial_refresh_soft_timeout_releases_lease_and_can_retry(
    monkeypatch,
    _financial_runtime,
) -> None:
    sync, _ = _financial_runtime
    sync.execute = lambda _: (_ for _ in ()).throw(SoftTimeLimitExceeded())

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
    )

    assert result["outcome"] == "failed"
    assert result["stage"] == "provider"
    assert result["error_code"] == "financial_refresh_soft_time_limit_exceeded"
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY) is None
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_PROGRESS_KEY) is None

    sync.execute = lambda _: SimpleNamespace(stored_count=4)
    retry = tasks.refresh_financial_publications_batch_task.run(
        batch_size=3,
        auto_continue=True,
    )

    assert retry["outcome"] == "success"
    assert retry["checkpoint"]["complete"] is True


def test_financial_refresh_broker_failure_keeps_checkpoint_and_releases_lease(
    monkeypatch,
    _financial_runtime,
) -> None:
    calls: list[str] = []
    sync, _ = _financial_runtime

    def execute(request):
        calls.append(request.asset_code)
        return SimpleNamespace(stored_count=4)

    sync.execute = execute
    monkeypatch.setattr(
        tasks.refresh_financial_publications_batch_task,
        "apply_async",
        lambda **_: (_ for _ in ()).throw(OSError("broker unavailable")),
    )

    first = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
    )

    assert first["outcome"] == "failed"
    assert first["stage"] == "continuation"
    assert first["error_code"] == "financial_refresh_continuation_enqueue_failed"
    assert first["requested"] == 2
    assert first["succeeded"] == 2
    assert first["failed"] == 0
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY) is None
    assert (
        tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_PROGRESS_KEY)["next_offset"] == 2
    )

    monkeypatch.setattr(
        tasks.refresh_financial_publications_batch_task,
        "apply_async",
        lambda **_: SimpleNamespace(id="recovered-continuation"),
    )
    resumed = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
    )

    assert calls == ["000001.SZ", "000002.SZ", "000003.SZ"]
    assert resumed["outcome"] == "success"
    assert resumed["requested"] == 1
    assert resumed["checkpoint"]["complete"] is True
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_PROGRESS_KEY) is None


def test_financial_refresh_recovers_after_worker_lease_expires(
    _financial_runtime,
) -> None:
    active_codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    encoded_universe = json.dumps(
        {"schema": "active-a-share-universe.v1", "asset_codes": active_codes},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    universe_hash = hashlib.sha256(encoded_universe.encode("utf-8")).hexdigest()
    tasks.cache.set(
        financial_refresh_lease.FINANCIAL_REFRESH_PROGRESS_KEY,
        {
            "next_offset": 2,
            "universe_hash": universe_hash,
            "source": "tushare",
            "financial_periods": 8,
            "batch_size": 2,
        },
        timeout=financial_refresh_lease.FINANCIAL_REFRESH_CHECKPOINT_TTL,
    )
    tasks.cache.set(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY, "lost-worker", timeout=0.02)
    time.sleep(0.04)

    result = tasks.refresh_financial_publications_batch_task.run(
        batch_size=2,
        auto_continue=True,
    )

    assert result["outcome"] == "success"
    assert result["requested"] == 1
    assert result["checkpoint"]["offset"] == 2
    assert result["checkpoint"]["complete"] is True
    assert tasks.cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY) is None
