"""T3B Alpha operational contracts for locks, refreshes, and evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.alpha.application import ops_services, ops_use_cases, tasks
from apps.alpha.domain.entities import AlphaPoolScope

TARGET_DATE = date(2026, 7, 24)


def _summary() -> SimpleNamespace:
    return SimpleNamespace(
        requested_target_date=TARGET_DATE,
        effective_target_date=TARGET_DATE,
        latest_local_date_before=date(2026, 7, 23),
        latest_local_date_after=TARGET_DATE,
        calendar_days_written=2,
        instrument_files_written=3,
        feature_series_written=12,
        stock_count=2,
        universe_count=1,
        warning_messages=("one delayed quote",),
    )


def _scope() -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ", "600000.SH"),
        selection_reason="T3B ops",
        trade_date=TARGET_DATE,
        display_label="portfolio-7",
        portfolio_id=7,
        portfolio_name="portfolio-7",
    )


def test_ops_serializers_preserve_valid_and_malformed_task_evidence() -> None:
    """Operational payload helpers normalize inputs without hiding malformed results."""
    assert ops_services._parse_universe_list(None) == ["csi300"]
    assert ops_services._parse_universe_list(" CSI300, ,CSI500 ") == [
        "csi300",
        "csi500",
    ]
    assert ops_services._parse_universe_list((" CSI1000 ", "")) == ["csi1000"]
    assert ops_services._serialize_task_result(None) is None
    assert ops_services._serialize_task_result("{'status': 'partial'}") == {"status": "partial"}
    assert ops_services._serialize_task_result("{broken") == "{broken"
    assert ops_services._to_iso(None) is None
    assert ops_services._to_iso(TARGET_DATE) == TARGET_DATE.isoformat()
    assert ops_services._to_iso(7) == "7"


def test_runtime_refresh_service_handles_disabled_empty_and_successful_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime refresh rejects disabled/empty work and serializes builder evidence."""
    service = ops_services.QlibRuntimeDataRefreshService()
    monkeypatch.setattr(service, "get_runtime_config", lambda: {"enabled": False})
    assert service.refresh_universes(target_date=TARGET_DATE)["reason"] == "qlib_disabled"
    assert (
        service.refresh_codes(target_date=TARGET_DATE, stock_codes=["000001.SZ"])["reason"]
        == "qlib_disabled"
    )

    monkeypatch.setattr(
        service,
        "get_runtime_config",
        lambda: {"enabled": True, "provider_uri": "local-data"},
    )
    assert (
        service.refresh_codes(target_date=TARGET_DATE, stock_codes=["", "  "])["reason"]
        == "empty_stock_scope"
    )

    calls: list[tuple[str, object]] = []

    class _Builder:
        def __init__(self, provider_uri: str) -> None:
            calls.append(("provider_uri", provider_uri))

        def build_recent_data(self, **kwargs: object) -> SimpleNamespace:
            calls.append(("universes", kwargs["universes"]))
            return _summary()

        def build_recent_data_for_codes(self, **kwargs: object) -> SimpleNamespace:
            calls.append(("codes", kwargs["stock_codes"]))
            return _summary()

    monkeypatch.setattr(ops_services, "TushareQlibBuilder", _Builder)
    universe_result = service.refresh_universes(
        target_date=TARGET_DATE,
        universes="CSI300, csi500",
        lookback_days=30,
    )
    code_result = service.refresh_codes(
        target_date=TARGET_DATE,
        stock_codes=["000001", "000001.SZ", "600000"],
        universe_id="portfolio",
    )
    assert universe_result["status"] == "success"
    assert universe_result["warning_messages"] == ["one delayed quote"]
    assert code_result["status"] == "success"
    assert code_result["stock_count"] == 2
    assert ("codes", ["000001.SZ", "600000.SH"]) in calls


def test_alpha_ops_overview_serializes_health_tasks_caches_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ops overview deduplicates task records and keeps health failures visible."""
    service = ops_services.AlphaOpsOverviewQueryService()
    monkeypatch.setattr(
        ops_services,
        "get_celery_health_checker",
        lambda: SimpleNamespace(
            check_health=lambda: (_ for _ in ()).throw(ConnectionError("broker offline"))
        ),
    )
    health = service._get_celery_health()
    assert health["is_healthy"] is False
    assert health["error"] == "broker offline"

    started = datetime(2026, 7, 24, 8, tzinfo=UTC)
    records = {
        "task.a": [
            SimpleNamespace(
                task_id="same",
                task_name="task.a",
                status=SimpleNamespace(value="SUCCESS"),
                started_at=started,
                finished_at=None,
                runtime_seconds=1.2,
                queue="alpha",
                worker="worker-1",
                exception=None,
                result="{'outcome': 'partial'}",
            )
        ],
        "task.b": [
            SimpleNamespace(
                task_id="same",
                task_name="task.b",
                status=SimpleNamespace(value="FAILURE"),
                started_at=None,
                finished_at=started,
                runtime_seconds=2.0,
                queue="alpha",
                worker="worker-2",
                exception="failed",
                result="{malformed",
            )
        ],
    }
    monkeypatch.setattr(
        ops_services,
        "get_task_record_repository",
        lambda: SimpleNamespace(list_by_task_name=lambda name, limit: records.get(name, [])),
    )
    serialized = service._list_recent_tasks(("task.a", "task.b"), limit=10)
    assert len(serialized) == 1
    assert serialized[0]["task_name"] == "task.b"
    assert serialized[0]["result"] == "{malformed"

    cache_row = SimpleNamespace(
        id=1,
        universe_id="csi300",
        scope_hash="scope",
        scope_label="label",
        intended_trade_date=TARGET_DATE,
        asof_date=TARGET_DATE,
        status="available",
        model_artifact_hash="model",
        created_at=started,
        updated_at=started,
        scores=[{"code": "000001.SZ"}],
    )
    alert_row = SimpleNamespace(
        id=2,
        alert_type="coverage",
        severity="warning",
        title="degraded",
        message="cache stale",
        is_resolved=False,
        created_at=started,
        resolved_at=None,
    )
    monkeypatch.setattr(
        ops_services,
        "get_alpha_score_cache_repository",
        lambda: SimpleNamespace(list_recent_qlib_caches=lambda limit: [cache_row]),
    )
    monkeypatch.setattr(
        ops_services,
        "get_alpha_alert_repository",
        lambda: SimpleNamespace(list_recent_alerts=lambda limit: [alert_row]),
    )
    assert service._list_recent_caches(limit=1)[0]["score_count"] == 1
    assert service._list_recent_alerts(limit=1)[0]["resolved_at"] is None


def test_qlib_data_overview_reports_local_inspection_failure_and_summary_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local-data inspection failures remain visible and summary parsing is strict."""
    service = ops_services.QlibDataOpsOverviewQueryService()
    monkeypatch.setattr(
        ops_services,
        "get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        ops_services,
        "inspect_latest_trade_date",
        lambda uri: (_ for _ in ()).throw(OSError("calendar missing")),
    )
    monkeypatch.setattr(
        ops_services.AlphaOpsOverviewQueryService,
        "_list_recent_tasks",
        lambda self, names, limit: [
            {"result": "malformed"},
            {"result": {"summary": {"status": "partial", "stored": 0}}},
        ],
    )
    result = service.build()
    assert result["local_data_status"]["local_data_error"] == "calendar missing"
    assert result["latest_build_summary"] == {"status": "partial", "stored": 0}
    assert service._extract_latest_build_summary(
        [{"result": {"requested_target_date": TARGET_DATE.isoformat()}}]
    ) == {"requested_target_date": TARGET_DATE.isoformat()}
    assert service._extract_latest_build_summary([{"result": "not-a-dict"}]) is None


def test_general_and_scoped_inference_conflicts_and_queue_failures_release_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inference use cases fail idempotently and release pending locks after queue errors."""
    existing = {"task_id": "running", "task_state": "PENDING", "mode": "task"}
    monkeypatch.setattr(
        ops_use_cases,
        "resolve_dashboard_alpha_refresh_lock",
        lambda key: existing,
    )
    conflict = ops_use_cases.TriggerGeneralInferenceUseCase().execute(
        trade_date=TARGET_DATE,
        top_n=10,
        universe_id="csi300",
    )
    assert conflict["success"] is False
    assert conflict["task_id"] == "running"

    monkeypatch.setattr(
        ops_use_cases,
        "resolve_dashboard_alpha_refresh_lock",
        lambda key: None,
    )
    monkeypatch.setattr(
        ops_use_cases,
        "acquire_dashboard_alpha_refresh_pending_lock",
        lambda key, meta: False,
    )
    conflict = ops_use_cases.TriggerGeneralInferenceUseCase().execute(
        trade_date=TARGET_DATE,
        top_n=10,
        universe_id="csi300",
    )
    assert conflict["lock_type"] == "dashboard_alpha_refresh"

    released: list[str] = []
    monkeypatch.setattr(
        ops_use_cases,
        "acquire_dashboard_alpha_refresh_pending_lock",
        lambda key, meta: True,
    )
    monkeypatch.setattr(
        ops_use_cases,
        "release_dashboard_alpha_refresh_lock",
        lambda key: released.append(key),
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("queue offline")),
    )
    with pytest.raises(RuntimeError, match="queue offline"):
        ops_use_cases.TriggerGeneralInferenceUseCase().execute(
            trade_date=TARGET_DATE,
            top_n=10,
            universe_id="csi300",
        )
    assert released

    scope = _scope()
    monkeypatch.setattr(
        ops_use_cases,
        "PortfolioAlphaPoolResolver",
        lambda: SimpleNamespace(
            resolve=lambda **kwargs: SimpleNamespace(
                scope=scope,
                portfolio_id=7,
            )
        ),
    )
    with pytest.raises(RuntimeError, match="queue offline"):
        ops_use_cases.TriggerScopedInferenceUseCase().execute(
            actor_user_id=9,
            trade_date=TARGET_DATE,
            top_n=10,
            portfolio_id=7,
            pool_mode="price_covered",
        )
    assert len(released) == 2


def test_batch_and_refresh_queue_failures_release_their_distinct_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch and both refresh modes roll back only their own pending lock."""
    monkeypatch.setattr(
        ops_use_cases,
        "resolve_recent_closed_trade_date",
        lambda: TARGET_DATE,
    )
    monkeypatch.setattr(ops_use_cases, "resolve_inference_batch_lock", lambda key: None)
    monkeypatch.setattr(
        ops_use_cases,
        "acquire_inference_batch_pending_lock",
        lambda key, meta: True,
    )
    released_batches: list[str] = []
    monkeypatch.setattr(
        ops_use_cases,
        "release_inference_batch_lock",
        lambda key: released_batches.append(key),
    )
    monkeypatch.setattr(
        tasks.qlib_daily_scoped_inference,
        "delay",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("batch queue offline")),
    )
    with pytest.raises(RuntimeError, match="batch queue offline"):
        ops_use_cases.TriggerScopedBatchInferenceUseCase().execute(
            top_n=10,
            pool_mode="price_covered",
        )
    assert released_batches

    monkeypatch.setattr(ops_use_cases, "resolve_qlib_data_refresh_lock", lambda key: None)
    monkeypatch.setattr(
        ops_use_cases,
        "acquire_qlib_data_refresh_pending_lock",
        lambda key, meta: True,
    )
    released_refreshes: list[str] = []
    monkeypatch.setattr(
        ops_use_cases,
        "release_qlib_data_refresh_lock",
        lambda key: released_refreshes.append(key),
    )
    monkeypatch.setattr(
        tasks.qlib_refresh_runtime_data_task,
        "delay",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("refresh queue offline")),
    )
    with pytest.raises(RuntimeError, match="refresh queue offline"):
        ops_use_cases.TriggerQlibUniverseRefreshUseCase().execute(
            target_date=TARGET_DATE,
            lookback_days=30,
            universes=[" CSI500 ", ""],
        )

    with pytest.raises(ValueError, match="portfolio_ids"):
        ops_use_cases.TriggerQlibScopedCodesRefreshUseCase().execute(
            target_date=TARGET_DATE,
            lookback_days=30,
            portfolio_ids=[],
            all_active_portfolios=False,
            pool_mode="price_covered",
        )
    monkeypatch.setattr(
        tasks.qlib_refresh_runtime_data_for_codes_task,
        "delay",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("codes queue offline")),
    )
    with pytest.raises(RuntimeError, match="codes queue offline"):
        ops_use_cases.TriggerQlibScopedCodesRefreshUseCase().execute(
            target_date=TARGET_DATE,
            lookback_days=30,
            portfolio_ids=[3, 1],
            all_active_portfolios=False,
            pool_mode="price_covered",
        )
    assert len(released_refreshes) == 2


def test_collect_portfolio_refs_filters_requested_ids_and_supports_all_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio collection preserves user scopes and does not invent missing records."""
    refs = [
        {"portfolio_id": 1, "user_id": 10},
        {"portfolio_id": 2, "user_id": 20},
    ]
    monkeypatch.setattr(
        ops_use_cases,
        "get_alpha_pool_data_repository",
        lambda: SimpleNamespace(list_active_portfolio_refs=lambda limit: refs),
    )
    assert ops_use_cases.collect_portfolio_refs_for_refresh(
        portfolio_ids=[2, 99],
        all_active_portfolios=False,
    ) == [refs[1]]
    assert (
        ops_use_cases.collect_portfolio_refs_for_refresh(
            portfolio_ids=[],
            all_active_portfolios=True,
        )
        == refs
    )
