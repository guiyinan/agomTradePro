from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.alpha.application.tasks import (
    _normalize_qlib_instrument_code,
    _normalize_qlib_instrument_list,
    qlib_predict_scores,
)
from apps.alpha.application.workspace_sync import sync_default_workspace_after_alpha_update
from apps.alpha.domain.entities import AlphaPoolScope


def test_qlib_stale_prediction_is_degraded_and_skips_workspace(monkeypatch):
    import apps.alpha.application.tasks as tasks

    monkeypatch.setattr(
        tasks,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "source": "test", "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: SimpleNamespace(artifact_hash="hash-1")),
    )
    monkeypatch.setattr(tasks, "_get_qlib_data_latest_date", lambda: date(2026, 9, 4))
    monkeypatch.setattr(
        tasks,
        "_maybe_refresh_qlib_runtime_data_for_prediction",
        lambda **kw: (date(2026, 9, 4), {"qlib_runtime_refresh_status": "failed"}),
    )
    monkeypatch.setattr(
        tasks, "_execute_qlib_prediction", lambda **kw: [{"code": "000001.SZ", "score": 0.5}]
    )
    upsert = Mock(return_value=(SimpleNamespace(), True))
    workspace = Mock()
    monkeypatch.setattr(tasks, "_upsert_qlib_cache", upsert)
    monkeypatch.setattr(tasks, "sync_default_workspace_after_alpha_update", workspace)
    result = tasks.qlib_predict_scores.run("csi300", "2026-09-08", 10)
    assert result["outcome"] == "partial"
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "qlib_source_data_stale"
    assert upsert.call_args.kwargs["status"] == "degraded"
    assert upsert.call_args.kwargs["asof_date"] == date(2026, 9, 4)
    workspace.assert_not_called()


@pytest.mark.parametrize(
    "error_code",
    [
        "TUSHARE_DAILY_QUOTA_EXHAUSTED",
        "MODEL_MARKET_STALE",
        "MODEL_MARKET_SOURCE_CONFLICT",
        "MODEL_MARKET_UNVERIFIED_FAILOVER",
        "MODEL_MARKET_CONFIG_UNAVAILABLE",
    ],
)
def test_qlib_quota_exhaustion_blocks_without_prediction_or_write(monkeypatch, error_code):
    import apps.alpha.application.tasks as tasks
    from core.exceptions import DataFetchError

    monkeypatch.setattr(tasks, "_get_runtime_qlib_config", lambda: {"enabled": True})
    monkeypatch.setattr(tasks, "_require_usable_qlib_runtime", lambda _: None)
    monkeypatch.setattr(
        tasks,
        "get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: SimpleNamespace(artifact_hash="hash-1")),
    )
    monkeypatch.setattr(tasks, "_get_qlib_data_latest_date", lambda: date(2026, 9, 4))
    refresh = Mock(side_effect=DataFetchError("source blocked", code=error_code))
    predict, upsert = Mock(), Mock()
    monkeypatch.setattr(tasks, "_refresh_qlib_runtime_data", refresh)
    monkeypatch.setattr(tasks, "_execute_qlib_prediction", predict)
    monkeypatch.setattr(tasks, "_upsert_qlib_cache", upsert)
    result = tasks.qlib_predict_scores.run("csi300", "2026-09-08", 10)
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == error_code.lower()
    assert result["stored"] == 0
    assert result["success"] is False
    predict.assert_not_called()
    upsert.assert_not_called()


def test_normalize_qlib_instrument_code_converts_ts_code_to_qlib_code():
    assert _normalize_qlib_instrument_code("000001.SZ") == "SZ000001"
    assert _normalize_qlib_instrument_code("600000.SH") == "SH600000"
    assert _normalize_qlib_instrument_code("sh600015") == "SH600015"


def test_normalize_qlib_instrument_list_deduplicates_and_preserves_order():
    assert _normalize_qlib_instrument_list(
        ["000001.SZ", "SZ000001", "600000.SH", "sh600000", ""]
    ) == [
        "SZ000001",
        "SH600000",
    ]


def test_qlib_predict_scores_refreshes_default_workspace_after_current_alpha_cache(
    monkeypatch,
):
    captured: dict[str, object] = {}
    active_model = SimpleNamespace(artifact_hash="hash-0")
    target_date = date(2026, 4, 29)

    def fake_predict(**kwargs):
        return [
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.8},
                "source": "qlib",
                "confidence": 0.87,
            }
        ]

    def fake_upsert(**kwargs):
        captured["cache_kwargs"] = kwargs
        return SimpleNamespace(), True

    def fake_refresh_workspace(dto):
        captured["workspace_refresh_dto"] = dto
        return SimpleNamespace(
            status="COMPLETED",
            task_id="refresh-alpha",
            recommendations_count=30,
            conflicts_count=0,
            message="ok",
        )

    monkeypatch.setattr(
        "apps.alpha.application.tasks.get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: active_model),
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_runtime_qlib_config",
        lambda: {"enabled": True, "source": "test", "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_qlib_data_latest_date",
        lambda: target_date,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._execute_qlib_prediction",
        fake_predict,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._upsert_qlib_cache",
        fake_upsert,
    )
    monkeypatch.setattr(
        "apps.alpha.application.workspace_sync._resolve_recent_closed_trade_date",
        lambda: target_date,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.workspace_services.refresh_workspace_recommendations",
        fake_refresh_workspace,
    )

    result = qlib_predict_scores.run("csi300", target_date.isoformat(), 10)

    dto = captured["workspace_refresh_dto"]
    assert result["status"] == "success"
    assert result["workspace_recommendations_status"] == "refreshed"
    assert result["workspace_recommendations_count"] == 30
    assert dto.account_id == "default"
    assert dto.force is True
    assert dto.async_mode is False


def test_workspace_refresh_failure_does_not_fail_alpha_cache_update(monkeypatch):
    target_date = date(2026, 4, 29)

    def fake_refresh_workspace(dto):
        raise RuntimeError("workspace unavailable")

    monkeypatch.setattr(
        "apps.alpha.application.workspace_sync._resolve_recent_closed_trade_date",
        lambda: target_date,
    )
    monkeypatch.setattr(
        "apps.decision_rhythm.application.workspace_services.refresh_workspace_recommendations",
        fake_refresh_workspace,
    )

    result = sync_default_workspace_after_alpha_update("csi300", target_date, None)

    assert result["workspace_recommendations_status"] == "failed"
    assert result["workspace_recommendations_error"] == "workspace unavailable"


def test_qlib_predict_scores_refreshes_general_runtime_data_before_prediction(monkeypatch):
    captured: dict[str, object] = {}
    active_model = SimpleNamespace(artifact_hash="hash-1")
    latest_dates = iter([date(2026, 4, 24), date(2026, 4, 29)])

    def fake_refresh(**kwargs):
        captured["refresh_kwargs"] = kwargs
        return {"status": "success"}

    def fake_predict(**kwargs):
        captured["prediction_kwargs"] = kwargs
        return [
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.8},
                "source": "qlib",
                "confidence": 0.87,
            }
        ]

    def fake_upsert(**kwargs):
        captured["cache_kwargs"] = kwargs
        return SimpleNamespace(), True

    monkeypatch.setattr(
        "apps.alpha.application.tasks.get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: active_model),
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_runtime_qlib_config",
        lambda: {"enabled": True, "source": "test", "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_qlib_data_latest_date",
        lambda: next(latest_dates),
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._refresh_qlib_runtime_data",
        fake_refresh,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._execute_qlib_prediction",
        fake_predict,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._upsert_qlib_cache",
        fake_upsert,
    )

    result = qlib_predict_scores.run("csi300", "2026-04-29", 10)

    assert result["status"] == "success"
    assert captured["refresh_kwargs"]["universes"] == ["csi300"]
    assert captured["prediction_kwargs"]["trade_date"] == date(2026, 4, 29)
    assert captured["cache_kwargs"]["asof_date"] == date(2026, 4, 29)
    assert result["qlib_runtime_refresh_status"] == "success"


def test_qlib_predict_scores_refreshes_scoped_runtime_data_before_prediction(monkeypatch):
    captured: dict[str, object] = {}
    active_model = SimpleNamespace(artifact_hash="hash-2")
    latest_dates = iter([date(2026, 4, 24), date(2026, 4, 29)])
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ", "600519.SH"),
        selection_reason="test",
        trade_date=date(2026, 4, 29),
        display_label="测试账户池",
        portfolio_id=9,
        portfolio_name="My Portfolio",
    )

    def fake_refresh(**kwargs):
        captured["refresh_kwargs"] = kwargs
        return {"status": "success"}

    def fake_predict(**kwargs):
        captured["prediction_kwargs"] = kwargs
        return [
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.8},
                "source": "qlib",
                "confidence": 0.87,
            }
        ]

    def fake_upsert(**kwargs):
        captured["cache_kwargs"] = kwargs
        return SimpleNamespace(), True

    monkeypatch.setattr(
        "apps.alpha.application.tasks.get_qlib_model_registry_repository",
        lambda: SimpleNamespace(get_active_model=lambda: active_model),
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_runtime_qlib_config",
        lambda: {"enabled": True, "source": "test", "provider_uri": "local-data"},
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._get_qlib_data_latest_date",
        lambda: next(latest_dates),
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._refresh_qlib_runtime_data_for_codes",
        fake_refresh,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._execute_qlib_prediction",
        fake_predict,
    )
    monkeypatch.setattr(
        "apps.alpha.application.tasks._upsert_qlib_cache",
        fake_upsert,
    )

    result = qlib_predict_scores.run(scope.universe_id, "2026-04-29", 10, scope.to_dict())

    assert result["status"] == "success"
    assert captured["refresh_kwargs"]["stock_codes"] == ["000001.SZ", "600519.SH"]
    assert captured["refresh_kwargs"]["universe_id"] == scope.universe_id
    assert captured["prediction_kwargs"]["pool_scope"].scope_hash == scope.scope_hash
    assert captured["cache_kwargs"]["pool_scope"].scope_hash == scope.scope_hash
    assert result["qlib_runtime_refresh_status"] == "success"
