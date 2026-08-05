from datetime import date
from types import SimpleNamespace

from apps.alpha.application.tasks import (
    _normalize_qlib_instrument_code,
    _normalize_qlib_instrument_list,
    qlib_predict_scores,
)
from apps.alpha.application.workspace_sync import sync_default_workspace_after_alpha_update
from apps.alpha.domain.entities import AlphaPoolScope


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
        lambda: {"enabled": True, "source": "test"},
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
        lambda: {"enabled": True, "source": "test"},
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
        lambda: {"enabled": True, "source": "test"},
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
