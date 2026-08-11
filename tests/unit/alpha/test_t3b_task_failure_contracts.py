"""T3B Alpha task contracts for refresh, fallback, and scoped isolation."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from apps.alpha.application import tasks
from apps.alpha.domain.entities import AlphaPoolScope

TRADE_DATE = date(2026, 7, 24)


def _scope(
    *,
    portfolio_id: int,
    codes: tuple[str, ...] = ("000001.SZ",),
) -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=codes,
        selection_reason="T3B contract",
        trade_date=TRADE_DATE,
        display_label=f"portfolio-{portfolio_id}",
        portfolio_id=portfolio_id,
        portfolio_name=f"portfolio-{portfolio_id}",
    )


def test_runtime_refresh_helpers_reset_process_state_on_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refresh helpers always clear Qlib process markers, including failed refreshes."""
    reset_calls: list[str] = []

    class _RefreshService:
        def refresh_universes(self, **kwargs: object) -> dict[str, object]:
            assert kwargs["target_date"] == TRADE_DATE
            return {"status": "success", "mode": "universe"}

        def refresh_codes(self, **kwargs: object) -> dict[str, object]:
            assert kwargs["stock_codes"] == {"000001.SZ"}
            return {"status": "success", "mode": "codes"}

    monkeypatch.setattr(tasks, "QlibRuntimeDataRefreshService", _RefreshService)
    monkeypatch.setattr(tasks, "_reset_qlib_runtime_state", lambda: reset_calls.append("reset"))

    assert (
        tasks._refresh_qlib_runtime_data(
            target_date=TRADE_DATE,
            universes="csi300",
        )["mode"]
        == "universe"
    )
    assert (
        tasks._refresh_qlib_runtime_data_for_codes(
            target_date=TRADE_DATE,
            stock_codes={"000001.SZ"},
        )["mode"]
        == "codes"
    )

    monkeypatch.setattr(
        _RefreshService,
        "refresh_codes",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("provider offline")),
    )
    with pytest.raises(RuntimeError, match="provider offline"):
        tasks._refresh_qlib_runtime_data_for_codes(
            target_date=TRADE_DATE,
            stock_codes={"000001.SZ"},
        )
    assert reset_calls == ["reset", "reset", "reset"]


def test_inline_refresh_reports_up_to_date_scoped_and_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inline refresh preserves old dates and exposes refresh/post-check failures."""
    latest, metadata = tasks._maybe_refresh_qlib_runtime_data_for_prediction(
        trade_date=TRADE_DATE,
        universe_id="csi300",
        latest_qlib_data_date=TRADE_DATE,
    )
    assert latest == TRADE_DATE
    assert metadata == {
        "qlib_data_latest_date_before_refresh": TRADE_DATE.isoformat(),
        "qlib_runtime_refresh_status": "skipped",
        "qlib_runtime_refresh_reason": "already_up_to_date",
    }

    scope = _scope(portfolio_id=7)
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data_for_codes",
        lambda **kwargs: {"status": "success", "stored": 1},
    )
    monkeypatch.setattr(tasks, "_get_qlib_data_latest_date", lambda: TRADE_DATE)
    latest, metadata = tasks._maybe_refresh_qlib_runtime_data_for_prediction(
        trade_date=TRADE_DATE,
        universe_id="fallback",
        pool_scope=scope,
        latest_qlib_data_date=None,
    )
    assert latest == TRADE_DATE
    assert metadata["qlib_runtime_refresh_status"] == "success"
    assert metadata["qlib_data_latest_date_after_refresh"] == TRADE_DATE.isoformat()

    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data_for_codes",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("refresh timeout")),
    )
    latest, metadata = tasks._maybe_refresh_qlib_runtime_data_for_prediction(
        trade_date=TRADE_DATE,
        universe_id="csi300",
        pool_scope=scope,
        latest_qlib_data_date=None,
    )
    assert latest is None
    assert metadata["qlib_runtime_refresh_status"] == "failed"
    assert metadata["qlib_runtime_refresh_error"] == "refresh timeout"

    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **kwargs: {"status": "partial", "stored": 0},
    )
    monkeypatch.setattr(
        tasks,
        "_get_qlib_data_latest_date",
        lambda: (_ for _ in ()).throw(OSError("calendar unreadable")),
    )
    latest, metadata = tasks._maybe_refresh_qlib_runtime_data_for_prediction(
        trade_date=TRADE_DATE,
        universe_id="csi300",
        latest_qlib_data_date=None,
    )
    assert latest is None
    assert metadata["qlib_runtime_refresh_status"] == "partial"
    assert metadata["qlib_runtime_refresh_post_check_error"] == "calendar unreadable"


@pytest.mark.parametrize(
    ("failure_mode", "expected_status"),
    [
        ("data_state", "fallback-data"),
        ("prediction", "fallback-prediction"),
        ("empty", "fallback-empty"),
    ],
)
def test_prediction_task_uses_auditable_cache_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_status: str,
) -> None:
    """Runtime, prediction, and empty-output failures reuse cache with explicit evidence."""
    active_model = SimpleNamespace(artifact_hash="model-hash")
    monkeypatch.setattr(
        tasks,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "source": "test", "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: active_model),
    )
    monkeypatch.setattr(
        tasks,
        "_build_qlib_runtime_failure_reason",
        lambda exc: f"runtime: {exc}",
    )
    monkeypatch.setattr(
        tasks,
        "_maybe_refresh_qlib_runtime_data_for_prediction",
        lambda **kwargs: (TRADE_DATE, {}),
    )
    monkeypatch.setattr(
        tasks,
        "resolve_effective_trade_date",
        lambda *args, **kwargs: (TRADE_DATE, {"date_resolution": "exact"}),
    )

    if failure_mode == "data_state":
        monkeypatch.setattr(
            tasks,
            "_get_qlib_data_latest_date",
            lambda: (_ for _ in ()).throw(OSError("metadata unavailable")),
        )
    else:
        monkeypatch.setattr(tasks, "_get_qlib_data_latest_date", lambda: TRADE_DATE)

    if failure_mode == "prediction":
        monkeypatch.setattr(
            tasks,
            "_execute_qlib_prediction",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("model crashed")),
        )
    elif failure_mode == "empty":
        monkeypatch.setattr(tasks, "_execute_qlib_prediction", lambda **kwargs: [])

    fallback = {
        "data_state": {"status": "fallback-data"},
        "prediction": {"status": "fallback-prediction"},
        "empty": {"status": "fallback-empty"},
    }
    failure_reasons: list[str] = []

    def _reuse(**kwargs: object) -> dict[str, str]:
        failure_reasons.append(str(kwargs["failure_reason"]))
        return fallback[failure_mode]

    monkeypatch.setattr(tasks, "_reuse_latest_qlib_cache", _reuse)

    result = tasks.qlib_predict_scores.run(
        universe_id="csi300",
        intended_trade_date=TRADE_DATE.isoformat(),
        top_n=10,
    )

    assert result["status"] == expected_status
    assert failure_reasons


def test_prediction_task_blocks_before_legacy_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing typed snapshot must stop inference before model/data access."""
    calls: list[str] = []
    monkeypatch.setattr(
        tasks,
        "_get_runtime_qlib_config",
        lambda: {
            "enabled": False,
            "status": "blocked",
            "source": "config_center_runtime_profile",
            "must_not_use_for_decision": True,
            "blocked_reason": "runtime_config_snapshot_unavailable",
        },
    )
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: calls.append("model") or SimpleNamespace(get_active_model=lambda: None),
    )
    monkeypatch.setattr(
        tasks,
        "_get_qlib_data_latest_date",
        lambda: calls.append("calendar") or TRADE_DATE,
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "retry",
        lambda **kwargs: RuntimeError(str(kwargs["exc"])),
    )

    with pytest.raises(RuntimeError, match="runtime_config_snapshot_unavailable"):
        tasks.qlib_predict_scores.run(
            universe_id="csi300",
            intended_trade_date=TRADE_DATE.isoformat(),
            top_n=10,
        )

    assert calls == []


def test_daily_inference_and_cache_refresh_keep_failure_results_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daily scheduling continues after refresh failure; range refresh serializes queue failure."""
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("source timeout")),
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *args, **kwargs: SimpleNamespace(id="predict-1"),
    )
    result = tasks.qlib_daily_inference.run(
        trade_date=TRADE_DATE.isoformat(),
        refresh_data=True,
    )
    assert result["status"] == "queued"
    assert result["refresh_result"] == {
        "status": "failed",
        "error": "source timeout",
    }

    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    refreshed = tasks.qlib_refresh_cache.run("csi300", days_back=7, top_n=10)
    assert refreshed["status"] == "error"
    assert refreshed["error"] == "broker down"
    assert refreshed["outcome"] == "failed"
    assert refreshed["success"] is False


def test_scoped_inference_isolates_empty_duplicate_resolution_refresh_and_queue_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bad portfolio cannot hide or abort other scoped inference outcomes."""
    scope = _scope(portfolio_id=2)
    refs = [
        {"portfolio_id": 1, "user_id": 10},
        {"portfolio_id": 2, "user_id": 20},
        {"portfolio_id": 3, "user_id": 30},
        {"portfolio_id": 4, "user_id": 40},
    ]

    class _Resolver:
        def resolve(self, **kwargs: object) -> SimpleNamespace:
            portfolio_id = int(kwargs["portfolio_id"])
            if portfolio_id == 1:
                return SimpleNamespace(scope=_scope(portfolio_id=1, codes=()))
            if portfolio_id == 4:
                raise LookupError("portfolio unavailable")
            return SimpleNamespace(scope=scope)

    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(
            get_active_model=lambda: SimpleNamespace(artifact_hash="model-hash")
        ),
    )
    monkeypatch.setattr(
        tasks,
        "get_alpha_pool_data_repository",
        lambda: SimpleNamespace(list_active_portfolio_refs=lambda limit: refs),
    )
    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        _Resolver,
    )
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data_for_codes",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("refresh failed")),
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("queue failed")),
    )

    result = tasks.qlib_daily_scoped_inference.run(
        trade_date=TRADE_DATE.isoformat(),
        refresh_data=True,
        only_missing=False,
    )

    assert result["status"] == "skipped"
    assert result["queued_count"] == 0
    assert result["refresh_result"]["status"] == "failed"
    assert {item["reason"] for item in result["skipped"]} == {
        "empty_scope",
        "duplicate_scope",
        "portfolio unavailable",
        "queue failed",
    }


def test_scoped_inference_skips_without_active_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing model is a business skip and performs no portfolio reads."""
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: None),
    )
    monkeypatch.setattr(
        tasks,
        "get_alpha_pool_data_repository",
        lambda: pytest.fail("portfolio repository must not be read"),
    )
    result = tasks.qlib_daily_scoped_inference.run(
        trade_date=TRADE_DATE.isoformat(),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "no_active_model"
    assert result["trade_date"] == TRADE_DATE.isoformat()
    assert result["outcome"] == "blocked"
    assert result["success"] is False


def test_portfolio_runtime_refresh_reports_empty_failed_missing_and_successful_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit portfolio refresh returns per-portfolio evidence and deduplicated codes."""
    refs = [
        {"portfolio_id": 1, "user_id": 10},
        {"portfolio_id": 2, "user_id": 20},
        {"portfolio_id": 3, "user_id": 30},
    ]

    class _Resolver:
        def resolve(self, **kwargs: object) -> SimpleNamespace:
            portfolio_id = int(kwargs["portfolio_id"])
            if portfolio_id == 1:
                scope = _scope(portfolio_id=1, codes=())
            elif portfolio_id == 2:
                raise PermissionError("cross-user scope rejected")
            else:
                scope = _scope(
                    portfolio_id=3,
                    codes=("000001.SZ", "000001.SZ", "600000.SH"),
                )
            return SimpleNamespace(
                portfolio_id=portfolio_id,
                portfolio_name=f"portfolio-{portfolio_id}",
                scope=scope,
            )

    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        _Resolver,
    )
    monkeypatch.setattr(
        tasks,
        "collect_portfolio_refs_for_refresh",
        lambda **kwargs: refs,
    )
    captured: dict[str, object] = {}

    def _refresh(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "success", "stored": 2}

    monkeypatch.setattr(tasks, "_refresh_qlib_runtime_data_for_codes", _refresh)

    result = tasks.qlib_refresh_runtime_data_for_codes_task.run(
        target_date=TRADE_DATE.isoformat(),
        portfolio_ids=[1, 2, 3, 99],
        all_active_portfolios=False,
    )

    assert captured["stock_codes"] == {"000001.SZ", "600000.SH"}
    assert result["status"] == "success"
    assert result["portfolio_count"] == 1
    assert len(result["summary"]["skipped"]) == 3
    assert {item["reason"] for item in result["summary"]["skipped"]} == {
        "empty_scope",
        "cross-user scope rejected",
        "portfolio_not_active_or_not_found",
    }
