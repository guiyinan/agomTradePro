"""Full-market snapshots must never publish an intermediate or failed batch."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from apps.data_center.application.market_publication_refresh import (
    MarketPublicationRefreshBlocked,
    MarketPublicationRefreshPorts,
    refresh_market_price_inputs,
    refresh_market_publications,
)
from core.exceptions import DataFetchError


def _prefetched_quote_sync(execute: Callable[[object], object]) -> SimpleNamespace:
    """Build a quote-sync test double that exposes the frozen-session contract."""

    prepared = object()
    prepare_calls: list[dict[str, object]] = []

    def prepare_session(**kwargs: object) -> object:
        prepare_calls.append(dict(kwargs))
        return prepared

    return SimpleNamespace(
        prepare_session=prepare_session,
        execute_prefetched_session_batch=lambda request, session: (
            execute(request)
            if session is prepared
            else pytest.fail("quote batch used a different prepared session")
        ),
        prepare_calls=prepare_calls,
    )


def _universe_report(codes: list[str], *, active_count: int | None = None) -> dict[str, object]:
    """Return provider-bound universe evidence for task-path tests."""

    normalized = sorted(codes)
    return {
        "active_count": len(normalized) if active_count is None else active_count,
        "touched_count": len(normalized),
        "active_codes_sha256": hashlib.sha256(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


@pytest.fixture(autouse=True)
def _patch_current_authority(monkeypatch):
    """Bind task-path tests to one current server-issued authority."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    context = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: context,
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(tasks.list_active_stock_codes_for_backfill()),
    )
    return context


def run(*, quote_count=None, publish_error=False, empty=False):
    published = []

    def publish(codes):
        if publish_error:
            raise ValueError("missing policy evidence")
        published.append(codes)
        return len(codes) * 2

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: [] if empty else ["000001.SZ", "000002.SZ", "000003.SZ"],
        sync_quotes=lambda codes: len(codes) if quote_count is None else quote_count,
        sync_valuations=lambda codes, day: len(codes),
        publish=publish,
    )
    return (
        refresh_market_publications(ports=ports, as_of_date=date(2026, 9, 18), batch_size=2),
        published,
    )


def test_complete_market_refresh_publishes_full_scope_once():
    result, published = run()
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 5
    assert result["failed"] == 0
    assert result["stored"] == result["published_members"] == 6
    assert published == [["000001.SZ", "000002.SZ", "000003.SZ"]]


def test_partial_market_refresh_keeps_previous_publication():
    result, published = run(quote_count=0)
    assert result["outcome"] == "partial"
    assert result["requested"] == result["succeeded"] + result["failed"]
    assert result["published_members"] == 0
    assert published == []


def test_terminal_authority_block_stops_remaining_batches() -> None:
    """A task-wide authority loss is recorded once without replaying every batch."""

    quote_calls: list[list[str]] = []

    def blocked_quote(codes: list[str]) -> int:
        quote_calls.append(codes)
        raise MarketPublicationRefreshBlocked(
            "Audit authority is temporarily unavailable",
            code="system_audit_authority_unavailable",
        )

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ", "000002.SZ", "000003.SZ"],
        sync_quotes=blocked_quote,
        sync_valuations=lambda _codes, _day: pytest.fail("valuation batch executed"),
        publish=lambda _codes: pytest.fail("publication executed"),
    )

    result = refresh_market_publications(
        ports=ports,
        as_of_date=date(2026, 9, 18),
        batch_size=2,
    )

    assert quote_calls == [["000001.SZ", "000002.SZ"]]
    assert result["requested"] == 5
    assert result["succeeded"] == 0
    assert result["failed"] == 5
    assert result["errors"] == ["system_audit_authority_unavailable"]
    assert result["phase_results"] == [
        {"phase": "quote", "requested": 2, "succeeded": 0, "failed": 2, "stored": 0},
        {"phase": "valuation", "requested": 2, "succeeded": 0, "failed": 2, "stored": 0},
        {"phase": "publication", "requested": 1, "succeeded": 0, "failed": 1, "stored": 0},
    ]


def test_authority_revalidation_retries_transient_unavailability(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """One lock-contention read cannot poison the remainder of a long refresh."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    calls = 0

    def transient_then_current(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SystemAuditCompositionUnavailable(
                "lock contention",
                reason_code="authority_unavailable",
            )
        return _patch_current_authority

    waits: list[float] = []
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        transient_then_current,
    )
    observed_at = datetime.now(UTC)

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        max_attempts=2,
        retry_delay_seconds=0.25,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=1),
    )

    assert result.current is True
    assert result.reason_code == "authority_current"
    assert result.attempts == 2
    assert waits == [0.25]


def test_authority_revalidation_outlasts_back_to_back_writer_transactions(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """Bounded backoff crosses repeated short writer locks without weakening identity checks."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    calls = 0

    def contended_then_current(**_):
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise SystemAuditCompositionUnavailable(
                "back-to-back writer lock",
                reason_code="authority_unavailable",
            )
        return _patch_current_authority

    waits: list[float] = []
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        contended_then_current,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        max_attempts=6,
        retry_delay_seconds=1.0,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=sum(waits)),
    )

    assert result.current is True
    assert result.reason_code == "authority_current"
    assert result.attempts == 5
    assert waits == [1.0, 2.0, 3.0, 4.0]


def test_authority_revalidation_rejects_unbounded_attempt_override(
    _patch_current_authority,
) -> None:
    """Callers cannot expand the governed authority retry window."""

    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    with pytest.raises(ValueError, match="max_attempts must be between 1 and 6"):
        revalidate_data02_task_authority(
            _patch_current_authority,
            as_of=datetime.now(UTC),
            max_attempts=7,
        )


def test_authority_revalidation_exhaustion_stays_blocked_and_zero_write(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """Six transient read failures exhaust the budget without fabricating progress."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        data02_authority_failure,
        revalidate_data02_task_authority,
    )

    calls = 0

    def unavailable(**_):
        nonlocal calls
        calls += 1
        raise SystemAuditCompositionUnavailable(
            "authority tables remain contended",
            reason_code="authority_unavailable",
        )

    waits: list[float] = []
    observed_at = datetime.now(UTC)
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        unavailable,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=observed_at,
        sleeper=waits.append,
        clock=lambda: observed_at + timedelta(seconds=sum(waits)),
    )
    failure = data02_authority_failure(result.reason_code)

    assert result.current is False
    assert result.reason_code == "system_audit_authority_unavailable"
    assert result.attempts == 6
    assert calls == 6
    assert waits == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert failure["outcome"] == "blocked"
    assert failure["requested"] == 0
    assert failure["succeeded"] == 0
    assert failure["failed"] == 0
    assert failure["stored"] == 0


def test_authority_revalidation_does_not_retry_identity_drift(
    monkeypatch,
    _patch_current_authority,
) -> None:
    """A real actor change remains fail-closed without transient retries."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks
    from apps.data_center.application.data02_task_authority import (
        revalidate_data02_task_authority,
    )

    changed = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "actor_id": "service:other-refresh",
        }
    )
    calls = 0

    def changed_context(**_):
        nonlocal calls
        calls += 1
        return changed

    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        changed_context,
    )

    result = revalidate_data02_task_authority(
        _patch_current_authority,
        as_of=datetime.now(UTC),
        max_attempts=3,
        sleeper=lambda _: pytest.fail("identity drift retried"),
    )

    assert result.current is False
    assert result.reason_code == "operator_actor_mismatch"
    assert result.attempts == 1
    assert calls == 1


def test_provider_identity_gap_is_a_partial_business_result() -> None:
    def reject_valuation(_codes, _day):
        from apps.data_center.application.batch_identity import ProviderAssetIdentityError

        raise ProviderAssetIdentityError("valuation provider asset identities mismatch")

    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ", "000016.SZ"],
        sync_quotes=lambda codes: len(codes),
        sync_valuations=reject_valuation,
        publish=lambda _: pytest.fail("incomplete valuation scope reached publication"),
    )

    result = refresh_market_publications(
        ports=ports,
        as_of_date=date(2026, 9, 23),
        batch_size=2,
    )

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["stored"] == 2
    assert result["published_members"] == 0
    assert result["errors"] == [
        "PROVIDER_ASSET_IDENTITY_MISMATCH",
        "market_publication_skipped_incomplete_refresh",
    ]


def test_publication_evidence_failure_is_not_success():
    result, published = run(publish_error=True)
    assert result["outcome"] == "partial"
    assert result["failed"] == 1
    assert result["error_code"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["blocked_reason"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert result["errors"] == ["MARKET_PUBLICATION_VALIDATION_FAILED"]
    assert published == []


def test_publication_failure_preserves_phase_and_actual_write_counts():
    result, _ = run(publish_error=True)
    assert result["phase"] == "publication"
    assert result["stored_count_unit"] == "fact_row"
    assert result["target_trade_date"] == "2026-09-18"
    assert result["phase_results"] == [
        {"phase": "quote", "requested": 2, "succeeded": 2, "failed": 0, "stored": 3},
        {"phase": "valuation", "requested": 2, "succeeded": 2, "failed": 0, "stored": 3},
        {"phase": "publication", "requested": 1, "succeeded": 0, "failed": 1, "stored": 0},
    ]


def test_failed_quote_phase_is_not_hidden_by_skipped_publication():
    result, _ = run(quote_count=0)
    assert result["phase"] == "quote"
    assert result["phase_results"][0] == {
        "phase": "quote",
        "requested": 2,
        "succeeded": 0,
        "failed": 2,
        "stored": 0,
    }
    assert result["phase_results"][-1]["succeeded"] == 0


def test_empty_scope_is_not_success():
    result, published = run(empty=True)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0
    assert published == []


@pytest.mark.parametrize("count", [True, -1, 0, 1.5, "3", None])
def test_invalid_publication_count_never_reports_success(count):
    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: ["000001.SZ"],
        sync_quotes=lambda codes: len(codes),
        sync_valuations=lambda codes, day: len(codes),
        publish=lambda codes: count,
    )
    result = refresh_market_publications(ports=ports, as_of_date=date(2026, 9, 24))
    assert result["outcome"] == "partial"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["failed"] == 1
    assert result["error_code"] == "MARKET_PUBLICATION_COUNT_INVALID"


@pytest.mark.parametrize("batch_size", [True, 0, 201, "10"])
def test_market_refresh_rejects_invalid_input_before_io(batch_size):
    ports = MarketPublicationRefreshPorts(
        list_codes=lambda: pytest.fail("unexpected IO"),
        sync_quotes=lambda _: 0,
        sync_valuations=lambda *_: 0,
        publish=lambda _: 0,
    )
    with pytest.raises(ValueError):
        refresh_market_publications(
            ports=ports, as_of_date=date(2026, 9, 18), batch_size=batch_size
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": True},
        {"batch_size": 0},
        {"source": "bad"},
        {"quote_source": "bad"},
        {"valuation_source": "bad"},
    ],
)
def test_task_invalid_input_returns_failure_without_provider_access(monkeypatch, kwargs):
    from apps.data_center.application import tasks

    monkeypatch.setattr(
        tasks, "get_active_provider_id_by_source", lambda _: pytest.fail("provider IO")
    )
    result = tasks.refresh_full_market_publications_task.run(**kwargs)
    assert result["outcome"] == "failed"
    assert result["stored"] == 0


def test_task_calendar_unavailable_is_blocked(monkeypatch):
    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: None)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: SimpleNamespace())
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: SimpleNamespace()
    )
    monkeypatch.setattr(
        tasks, "make_core_current_publication_rebuild_use_case", lambda **_: SimpleNamespace()
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["stored"] == 0


def test_task_blocks_without_current_authority_before_provider_access(monkeypatch):
    """Scheduled market writes require the canonical current Audit authority."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks

    def unavailable(**_):
        raise SystemAuditCompositionUnavailable(
            "unavailable",
            reason_code="authority_unavailable",
        )

    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        unavailable,
    )
    provider = monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert provider is None
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_authority_unavailable"
    assert result["stored"] == 0


def test_task_blocks_authority_window_shorter_than_task_budget(
    monkeypatch,
    _patch_current_authority,
):
    """A scheduled refresh cannot outlive the authority used to start it."""

    from apps.data_center.application import tasks

    assert tasks.refresh_full_market_publications_task.time_limit == 4500
    assert tasks.refresh_full_market_publications_task.soft_time_limit == 4200
    _patch_current_authority.authority_valid_until = datetime.now(UTC) + timedelta(seconds=4799)
    monkeypatch.setattr(
        tasks,
        "get_active_provider_id_by_source",
        lambda _: pytest.fail("provider IO"),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_window_too_short"
    assert result["stored"] == 0


def test_task_stops_before_provider_when_authority_identity_changes(monkeypatch):
    """A scheduled batch must not continue under a different authority identity."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    initial = SimpleNamespace(
        authority_source_id="config-center",
        actor_id="service:market-refresh",
        user_id=1,
        tenant_id="tenant:production",
        owner_id="owner:production",
        is_authenticated=True,
        is_staff=True,
        role="system_owner",
        authority_content_hash="b" * 64,
        authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
    )
    changed = SimpleNamespace(
        authority_source_id=initial.authority_source_id,
        actor_id="service:other-refresh",
        user_id=initial.user_id,
        tenant_id=initial.tenant_id,
        owner_id=initial.owner_id,
        is_authenticated=initial.is_authenticated,
        is_staff=initial.is_staff,
        role=initial.role,
        authority_content_hash="c" * 64,
        authority_valid_until=initial.authority_valid_until,
    )
    contexts = iter((initial, changed))
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: next(contexts),
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ"],
    )
    quote = SimpleNamespace(
        execute=lambda *_args, **_kwargs: pytest.fail("quote provider called after authority drift")
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=1)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "operator_actor_mismatch"
    assert result["stored"] == 0


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_reason", "provider_details"),
    [
        pytest.param(
            ValueError("secret upstream response"),
            "MARKET_UNIVERSE_REFRESH_FAILED",
            "market_universe_refresh_failed",
            None,
            id="unknown-provider-error-is-redacted",
        ),
        pytest.param(
            DataFetchError(
                "secret upstream response",
                code="A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT",
                details={"source": "tushare.stock_basic[provider_id=7]", "tolerance": 0.01},
            ),
            "A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT",
            "a_share_universe_failover_inconsistent",
            {"source": "tushare.stock_basic[provider_id=7]", "tolerance": 0.01},
            id="classified-provider-error-keeps-code-and-provenance",
        ),
    ],
)
def test_task_exposes_stable_universe_refresh_error(
    monkeypatch,
    failure: Exception,
    expected_code: str,
    expected_reason: str,
    provider_details: dict[str, object] | None,
) -> None:
    """Provider exception text stays out of the user-facing task result."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(),
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: (_ for _ in ()).throw(failure),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == expected_reason
    assert result["error_code"] == expected_code
    assert result["errors"] == [expected_code]
    if provider_details is not None:
        assert result["market_universe_error"] == provider_details
    else:
        assert "market_universe_error" not in result
    assert "secret" not in str(result)


def test_task_blocks_partial_valuation_seed_without_verified_scope_exclusions(monkeypatch):
    """A provider omission cannot silently reduce the active publication denominator."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    active_codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    policy = SimpleNamespace(
        dataset=SimpleNamespace(value="equity.valuation.fact"),
        allow_partial=True,
        uses_versioned_evidence=True,
        minimum_coverage_ratio=0.99,
        identity="p2:valuation-current-v1:" + "a" * 64,
    )
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: policy),
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(active_codes),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: list(active_codes),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: SimpleNamespace(
            execute=lambda *_args, **_kwargs: pytest.fail(
                "quote provider called after incomplete valuation scope"
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(
            execute=lambda **_kwargs: SimpleNamespace(
                stored_count=1,
                status="partial",
                succeeded_asset_codes=("000001.SZ",),
                returned_asset_codes=("000001.SZ",),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: pytest.fail("incomplete scope reached publication preview"),
            execute=lambda **_: pytest.fail("incomplete scope reached publication"),
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["requested"] == 3
    assert result["succeeded"] == 1
    assert result["failed"] == 2
    assert result["stored"] == 1
    assert result["count_unit"] == "valuation_asset"
    assert result["operation_requested"] == 1
    assert result["operation_succeeded"] == 0
    assert result["operation_failed"] == 1
    assert result["requested_asset_count"] == 3
    assert result["succeeded_asset_count"] == 1
    assert result["failed_asset_count"] == 2
    assert result["missing_asset_codes"] == ["000002.SZ", "000003.SZ"]
    assert result["excluded_non_trading_codes"] == []
    assert result["error_code"] == "CURRENT_VALUATION_SCOPE_INCOMPLETE"
    assert result["blocked_reason"] == "current_valuation_scope_incomplete"


def test_task_publishes_policy_allowed_partial_valuation_and_reports_asset_counts(monkeypatch):
    """A bounded valuation gap remains visible without blocking qualified assets."""

    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    progress_snapshots = []
    monkeypatch.setattr(
        tasks,
        "record_current_task_progress",
        lambda progress: progress_snapshots.append(progress) or True,
    )

    active_codes = [f"{index:06d}.SZ" for index in range(100)]
    succeeded_codes = tuple(active_codes[:-1])
    missing_code = active_codes[-1]
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    policy = SimpleNamespace(
        dataset=SimpleNamespace(value="equity.valuation.fact"),
        allow_partial=True,
        uses_versioned_evidence=True,
        minimum_coverage_ratio=0.99,
        identity="p2:valuation-current-v1:" + "a" * 64,
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: list(active_codes))
    monkeypatch.setattr(
        tasks,
        "get_publication_policy_repository",
        lambda: SimpleNamespace(get_active=lambda _dataset: policy),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: _prefetched_quote_sync(
            lambda request: SimpleNamespace(
                stored_count=len(request.asset_codes),
                stored_asset_codes=tuple(request.asset_codes),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(
            execute=lambda **_: SimpleNamespace(
                stored_count=len(succeeded_codes),
                status="partial",
                succeeded_asset_codes=succeeded_codes,
                returned_asset_codes=succeeded_codes,
            )
        ),
    )
    quote_preview = SimpleNamespace(
        dataset_key="equity.quote.snapshot",
        ready=True,
        oldest_observed_at=observed,
        newest_observed_at=observed,
    )
    valuation_preview = SimpleNamespace(
        dataset_key="equity.valuation.fact",
        ready=False,
        covered_asset_count=len(succeeded_codes),
        missing_asset_codes=(missing_code,),
        unexpected_asset_codes=(),
        oldest_observed_at=observed,
        newest_observed_at=observed,
    )
    publication_id = "bf8c00f5-59df-42c0-a3cb-44d2e306d668"
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: SimpleNamespace(datasets=[quote_preview, valuation_preview]),
            execute=lambda **kwargs: SimpleNamespace(
                published_count=299,
                to_dict=lambda: {
                    "published_count": 299,
                    "publication_ids": [publication_id],
                    "datasets": [
                        {
                            "dataset_key": "equity.valuation.fact",
                            "scope_blocks": [
                                {
                                    "asset_code": missing_code,
                                    "reason_code": "valuation_source_data_unavailable",
                                    "target_trade_date": "2026-09-18",
                                    "source": "akshare",
                                    "publication_run_id": kwargs["run_id"],
                                    "policy_version": policy.identity,
                                    "publication_id": publication_id,
                                }
                            ],
                        }
                    ],
                    "run_id": kwargs["run_id"],
                },
            ),
        ),
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: (),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=100)

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["publication_updated"] is True
    assert result["requested"] == 100
    assert result["succeeded"] == 99
    assert result["failed"] == 1
    assert result["stored"] == 199
    assert result["missing_asset_codes"] == [missing_code]
    assert result["scope_blocks"] == [
        {
            "asset_code": missing_code,
            "reason_code": "valuation_source_data_unavailable",
            "target_trade_date": "2026-09-18",
            "source": "akshare",
            "publication_run_id": result["publication_run_id"],
            "policy_version": policy.identity,
            "publication_id": publication_id,
        }
    ]
    assert result["excluded_non_trading_codes"] == []
    assert result["publication_run_id"] == result["run_id"]
    assert progress_snapshots[0].phase == "universe"
    assert progress_snapshots[0].requested == 1
    assert progress_snapshots[0].succeeded == 0
    assert progress_snapshots[0].stored is None
    assert [phase.phase for phase in progress_snapshots[-1].phase_results] == [
        "universe",
        "scope",
        "valuation",
        "quote_prefetch",
        "quote",
        "publication",
    ]
    phase_results = {phase.phase: phase for phase in progress_snapshots[-1].phase_results}
    assert phase_results["universe"].requested == 1
    assert phase_results["universe"].succeeded == 1
    assert phase_results["universe"].stored == len(active_codes)
    assert phase_results["universe"].stored_count_unit == "universe_asset"
    assert phase_results["scope"].requested == 1
    assert phase_results["scope"].succeeded == 1
    assert phase_results["scope"].stored == len(active_codes)
    assert phase_results["scope"].stored_count_unit == "universe_asset"
    assert phase_results["valuation"].requested == len(active_codes)
    assert phase_results["valuation"].succeeded == len(succeeded_codes)
    assert phase_results["valuation"].failed == 1
    assert phase_results["valuation"].stored == len(succeeded_codes)
    assert phase_results["valuation"].count_unit == "valuation_asset"
    assert phase_results["valuation"].stored_count_unit == "fact_row"
    assert phase_results["quote_prefetch"].requested == 1
    assert phase_results["quote_prefetch"].succeeded == 1
    assert phase_results["quote_prefetch"].stored == 0
    assert phase_results["quote_prefetch"].count_unit == "provider_request"
    assert phase_results["quote"].requested == 1
    assert phase_results["quote"].succeeded == 1
    assert phase_results["quote"].stored == len(active_codes)
    assert phase_results["quote"].stored_count_unit == "fact_row"
    assert phase_results["publication"].count_unit == "sync_operation"
    assert phase_results["publication"].stored_count_unit == "publication_member"
    quote_in_progress = next(
        progress
        for progress in progress_snapshots
        if progress.phase == "quote" and progress.succeeded == 0
    )
    assert quote_in_progress.requested == 1
    assert quote_in_progress.stored == 0
    assert progress_snapshots[-1].phase == "publication"
    assert progress_snapshots[-1].succeeded == 1
    assert progress_snapshots[-1].stored == 299
    assert progress_snapshots[-1].stored_count_unit == "publication_member"


def test_task_reports_quote_prefetch_failure_before_any_quote_write(monkeypatch):
    """A failed full-session read keeps seed evidence and never enters batch writes."""

    from apps.data_center.application import tasks

    active_codes = ["000001.SZ", "600000.SH"]
    progress_snapshots = []
    monkeypatch.setattr(
        tasks,
        "record_current_task_progress",
        lambda progress: progress_snapshots.append(progress) or True,
    )
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: active_codes)

    def fail_prefetch(**_: object) -> object:
        raise DataFetchError("provider rejected", code="TUSHARE_PROVIDER_REJECTED")

    quote = SimpleNamespace(
        prepare_session=fail_prefetch,
        execute_prefetched_session_batch=lambda *_: pytest.fail("quote batch write executed"),
    )
    valuation = SimpleNamespace(
        execute=lambda **_: SimpleNamespace(
            stored_count=2,
            status="success",
            succeeded_asset_codes=tuple(active_codes),
            returned_asset_codes=tuple(active_codes),
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **__: pytest.fail("publication preview executed"),
            execute=lambda **__: pytest.fail("publication write executed"),
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["phase"] == "quote"
    assert result["requested"] == 2
    assert result["succeeded"] == 0
    assert result["failed"] == 2
    assert result["stored"] == 2
    assert result["count_unit"] == "quote_asset"
    assert result["error_code"] == "TUSHARE_PROVIDER_REJECTED"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert progress_snapshots[-1].phase == "quote_prefetch"
    assert progress_snapshots[-1].failed == 1
    assert progress_snapshots[-1].stored == 0


def test_task_verifies_dynamic_quote_gap_and_publishes_full_scope_with_exclusion(monkeypatch):
    """A proven suspension narrows quote writes while publication keeps the frozen denominator."""

    from apps.data_center.application import market_publication_refresh, tasks

    target = date(2026, 9, 18)
    active_codes = ["000001.SZ", "600000.SH"]
    excluded = active_codes[1]
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: target)
    monkeypatch.setattr(
        tasks, "sync_active_a_share_universe", lambda: _universe_report(active_codes)
    )
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: list(active_codes))

    quote_calls: list[tuple[str, ...]] = []
    verify_calls: list[tuple[str, ...]] = []

    def prepare_session(**kwargs: object) -> SimpleNamespace:
        verifier = kwargs["missing_asset_verifier"]
        assert callable(verifier)
        verified = verifier((excluded,), target)
        verify_calls.append(tuple(verified))
        return SimpleNamespace(
            universe_codes=tuple(active_codes),
            available_codes=(active_codes[0],),
            eligible_codes=(active_codes[0],),
            excluded_codes=(excluded,),
        )

    quote = SimpleNamespace(
        prepare_session=prepare_session,
        execute_prefetched_session_batch=lambda request, _session: (
            quote_calls.append(tuple(request.asset_codes))
            or SimpleNamespace(
                stored_count=len(request.asset_codes),
                stored_asset_codes=tuple(request.asset_codes),
            )
        ),
    )
    valuation = SimpleNamespace(
        execute=lambda **_: SimpleNamespace(
            stored_count=len(active_codes),
            succeeded_asset_codes=tuple(active_codes),
            returned_asset_codes=tuple(active_codes),
            status="success",
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation
    )

    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    datasets = [
        SimpleNamespace(
            dataset_key="equity.quote.snapshot",
            ready=False,
            covered_asset_count=1,
            missing_asset_codes=(excluded,),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        ),
        SimpleNamespace(
            dataset_key="equity.valuation.fact",
            ready=True,
            covered_asset_count=len(active_codes),
            missing_asset_codes=(),
            unexpected_asset_codes=(),
            oldest_observed_at=observed,
            newest_observed_at=observed,
        ),
    ]
    publication_calls: list[dict[str, object]] = []

    def execute_publication(**kwargs: object) -> SimpleNamespace:
        publication_calls.append(dict(kwargs))
        run_id = str(kwargs["run_id"])
        block = {
            "asset_code": excluded,
            "reason_code": "quote_full_day_suspension",
            "target_trade_date": target.isoformat(),
            "source": "tushare",
            "publication_run_id": run_id,
            "policy_version": "p2:quote-current-v1:policy-digest",
            "publication_id": "quote-publication-20260918",
            "evidence_source": "tushare.suspend_d",
        }
        return SimpleNamespace(
            published_count=1,
            to_dict=lambda: {
                "published_count": 1,
                "run_id": run_id,
                "datasets": [
                    {
                        "dataset_key": "equity.quote.snapshot",
                        "scope_blocks": [block],
                    }
                ],
            },
        )

    preview_calls: list[dict[str, object]] = []

    def preview_publication(**kwargs: object) -> SimpleNamespace:
        preview_calls.append(dict(kwargs))
        return SimpleNamespace(datasets=datasets)

    publication = SimpleNamespace(
        preview=preview_publication,
        execute=execute_publication,
    )
    monkeypatch.setattr(
        tasks, "make_core_current_publication_rebuild_use_case", lambda **_: publication
    )
    monkeypatch.setattr(tasks.public_services, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda _port, codes, _target: ((excluded,) if tuple(codes) == (excluded,) else (excluded,)),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert verify_calls == [(excluded,)]
    assert quote_calls == [(active_codes[0],)]
    assert result["excluded_non_trading_codes"] == [excluded]
    assert result["missing_asset_codes"] == [excluded]
    assert result["requested"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["quote_eligible_asset_count"] == 1
    assert result["quote_selected_asset_count"] == 1
    assert result["suspension_evidence_source"] == "tushare.suspend_d"
    assert result["quote_scope_blocks"][0]["asset_code"] == excluded
    assert result["scope_blocks"] == result["quote_scope_blocks"]
    assert "全天停牌" in result["scope_notice"]
    assert result.get("must_not_use_for_decision") is not True
    assert publication_calls[0]["asset_codes"] == active_codes
    exclusions = publication_calls[0]["scope_exclusions_by_dataset"]["equity.quote.snapshot"]
    assert exclusions[0].asset_code == excluded
    assert exclusions[0].reason_code == "quote_full_day_suspension"
    assert preview_calls[0]["asset_codes"] == active_codes
    assert (
        preview_calls[0]["scope_exclusions_by_dataset"]
        == publication_calls[0]["scope_exclusions_by_dataset"]
    )


def test_task_blocks_when_refreshed_universe_count_differs_from_frozen_codes(monkeypatch):
    """The refreshed active count is the denominator and cannot be silently reduced."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000002.SZ"], active_count=3),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["error_code"] == "MARKET_UNIVERSE_SCOPE_INVALID"
    assert result["blocked_reason"] == "market_universe_scope_invalid"
    assert result["publication_updated"] is False
    assert result["published_members"] == 0
    assert result["requested_asset_count"] == 2
    assert result["market_universe"]["active_count"] == 3


def test_task_blocks_same_count_universe_identity_substitution(monkeypatch):
    """Equal counts cannot hide a different provider-observed security identity."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000003.SZ"]),
    )
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", SimpleNamespace)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=lambda **_: pytest.fail("valuation provider called")),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(preview=lambda **_: pytest.fail("publication preview called")),
    )

    result = tasks.refresh_full_market_publications_task.run()

    assert result["outcome"] == "blocked"
    assert result["error_code"] == "MARKET_UNIVERSE_SCOPE_INVALID"
    assert result["frozen_universe_sha256"] != result["reported_universe_sha256"]
    assert result["publication_updated"] is False


def test_equivalent_authority_successor_does_not_interrupt_active_refresh(
    monkeypatch,
    _patch_current_authority,
):
    """An append-only renewal with the same identity may rotate the authority hash."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    successor = SimpleNamespace(
        **{
            **vars(_patch_current_authority),
            "authority_content_hash": "c" * 64,
            "authority_valid_until": datetime.now(UTC) + timedelta(hours=3),
        }
    )
    monkeypatch.setattr(
        tasks.audit_integration,
        "preflight_data_reliability_audit_runtime",
        lambda **_: successor,
    )

    assert tasks._same_data02_task_authority_is_current(
        _patch_current_authority,
        as_of=datetime.now(UTC),
    )


def test_audit_configuration_blocks_before_market_fetch(monkeypatch):
    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)

    def unavailable():
        raise SystemAuditCompositionUnavailable("unavailable", reason_code="audit_runtime_disabled")

    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", unavailable)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: pytest.fail("unexpected valuation fetch"),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "system_audit_audit_runtime_disabled"
    assert result["stored"] == 0


def test_task_does_not_publish_stale_quotes_even_when_all_rows_were_stored(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])

    def execute_sync(*_: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )

    quote_sync = _prefetched_quote_sync(execute_sync)
    valuation_sync = SimpleNamespace(execute=execute_sync)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote_sync)
    monkeypatch.setattr(
        tasks, "make_backfill_sync_current_valuation_batch_use_case", lambda: valuation_sync
    )
    preview = SimpleNamespace(
        ready=True,
        datasets=[
            SimpleNamespace(
                dataset_key="equity.quote.snapshot",
                ready=True,
                oldest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
                newest_observed_at=datetime(2026, 9, 17, 7, tzinfo=UTC),
            )
        ],
    )
    composition_calls = []

    def build_publications(**kwargs):
        composition_calls.append(kwargs)
        return SimpleNamespace(
            preview=lambda **_: preview, execute=lambda **_: pytest.fail("published stale scope")
        )

    monkeypatch.setattr(tasks, "make_core_current_publication_rebuild_use_case", build_publications)
    result = tasks.refresh_full_market_publications_task.run()
    assert result["outcome"] == "partial"
    assert result["published_members"] == 0
    assert composition_calls[0]["created_by"] == (
        "celery.full_market_refresh:service:market-refresh"
    )


@pytest.mark.parametrize(
    ("quote_codes", "valuation_succeeded_codes", "expected_outcome"),
    [
        (("000001.SZ", "000001.SZ"), ("000001.SZ", "000002.SZ"), "partial"),
        (("000001.SZ", "000002.SZ"), ("000001.SZ", "000001.SZ"), "blocked"),
    ],
)
def test_task_rejects_duplicate_provider_asset_identities_before_publication(
    monkeypatch,
    quote_codes,
    valuation_succeeded_codes,
    expected_outcome,
):
    """A count-equal duplicate batch cannot reach full-market publication."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda _: 3)
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "000002.SZ"],
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "000002.SZ"]),
    )
    quote = _prefetched_quote_sync(
        lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            stored_asset_codes=quote_codes,
        )
    )
    valuation = SimpleNamespace(
        execute=lambda *_args, **_kwargs: SimpleNamespace(
            stored_count=2,
            succeeded_asset_codes=valuation_succeeded_codes,
            returned_asset_codes=("000001.SZ", "000002.SZ"),
        )
    )
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: valuation,
    )
    publication = SimpleNamespace(
        preview=lambda **_: pytest.fail("duplicate quote batch reached preview"),
        execute=lambda **_: pytest.fail("duplicate quote batch reached publication"),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: publication,
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == expected_outcome
    assert result.get("published_members", 0) == 0


def test_market_dataset_selection_retains_default_financial_rebuild():
    from apps.data_center.composition import make_core_current_publication_rebuild_use_case

    default = make_core_current_publication_rebuild_use_case()
    assert len(default._rebuilders) == 4
    selected = make_core_current_publication_rebuild_use_case(
        dataset_keys=("equity.quote.snapshot", "equity.valuation.fact")
    )
    assert {item.dataset.dataset_key for item in selected._rebuilders} == {
        "equity.quote.snapshot",
        "equity.valuation.fact",
    }
    for keys in [(), ("bad",), ("equity.price.bar", "equity.price.bar")]:
        with pytest.raises(ValueError):
            make_core_current_publication_rebuild_use_case(dataset_keys=keys)


@pytest.mark.parametrize("reason", ["MODEL_MARKET_STALE", "MODEL_MARKET_SOURCE_CONFLICT"])
def test_price_stage_never_publishes_stale_or_conflicting_existing_facts(reason):
    from types import SimpleNamespace

    def fail(*args):
        raise DataFetchError("invalid", code=reason)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(
            SimpleNamespace(stock_history=fail), ["000001.SZ"], date(2026, 9, 18)
        )
    assert caught.value.code == reason


def test_price_stage_prefetches_only_target_session_at_full_market_scale():
    """Full-market validation must reuse one target-session prefetch, not Qlib history."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    codes = [f"{value:06d}.SZ" for value in range(1, 5570)]

    class PreparedPort:
        def __init__(self):
            self.prepare_calls = []
            self.provider_batch_requests = 0
            self.per_asset_provider_requests = []
            self.prepared_rows = {}

        def prepare_stock_history(self, asset_codes, start_date, end_date):
            self.prepare_calls.append((asset_codes, start_date, end_date))
            self.provider_batch_requests += 1
            self.prepared_codes = set(asset_codes)
            self.prepared_rows = {
                code: (SimpleNamespace(trade_date=target),) for code in asset_codes
            }

        def stock_history(self, asset_code, start_date, end_date):
            assert (start_date, end_date) == (target, target)
            assert asset_code in self.prepared_codes
            if asset_code not in self.prepared_rows:
                self.per_asset_provider_requests.append(asset_code)
                return ()
            return self.prepared_rows[asset_code]

    port = PreparedPort()

    assert refresh_market_price_inputs(port, codes, target) == ()
    assert port.prepare_calls == [(tuple(codes), target, target)]
    assert port.provider_batch_requests == 1
    assert port.per_asset_provider_requests == []


def test_price_stage_expands_only_missing_assets_for_native_suspension_evidence():
    """Only missing target-session members may use the bounded history fallback."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)
    missing_code = "000016.SZ"
    calls = []

    class Port:
        def prepare_stock_history(self, asset_codes, start_date, end_date):
            calls.append(("prepare", asset_codes, start_date, end_date))

        def stock_history(self, asset_code, start_date, end_date):
            calls.append(("read", asset_code, start_date, end_date))
            if start_date == target:
                if asset_code == missing_code:
                    raise DataFetchError("missing target session", code="MODEL_MARKET_UNAVAILABLE")
                return (SimpleNamespace(trade_date=target),)
            assert start_date == target - timedelta(days=120)
            assert asset_code == missing_code
            raise DataFetchError(
                "verified suspension",
                code="MODEL_MARKET_SUSPENDED",
                details={"asset_code": missing_code, "suspended_through": target.isoformat()},
            )

    assert refresh_market_price_inputs(
        Port(), ["000001.SZ", missing_code, "000002.SZ"], target
    ) == (missing_code,)
    assert calls[0] == ("prepare", ("000001.SZ", missing_code, "000002.SZ"), target, target)
    assert [call[1] for call in calls if call[0] == "read" and call[2] != target] == [missing_code]


def test_price_stage_rejects_unverified_suspension_after_missing_target_read():
    """A historical gap without exact target-day suspension evidence still blocks."""
    from types import SimpleNamespace

    target = date(2026, 9, 18)

    class Port:
        def stock_history(self, asset_code, start_date, end_date):
            if start_date == target:
                raise DataFetchError("missing target session", code="MODEL_MARKET_UNAVAILABLE")
            return (SimpleNamespace(trade_date=target - timedelta(days=1)),)

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(Port(), ["000016.SZ"], target)
    assert caught.value.code == "MODEL_MARKET_STALE"


def test_price_stage_does_not_expand_provider_rejection_into_history_requests():
    """Provider rejection is a terminal route error, not evidence of a missing price."""
    target = date(2026, 9, 18)
    calls = []

    class Port:
        def stock_history(self, asset_code, start_date, end_date):
            calls.append((asset_code, start_date, end_date))
            raise DataFetchError("rejected", code="TUSHARE_PROVIDER_REJECTED")

    with pytest.raises(DataFetchError) as caught:
        refresh_market_price_inputs(Port(), ["000001.SZ"], target)
    assert caught.value.code == "TUSHARE_PROVIDER_REJECTED"
    assert calls == [("000001.SZ", target, target)]


@pytest.mark.parametrize("evidence_date", ["2026-09-18", "2026-09-17"])
def test_price_stage_requires_target_bound_suspension_evidence(evidence_date):
    from types import SimpleNamespace

    def read(code, start, end):
        if code == "000001.SZ":
            return [SimpleNamespace(trade_date=end)]
        raise DataFetchError(
            "suspended",
            code="MODEL_MARKET_SUSPENDED",
            details={"asset_code": code, "suspended_through": evidence_date},
        )

    port = SimpleNamespace(stock_history=read)
    if evidence_date == "2026-09-18":
        assert refresh_market_price_inputs(port, ["000001.SZ", "000016.SZ"], date(2026, 9, 18)) == (
            "000016.SZ",
        )
    else:
        with pytest.raises(DataFetchError):
            refresh_market_price_inputs(port, ["000016.SZ"], date(2026, 9, 18))


def test_task_repairs_missing_price_scope_before_final_publication(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from apps.data_center.application import market_publication_refresh, public, tasks

    events = []
    provider_ids = {"tushare": 3, "akshare": 7}
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda name: provider_ids[name])
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(tasks, "list_active_stock_codes_for_backfill", lambda: ["000001.SZ"])
    quote_provider_ids = []
    valuation_provider_ids = []

    def sync_quote(request):
        quote_provider_ids.append(request.provider_id)
        return SimpleNamespace(
            stored_count=1,
            stored_asset_codes=("000001.SZ",),
        )

    def sync_valuation(**kwargs):
        valuation_provider_ids.append(kwargs["provider_id"])
        return SimpleNamespace(
            stored_count=1,
            succeeded_asset_codes=("000001.SZ",),
            returned_asset_codes=("000001.SZ",),
        )

    quote_sync = _prefetched_quote_sync(sync_quote)
    monkeypatch.setattr(tasks, "make_backfill_sync_quote_use_case", lambda: quote_sync)
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(execute=sync_valuation),
    )
    observed = datetime(2026, 9, 18, 7, tzinfo=UTC)
    datasets = [
        SimpleNamespace(
            dataset_key=key, ready=True, oldest_observed_at=observed, newest_observed_at=observed
        )
        for key in ("equity.quote.snapshot", "equity.valuation.fact")
    ]
    datasets.append(SimpleNamespace(dataset_key="equity.price.bar", ready=False))
    publication_id = "bf8c00f5-59df-42c0-a3cb-44d2e306d668"
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: SimpleNamespace(ready=False, datasets=datasets),
            execute=lambda **kwargs: (
                events.append("publish")
                or SimpleNamespace(
                    published_count=3,
                    to_dict=lambda: {
                        "published_count": 3,
                        "publication_ids": [publication_id],
                        "datasets": [
                            {
                                "dataset_key": "equity.quote.snapshot",
                                "publication_id": publication_id,
                                "publication_hash": "a" * 64,
                            }
                        ],
                        "run_id": kwargs["run_id"],
                    },
                )
            ),
        ),
    )
    monkeypatch.setattr(public, "get_model_market_data_port", lambda: object())
    monkeypatch.setattr(
        market_publication_refresh,
        "refresh_market_price_inputs",
        lambda *_: (events.append("refresh_prices") or ()),
    )
    result = tasks.refresh_full_market_publications_task.run()
    assert events == ["refresh_prices", "publish"]
    assert result["outcome"] == "success"
    assert result["price_scope_verified"] == 1
    assert result["publication_ids"] == [publication_id]
    assert result["publication_run_id"] == result["run_id"]
    assert result["quote_source"] == "tushare"
    assert result["valuation_source"] == "akshare"
    assert len(quote_sync.prepare_calls) == 1
    prepare_call = quote_sync.prepare_calls[0]
    assert callable(prepare_call["missing_asset_verifier"])
    assert {
        key: value for key, value in prepare_call.items() if key != "missing_asset_verifier"
    } == {
        "provider_id": 3,
        "asset_codes": ("000001.SZ",),
        "target_trade_date": date(2026, 9, 18),
    }
    assert quote_provider_ids == [3]
    assert valuation_provider_ids == [7]


def test_task_reports_business_outcome_when_publication_hits_soft_time_limit(monkeypatch):
    """A worker timeout must preserve the completed write counts and failed phase."""

    from types import SimpleNamespace

    from apps.data_center.application import tasks

    provider_ids = {"tushare": 3, "akshare": 7}
    monkeypatch.setattr(tasks, "get_active_provider_id_by_source", lambda name: provider_ids[name])
    monkeypatch.setattr(tasks, "latest_closed_cn_market_session", lambda _: date(2026, 9, 18))
    monkeypatch.setattr(
        tasks,
        "list_active_stock_codes_for_backfill",
        lambda: ["000001.SZ", "600000.SH"],
    )
    monkeypatch.setattr(
        tasks,
        "sync_active_a_share_universe",
        lambda: _universe_report(["000001.SZ", "600000.SH"]),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_quote_use_case",
        lambda: _prefetched_quote_sync(
            lambda *_args, **_kwargs: SimpleNamespace(
                stored_count=2,
                stored_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_backfill_sync_current_valuation_batch_use_case",
        lambda: SimpleNamespace(
            execute=lambda *_args, **_kwargs: SimpleNamespace(
                stored_count=2,
                succeeded_asset_codes=("000001.SZ", "600000.SH"),
                returned_asset_codes=("000001.SZ", "600000.SH"),
            )
        ),
    )
    monkeypatch.setattr(
        tasks,
        "make_core_current_publication_rebuild_use_case",
        lambda **_: SimpleNamespace(
            preview=lambda **_: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
            execute=lambda **_: pytest.fail("timed-out preview reached publication"),
        ),
    )

    result = tasks.refresh_full_market_publications_task.run(batch_size=2)

    assert result["outcome"] == "failed"
    assert result["requested"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["stored"] == 4
    assert result["phase"] == "publication"
    assert result["error_code"] == "MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED"
    assert result["publication_updated"] is False
    assert result["must_not_use_for_decision"] is True
    assert result["publication_run_id"]
