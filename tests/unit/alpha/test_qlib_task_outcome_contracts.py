"""Normalized outcomes for Alpha Qlib tasks and exact alias delegation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.alpha.application import tasks
from apps.alpha.domain.entities import AlphaPoolScope

TRADE_DATE = date(2026, 7, 24)


def _scope(portfolio_id: int = 7) -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=TRADE_DATE,
        display_label="test scope",
        portfolio_id=portfolio_id,
        portfolio_name=f"portfolio-{portfolio_id}",
    )


def test_qlib_predict_scores_reports_stored_success(monkeypatch) -> None:
    """A persisted prediction publishes one requested, succeeded, and stored result."""
    active_model = SimpleNamespace(artifact_hash="model-hash")
    monkeypatch.setattr(tasks, "_get_runtime_qlib_config", lambda: {"enabled": True})
    monkeypatch.setattr(tasks, "_require_usable_qlib_runtime", lambda _config: None)
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: active_model),
    )
    monkeypatch.setattr(tasks, "_get_qlib_data_latest_date", lambda: TRADE_DATE)
    monkeypatch.setattr(
        tasks,
        "_execute_qlib_prediction",
        lambda **_kwargs: [{"code": "000001.SZ", "score": 0.8}],
    )
    monkeypatch.setattr(
        tasks,
        "_upsert_qlib_cache",
        lambda **_kwargs: (SimpleNamespace(), True),
    )
    monkeypatch.setattr(tasks, "sync_default_workspace_after_alpha_update", lambda *_args: {})

    result = tasks.qlib_predict_scores.run("csi300", TRADE_DATE.isoformat(), 10)

    assert result["outcome"] == "success"
    assert result["success"] is True
    assert (result["requested"], result["succeeded"], result["failed"], result["stored"]) == (
        1,
        1,
        0,
        1,
    )


def test_qlib_train_model_reports_registry_write(monkeypatch, tmp_path: Path) -> None:
    """Successful training reports its authoritative registry write."""
    registry_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(tasks, "_get_runtime_qlib_config", lambda: {"enabled": True})
    monkeypatch.setattr(tasks, "_require_usable_qlib_runtime", lambda _config: None)
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(
            create_model_entry=lambda **kwargs: registry_calls.append(kwargs),
            activate_model=lambda **_kwargs: None,
        ),
    )
    monkeypatch.setattr(
        tasks,
        "get_qlib_training_run_repository",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(tasks, "_train_qlib_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        tasks,
        "_evaluate_model_metrics",
        lambda *_args, **_kwargs: {"ic": 0.2, "icir": 1.1},
    )
    monkeypatch.setattr(tasks, "_calculate_artifact_hash", lambda _value: "a" * 64)
    monkeypatch.setattr(tasks, "_save_model_artifact", lambda **_kwargs: tmp_path)

    result = tasks.qlib_train_model.run(
        "model",
        "LGBModel",
        {"model_path": str(tmp_path), "activate": False},
    )

    assert result["outcome"] == "success"
    assert result["stored"] == 1
    assert len(registry_calls) == 1


def test_qlib_evaluate_model_normalizes_service_result(monkeypatch) -> None:
    """Model evaluation wraps the service payload in the common task contract."""
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        tasks,
        "evaluate_model_artifact",
        lambda **_kwargs: {"status": "success", "ic": 0.25},
    )

    result = tasks.qlib_evaluate_model.run("model-hash")

    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == result["stored"] == 1
    assert result["failed"] == 0


def test_qlib_refresh_cache_reports_success_noop_and_failure(monkeypatch) -> None:
    """Range scheduling distinguishes queued work, no work, and broker failure."""

    class Friday(date):
        @classmethod
        def today(cls) -> Friday:
            return cls(2026, 7, 24)

    class Saturday(date):
        @classmethod
        def today(cls) -> Saturday:
            return cls(2026, 7, 25)

    monkeypatch.setattr(tasks, "date", Friday)
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *_args, **_kwargs: SimpleNamespace(id="task-1"),
    )
    success = tasks.qlib_refresh_cache.run("csi300", days_back=0, top_n=10)
    assert success["outcome"] == "success"
    assert success["requested"] == success["succeeded"] == 1

    monkeypatch.setattr(tasks, "date", Saturday)
    noop = tasks.qlib_refresh_cache.run("csi300", days_back=0, top_n=10)
    assert noop["outcome"] == "noop"

    monkeypatch.setattr(tasks, "date", Friday)
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    failed = tasks.qlib_refresh_cache.run("csi300", days_back=0, top_n=10)
    assert failed["outcome"] == "failed"
    assert failed["success"] is False


def test_qlib_daily_inference_reports_partial_refresh_failure(monkeypatch) -> None:
    """A queued inference after refresh failure is partial rather than full success."""
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("refresh unavailable")),
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *_args, **_kwargs: SimpleNamespace(id="task-1"),
    )

    result = tasks.qlib_daily_inference.run(
        trade_date=TRADE_DATE.isoformat(),
        refresh_data=True,
    )

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert (result["requested"], result["succeeded"], result["failed"]) == (2, 1, 1)


def test_qlib_daily_scoped_inference_reports_blocked_and_success(monkeypatch) -> None:
    """Missing model blocks; one queued canonical scope is a completed request."""
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: None),
    )
    blocked = tasks.qlib_daily_scoped_inference.run(trade_date=TRADE_DATE.isoformat())
    assert blocked["outcome"] == "blocked"
    assert blocked["success"] is False

    scope = _scope()
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(
            get_active_model=lambda: SimpleNamespace(artifact_hash="model-hash")
        ),
    )
    monkeypatch.setattr(
        tasks,
        "get_alpha_score_cache_repository",
        lambda: SimpleNamespace(get_qlib_cache_for_trade_date=lambda **_kwargs: None),
    )
    monkeypatch.setattr(
        tasks,
        "get_alpha_pool_data_repository",
        lambda: SimpleNamespace(
            list_active_portfolio_refs=lambda **_kwargs: [{"portfolio_id": 7, "user_id": 8}]
        ),
    )

    class _Resolver:
        def resolve(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(scope=scope)

    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        _Resolver,
    )
    monkeypatch.setattr(
        tasks.qlib_predict_scores,
        "delay",
        lambda *_args, **_kwargs: SimpleNamespace(id="task-1"),
    )
    result = tasks.qlib_daily_scoped_inference.run(
        trade_date=TRADE_DATE.isoformat(),
        refresh_data=False,
    )
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == result["stored"] == 1


def test_qlib_refresh_runtime_data_task_normalizes_summary(monkeypatch) -> None:
    """Universe refresh maps service success/block/failure to task outcomes."""
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **_kwargs: {"status": "success", "universe_count": 2},
    )
    result = tasks.qlib_refresh_runtime_data_task.run(target_date=TRADE_DATE.isoformat())
    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == result["stored"] == 2

    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **_kwargs: {"status": "blocked", "reason": "runtime unavailable"},
    )
    blocked = tasks.qlib_refresh_runtime_data_task.run(target_date=TRADE_DATE.isoformat())
    assert blocked["outcome"] == "blocked"

    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("source unavailable")),
    )
    failed = tasks.qlib_refresh_runtime_data_task.run(target_date=TRADE_DATE.isoformat())
    assert failed["outcome"] == "failed"


def test_qlib_refresh_runtime_data_for_codes_reports_portfolio_counts(monkeypatch) -> None:
    """Scoped refresh reports its exact portfolio request and persisted code evidence."""
    scope = _scope()
    monkeypatch.setattr(
        tasks,
        "collect_portfolio_refs_for_refresh",
        lambda **_kwargs: [{"portfolio_id": 7, "user_id": 8}],
    )

    class _Resolver:
        def resolve(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                portfolio_id=7,
                portfolio_name="portfolio-7",
                scope=scope,
            )

    monkeypatch.setattr(
        "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
        _Resolver,
    )
    monkeypatch.setattr(
        tasks,
        "_refresh_qlib_runtime_data_for_codes",
        lambda **_kwargs: {"status": "success", "stock_count": 1},
    )

    result = tasks.qlib_refresh_runtime_data_for_codes_task.run(
        target_date=TRADE_DATE.isoformat(),
        portfolio_ids=[7],
    )

    assert result["outcome"] == "success"
    assert result["requested"] == result["succeeded"] == 1
    assert result["failed"] == 0
    assert result["stored"] == 1


@pytest.mark.parametrize(
    ("alias_name", "canonical_name", "kwargs"),
    [
        (
            "qlib_daily_inference_alias",
            "qlib_daily_inference",
            {
                "universe_id": "csi500",
                "top_n": 12,
                "refresh_data": False,
                "refresh_universes": ("csi500",),
                "lookback_days": 50,
                "trade_date": "2026-07-24",
            },
        ),
        (
            "qlib_daily_scoped_inference_alias",
            "qlib_daily_scoped_inference",
            {
                "top_n": 12,
                "portfolio_limit": 4,
                "pool_mode": "price_covered",
                "refresh_data": False,
                "lookback_days": 50,
                "trade_date": "2026-07-24",
                "only_missing": False,
            },
        ),
        (
            "qlib_refresh_cache_alias",
            "qlib_refresh_cache",
            {"universe_id": "csi500", "days_back": 3, "top_n": 12},
        ),
    ],
)
def test_qlib_legacy_aliases_delegate_exactly_once(
    monkeypatch,
    alias_name: str,
    canonical_name: str,
    kwargs: dict[str, Any],
) -> None:
    """Compatibility registrations delegate once and do not own outcome semantics."""
    calls: list[dict[str, Any]] = []
    sentinel = {"outcome": "sentinel"}
    monkeypatch.setattr(
        getattr(tasks, canonical_name),
        "run",
        lambda **actual: calls.append(actual) or sentinel,
    )

    result = getattr(tasks, alias_name).run(**kwargs)

    assert result is sentinel
    assert calls == [kwargs]
