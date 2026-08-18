"""Deterministic infrastructure-edge tests for Alpha fallbacks and artifacts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from django.conf import settings

from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult, StockScore
from apps.alpha.infrastructure.adapters.qlib_adapter import (
    QlibAlphaProvider,
    _normalize_calendar_date,
)
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.qlib_artifact_runtime import (
    _calculate_artifact_hash,
    _save_model_artifact,
)
from shared.infrastructure.model_evaluation import ModelMetrics


def _scope(size: int = 2) -> AlphaPoolScope:
    return AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="strict",
        instrument_codes=tuple(f"{index:06d}.SZ" for index in range(1, size + 1)),
        selection_reason="contract",
        trade_date=date(2026, 7, 24),
    )


def test_qlib_calendar_normalization_and_artifact_round_trip(tmp_path) -> None:
    """Calendar inputs normalize and artifacts persist reproducible metadata."""
    assert _normalize_calendar_date(None) is None
    assert _normalize_calendar_date(date(2026, 7, 24)) == date(2026, 7, 24)
    assert _normalize_calendar_date(pd.Timestamp("2026-07-23")) == date(2026, 7, 23)
    assert _normalize_calendar_date("bad-date") is None

    source = tmp_path / "source.bin"
    source.write_bytes(b"stable-model")
    assert _calculate_artifact_hash(str(source)) == _calculate_artifact_hash(str(source))
    assert _calculate_artifact_hash("not-yet-written") != ""

    artifact = _save_model_artifact(
        model={"weight": 1.0},
        model_name="contract-model",
        artifact_hash="abc123",
        model_path=str(tmp_path),
        train_config={
            "end_date": "2026-07-23",
            "feature_set_id": "alpha158",
            "label_id": "return_5d",
        },
        metrics={"ic": 0.12},
    )
    assert (artifact / "model.pkl").exists()
    assert '"ic": 0.12' in (artifact / "metrics.json").read_text(encoding="utf-8")
    assert (artifact / "data_version.txt").read_text(encoding="utf-8").strip() == "2026-07-23"
    schema = json.loads((artifact / "feature_schema.json").read_text(encoding="utf-8"))
    assert schema == {"feature_set_id": "alpha158", "label_id": "return_5d"}
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["model.pkl"]["sha256"] == _calculate_artifact_hash(
        str(artifact / "model.pkl")
    )

    with pytest.raises(FileExistsError, match="禁止覆盖"):
        _save_model_artifact(
            model={"weight": 2.0},
            model_name="contract-model",
            artifact_hash="abc123",
            model_path=str(tmp_path),
            train_config={"end_date": "2026-07-24"},
            metrics={"ic": 0.20},
        )


def test_qlib_provider_cache_miss_statuses_and_inline_boundaries(monkeypatch) -> None:
    """Cache misses expose queue/inline outcomes without hiding degradation."""
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(settings, "ALPHA_ALLOW_INLINE_INFERENCE", True, raising=False)
    trade_date = date(2026, 7, 24)
    monkeypatch.setattr(provider, "_get_from_cache", lambda *args, **kwargs: None)

    for trigger, expected_error in (
        ("queued", "已触发"),
        ("failed", "投递失败"),
    ):
        monkeypatch.setattr(
            provider, "_trigger_infer_task", lambda *args, value=trigger, **kwargs: value
        )
        result = provider.get_stock_scores("csi300", trade_date)
        assert result.status == "degraded"
        assert expected_error in (result.error_message or "")

    small_scope = _scope()
    monkeypatch.setattr(provider, "_trigger_infer_task", lambda *args, **kwargs: "no_worker")
    monkeypatch.setattr(
        provider,
        "_run_inline_infer_task",
        lambda **kwargs: {"status": "completed", "result": {"count": 0}},
    )
    result = provider.get_stock_scores("csi300", trade_date, pool_scope=small_scope)
    assert result.metadata["inline_inference_executed"] is True
    assert provider._can_run_inline_inference(small_scope) is True
    assert provider._can_run_inline_inference(None) is False
    assert provider._build_inline_skip_metadata(None)["reason"].endswith("scoped_pool")
    assert provider._build_inline_skip_metadata(_scope(121))["pool_size"] == 121


def test_qlib_inline_inference_is_disabled_when_not_explicitly_allowed(monkeypatch) -> None:
    """A missing worker must not run model inference inside a web request by default."""

    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(settings, "ALPHA_ALLOW_INLINE_INFERENCE", False, raising=False)
    monkeypatch.setattr(provider, "_get_from_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(provider, "_trigger_infer_task", lambda *args, **kwargs: "no_worker")
    inline = False

    def fail_if_called(**kwargs):
        nonlocal inline
        inline = True
        raise AssertionError("inline inference must remain disabled")

    monkeypatch.setattr(provider, "_run_inline_infer_task", fail_if_called)
    result = provider.get_stock_scores("csi300", date(2026, 7, 24), pool_scope=_scope())

    assert result.status == "degraded"
    assert result.metadata["inline_inference_executed"] is False
    assert inline is False


def test_qlib_provider_returns_inline_cache_and_parses_only_valid_scores(monkeypatch) -> None:
    """Inline inference rechecks cache and malformed cached rows are ignored."""
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(settings, "ALPHA_ALLOW_INLINE_INFERENCE", True, raising=False)
    trade_date = date(2026, 7, 24)
    cached = AlphaResult(
        success=True,
        scores=[],
        source="qlib",
        timestamp=trade_date.isoformat(),
        status="available",
    )
    responses = iter((None, cached))
    monkeypatch.setattr(provider, "_get_from_cache", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(provider, "_trigger_infer_task", lambda *args, **kwargs: "no_worker")
    monkeypatch.setattr(
        provider,
        "_run_inline_infer_task",
        lambda **kwargs: {"status": "completed", "result": {"count": 2}},
    )
    result = provider.get_stock_scores("csi300", trade_date, pool_scope=_scope())
    assert result.success is True
    assert result.metadata["inline_inference_executed"] is True
    assert result.staleness_days == 0

    parsed = provider._parse_scores(
        [
            {"code": "000001", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.9},
            {"score": "invalid"},
        ],
        10,
        default_asof_date=trade_date,
        default_intended_trade_date=trade_date + timedelta(days=1),
    )
    assert [item.code for item in parsed] == ["000001.SZ"]
    assert parsed[0].intended_trade_date == trade_date + timedelta(days=1)


def test_simple_provider_scores_fundamentals_and_falls_back_to_quotes(monkeypatch) -> None:
    """Simple Alpha ranks fundamentals and prefers quote fallback when coverage is low."""
    provider = SimpleAlphaProvider()
    trade_date = date(2026, 7, 24)
    stocks = ["000001.SZ", "000002.SZ", "000003.SZ"]
    monkeypatch.setattr(provider, "_get_universe_stocks", lambda *args, **kwargs: stocks)

    fundamentals = {
        code: {
            "pe": 10.0 + index,
            "pb": 1.0 + index,
            "roe": 0.2 - index * 0.02,
            "dividend_yield": 0.03,
            "_data_quality": {
                "has_pe": True,
                "has_pb": True,
                "has_roe": index != 2,
                "has_dividend": True,
            },
        }
        for index, code in enumerate(stocks)
    }
    quality = {
        "valuation_count": 3,
        "financial_count": 2,
        "complete_count": 2,
        "partial_count": 1,
        "missing_count": 0,
        "error": None,
    }
    monkeypatch.setattr(provider, "_get_fundamental_data", lambda *args: (fundamentals, quality))
    result = provider.get_stock_scores("csi300", trade_date, top_n=2)
    assert result.success is True
    assert [score.rank for score in result.scores] == [1, 2]
    assert result.scores[0].score >= result.scores[1].score
    assert provider.get_factor_exposure("missing", trade_date) == {}

    quote_score = StockScore(
        code="000001.SZ",
        score=0.7,
        rank=1,
        factors={"momentum": 0.7},
        source="simple",
        confidence=0.8,
        asof_date=trade_date,
    )
    monkeypatch.setattr(provider, "_get_fundamental_data", lambda *args: ({}, quality))
    monkeypatch.setattr(
        provider,
        "_compute_quote_momentum_scores",
        lambda **kwargs: ([quote_score], {"quote_count": 1}, 0),
    )
    fallback = provider.get_stock_scores("csi300", trade_date, top_n=1)
    assert fallback.success is True
    assert fallback.metadata["factor_basis"] == "quote_momentum"


def test_simple_provider_bounds_large_request_pool(monkeypatch) -> None:
    """Broad web requests must degrade instead of running an N+1 fundamental scan."""

    provider = SimpleAlphaProvider()
    monkeypatch.setattr(settings, "ALPHA_SIMPLE_MAX_POOL_SIZE", 2, raising=False)
    monkeypatch.setattr(
        provider,
        "_get_universe_stocks",
        lambda *args, **kwargs: ["000001.SZ", "000002.SZ", "000003.SZ"],
    )
    calls = 0

    def unexpected_fundamental_scan(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("large request must not start a fundamental scan")

    monkeypatch.setattr(provider, "_get_fundamental_data", unexpected_fundamental_scan)
    result = provider.get_stock_scores("portfolio-test", date(2026, 7, 24))

    assert result.status == "degraded"
    assert "请求上限" in (result.error_message or "")
    assert calls == 0


def test_simple_provider_reports_empty_universe_and_unusable_data(monkeypatch) -> None:
    """Simple Alpha returns auditable failures for missing source data."""
    provider = SimpleAlphaProvider()
    trade_date = date(2026, 7, 24)
    monkeypatch.setattr(provider, "_get_universe_stocks", lambda *args, **kwargs: [])
    assert provider.get_stock_scores("missing", trade_date).success is False

    monkeypatch.setattr(provider, "_get_universe_stocks", lambda *args, **kwargs: ["000001.SZ"])
    quality = {
        "valuation_count": 0,
        "financial_count": 0,
        "complete_count": 0,
        "partial_count": 0,
        "missing_count": 1,
        "error": "no source",
    }
    monkeypatch.setattr(provider, "_get_fundamental_data", lambda *args: ({}, quality))
    monkeypatch.setattr(provider, "_compute_quote_momentum_scores", lambda **kwargs: ([], {}, None))
    failed = provider.get_stock_scores("missing", trade_date)
    assert failed.success is False
    assert "no source" in (failed.error_message or "")
    assert SimpleAlphaProvider._normalize_factor_values([]) == []
    assert SimpleAlphaProvider._normalize_factor_values([2.0, 2.0]) == [0.5, 0.5]


class _CacheQuery(list[SimpleNamespace]):
    def exists(self) -> bool:
        return bool(self)

    def order_by(self, *args: str) -> _CacheQuery:
        return self


class _CacheManager:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = _CacheQuery(rows)

    def filter(self, **kwargs: object) -> _CacheQuery:
        return self.rows


def test_cache_evaluation_handles_empty_partial_and_valid_predictions(monkeypatch) -> None:
    """Cache evaluation ignores invalid rows and forwards aligned real returns."""
    from apps.alpha.infrastructure import cache_evaluation

    monkeypatch.setattr(
        cache_evaluation.AlphaScoreCacheModel,
        "objects",
        _CacheManager([]),
    )
    empty = cache_evaluation.evaluate_model_from_cache(
        "hash",
        "csi300",
        date(2026, 7, 1),
        date(2026, 7, 24),
    )
    assert empty == ModelMetrics()

    row = SimpleNamespace(
        intended_trade_date=date(2026, 7, 20),
        scores=[
            {"code": "000001.SZ", "score": 0.8},
            {"code": "", "score": 0.7},
            {"code": "000002.SZ"},
        ],
    )
    monkeypatch.setattr(
        cache_evaluation.AlphaScoreCacheModel,
        "objects",
        _CacheManager([row]),
    )
    monkeypatch.setattr(
        cache_evaluation,
        "_get_actual_returns",
        lambda codes, trade_date: {"000001.SZ": 0.03},
    )
    expected = ModelMetrics(ic=0.25, coverage=1.0)
    captured: dict[str, dict[str, float]] = {}

    def _evaluate(**kwargs: dict[str, float]) -> ModelMetrics:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(
        cache_evaluation.ModelEvaluator,
        "evaluate_predictions",
        lambda self, **kwargs: _evaluate(**kwargs),
    )
    result = cache_evaluation.evaluate_model_from_cache(
        "hash",
        "csi300",
        date(2026, 7, 1),
        date(2026, 7, 24),
    )
    assert result == expected
    assert captured["predictions"] == {"000001.SZ": 0.8}

    monkeypatch.setattr(cache_evaluation, "_get_actual_returns", lambda *args: {})
    assert (
        cache_evaluation.evaluate_model_from_cache(
            "hash",
            "csi300",
            date(2026, 7, 1),
            date(2026, 7, 24),
        )
        == ModelMetrics()
    )


def test_cache_rolling_metrics_enforces_window_and_builds_history(monkeypatch) -> None:
    """Rolling metrics require enough dates and align scores with realized returns."""
    from apps.alpha.infrastructure import cache_evaluation

    rows = [
        SimpleNamespace(
            intended_trade_date=date(2026, 7, day),
            scores=[{"code": f"00000{index}.SZ", "score": float(index)} for index in range(1, 6)],
        )
        for day in range(1, 7)
    ]
    monkeypatch.setattr(
        cache_evaluation.AlphaScoreCacheModel,
        "objects",
        _CacheManager(rows),
    )
    monkeypatch.setattr(
        cache_evaluation,
        "_get_actual_returns",
        lambda codes, trade_date: {
            code: index / 100 for index, code in enumerate(sorted(codes), start=1)
        },
    )
    monkeypatch.setattr(
        cache_evaluation.IC_Calculator,
        "calculate_ic",
        lambda self, predictions, targets: 0.4,
    )
    too_short = cache_evaluation.calculate_rolling_metrics(
        "hash",
        "csi300",
        date(2026, 7, 1),
        date(2026, 7, 24),
        window=10,
    )
    assert too_short == []

    metrics = cache_evaluation.calculate_rolling_metrics(
        "hash",
        "csi300",
        date(2026, 7, 1),
        date(2026, 7, 24),
        window=2,
    )
    assert len(metrics) == 5
    assert all(metric.ic == 0.4 for metric in metrics)
    assert metrics[-1].ic_ma_5 == 0.4
