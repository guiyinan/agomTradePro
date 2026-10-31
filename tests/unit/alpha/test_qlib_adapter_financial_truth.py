from __future__ import annotations

import logging
from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.adapters import qlib_adapter
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel


@pytest.fixture(params=["qlib", "cache"])
def score_parser(request: pytest.FixtureRequest) -> QlibAlphaProvider | CacheAlphaProvider:
    if request.param == "cache":
        return CacheAlphaProvider()
    return QlibAlphaProvider(provider_uri=".", model_path=".")


def test_cached_scores_reject_future_asof_and_non_finite_values(
    score_parser: QlibAlphaProvider | CacheAlphaProvider,
) -> None:
    intended_date = date(2026, 7, 24)

    scores = score_parser._parse_scores(
        [
            {
                "code": "600000.SH",
                "score": 0.8,
                "rank": 1,
                "factors": {},
                "confidence": 0.9,
                "asof_date": "2026-07-25",
            },
            {
                "code": "000001.SZ",
                "score": float("nan"),
                "rank": 2,
                "factors": {},
                "confidence": 0.9,
            },
            {
                "code": "000002.SZ",
                "score": 0.7,
                "rank": 3,
                "factors": {},
                "confidence": 0.9,
            },
        ],
        10,
        default_asof_date=intended_date,
        default_intended_trade_date=intended_date,
    )

    assert [score.code for score in scores] == ["000002.SZ"]


@pytest.mark.parametrize("explicit_source_date", [True, False])
def test_cached_scores_keep_old_source_date_when_plan_date_moves(
    score_parser: QlibAlphaProvider | CacheAlphaProvider,
    explicit_source_date: bool,
) -> None:
    payload: dict[str, object] = {
        "code": "600000.SH",
        "score": 0.7,
        "rank": 1,
        "factors": {},
        "confidence": 0.9,
    }
    if explicit_source_date:
        payload["asof_date"] = "2026-07-20"
        payload["intended_trade_date"] = "2026-07-20"

    scores = score_parser._parse_scores(
        [payload],
        10,
        default_asof_date=date(2026, 7, 20),
        default_intended_trade_date=date(2026, 7, 24),
    )

    assert len(scores) == 1
    assert scores[0].asof_date == date(2026, 7, 20)
    assert scores[0].intended_trade_date == date(2026, 7, 24)
    assert payload.get("asof_date") == ("2026-07-20" if explicit_source_date else None)


def _cache_row(scores: list[dict[str, object]]) -> AlphaScoreCacheModel:
    return AlphaScoreCacheModel(
        universe_id="csi300",
        asof_date=date(2026, 7, 24),
        intended_trade_date=date(2026, 7, 24),
        provider_source="qlib",
        model_artifact_hash="test-model",
        scores=scores,
        created_at=datetime(2026, 7, 24, tzinfo=UTC),
        metrics_snapshot={},
    )


def _score_row(asof: str | None = "2026-07-24") -> dict[str, object]:
    return {
        "code": "000001.SZ",
        "score": 0.8,
        "rank": 1,
        "confidence": 0.9,
        "factors": {},
        "asof_date": asof,
    }


def _stub_cache_query(
    monkeypatch: pytest.MonkeyPatch,
    exact: AlphaScoreCacheModel | None,
    broader: list[AlphaScoreCacheModel] | None = None,
) -> None:
    query = MagicMock()
    for method in ("filter", "exclude", "order_by"):
        getattr(query, method).return_value = query
    query.first.return_value = exact
    query.__getitem__.return_value = broader or []
    monkeypatch.setattr(AlphaScoreCacheModel._default_manager, "filter", lambda **kwargs: query)


@pytest.mark.parametrize("conflict_index", [1, 5000])
@pytest.mark.parametrize("source_date", ["2026-07-20", "2026-07-25", "invalid", ""])
def test_cache_read_checks_source_dates_before_score_limits(
    monkeypatch: pytest.MonkeyPatch,
    score_parser: QlibAlphaProvider | CacheAlphaProvider,
    conflict_index: int,
    source_date: str,
) -> None:
    rows = [_score_row() for _ in range(conflict_index)] + [_score_row(source_date)]
    original = deepcopy(rows)
    cache_row = _cache_row(rows)
    _stub_cache_query(monkeypatch, cache_row)
    if isinstance(score_parser, QlibAlphaProvider):
        monkeypatch.setattr(
            score_parser, "_get_active_model", lambda: {"artifact_hash": "test-model"}
        )

    result = score_parser.get_stock_scores("csi300", date(2026, 7, 24), top_n=1)

    assert result.success is False
    assert result.scores == []
    assert result.metadata["must_not_use_for_decision"] is True
    assert result.metadata["blocked_reason"] == (
        "alpha_cache_source_date_invalid"
        if source_date in {"invalid", ""}
        else "alpha_cache_source_date_conflict"
    )
    assert cache_row.scores == original


@pytest.mark.parametrize("fresh_broader", [False, True])
def test_broader_cache_checks_dates_before_scope_filter(
    monkeypatch: pytest.MonkeyPatch, fresh_broader: bool
) -> None:
    bad_row = _score_row("2026-07-20")
    bad_row["code"] = "600000.SH"
    corrupt = _cache_row([_score_row(), bad_row])
    valid = _cache_row([_score_row()])
    corrupt.metrics_snapshot = {"cache_identity": "corrupt"}
    valid.metrics_snapshot = {"cache_identity": "valid"}
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 7, 24),
    )
    _stub_cache_query(monkeypatch, None, [corrupt, valid] if fresh_broader else [corrupt])

    result = CacheAlphaProvider().get_stock_scores(
        scope.universe_id, scope.trade_date, top_n=1, pool_scope=scope
    )

    assert result.success is fresh_broader
    if fresh_broader:
        assert [score.code for score in result.scores] == ["000001.SZ"]
        assert result.metadata["scope_hash"] == scope.scope_hash
        assert result.metadata["cache_identity"] == "valid"
        assert result.metadata.get("must_not_use_for_decision") is not True
    else:
        assert result.scores == []
        assert result.metadata["blocked_reason"] == "alpha_cache_source_date_conflict"


@pytest.mark.parametrize("explicit_source_date", [True, False])
def test_cache_read_keeps_valid_forward_fill_source_date(
    monkeypatch: pytest.MonkeyPatch,
    score_parser: QlibAlphaProvider | CacheAlphaProvider,
    explicit_source_date: bool,
) -> None:
    payload = _score_row("2026-07-20" if explicit_source_date else None)
    payload["intended_trade_date"] = "2026-07-20"
    cache_row = _cache_row([payload])
    cache_row.asof_date = date(2026, 7, 20)
    cache_row.status = "degraded"
    cache_row.metrics_snapshot = {"fallback_mode": "forward_fill_latest_qlib_cache"}
    _stub_cache_query(monkeypatch, cache_row)
    if isinstance(score_parser, QlibAlphaProvider):
        monkeypatch.setattr(
            score_parser, "_get_active_model", lambda: {"artifact_hash": "test-model"}
        )

    result = score_parser.get_stock_scores("csi300", date(2026, 7, 24), top_n=1)

    assert result.success is True
    assert result.scores[0].asof_date == date(2026, 7, 20)
    assert result.scores[0].intended_trade_date == date(2026, 7, 24)
    assert result.metadata["asof_date"] == "2026-07-20"
    assert result.metadata["fallback_mode"] == "forward_fill_latest_qlib_cache"
    assert result.staleness_days is not None and result.staleness_days >= 4
    assert result.metadata.get("must_not_use_for_decision") is not True


def test_invalid_broader_cache_does_not_replace_valid_exact_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = _cache_row([_score_row("2026-07-20")])
    exact.asof_date = date(2026, 7, 20)
    exact.status = "degraded"
    exact.metrics_snapshot = {"fallback_mode": "forward_fill_latest_qlib_cache"}
    corrupt = _cache_row([_score_row("2026-07-25")])
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 7, 24),
    )
    _stub_cache_query(monkeypatch, exact, [corrupt])

    result = CacheAlphaProvider().get_stock_scores(
        scope.universe_id, scope.trade_date, top_n=1, pool_scope=scope
    )

    assert result.success is True
    assert result.status == "degraded"
    assert result.scores[0].asof_date == date(2026, 7, 20)
    assert result.staleness_days == 4
    assert result.metadata.get("must_not_use_for_decision") is not True


@pytest.mark.parametrize("header_case", ["unknown", "datetime", "future_source", "future_plan"])
def test_qlib_cache_read_requires_valid_header_date_chain(
    monkeypatch: pytest.MonkeyPatch,
    header_case: str,
) -> None:
    score_parser = QlibAlphaProvider(provider_uri=".", model_path=".")
    cache_row = _cache_row([_score_row(None)])
    if header_case == "unknown":
        cache_row.asof_date = None
    elif header_case == "datetime":
        cache_row.asof_date = datetime(2026, 7, 24, tzinfo=UTC)
    elif header_case == "future_source":
        cache_row.asof_date = date(2026, 7, 25)
    else:
        cache_row.intended_trade_date = date(2026, 7, 25)
    _stub_cache_query(monkeypatch, cache_row)
    monkeypatch.setattr(score_parser, "_get_active_model", lambda: {"artifact_hash": "test-model"})

    result = score_parser.get_stock_scores("csi300", date(2026, 7, 24), top_n=1)

    assert result.success is False
    assert result.scores == []
    assert result.metadata["must_not_use_for_decision"] is True
    assert result.metadata["blocked_reason"] == "alpha_cache_source_date_invalid"


def test_factor_exposure_drops_non_finite_values(monkeypatch) -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    frame = pd.DataFrame([[0.1, float("nan"), float("inf"), -0.2, 0.3]])
    data_api = SimpleNamespace(features=lambda **kwargs: frame)
    monkeypatch.setattr(
        qlib_adapter,
        "import_module",
        lambda name: SimpleNamespace(D=data_api),
    )

    result = provider.get_factor_exposure("600000.SH", date(2026, 7, 24))

    assert result == {
        "momentum_1d": 0.1,
        "volume_ratio": -0.2,
        "volatility_20d": 0.3,
    }


def test_inference_trigger_redacts_provider_error(
    monkeypatch,
    caplog,
) -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    captured_alerts: list[tuple[str, date, str]] = []
    monkeypatch.setattr(qlib_adapter, "cache", SimpleNamespace(get=lambda key: None))
    monkeypatch.setattr(provider, "_resolve_live_inference_queue", lambda: "qlib_infer")
    monkeypatch.setattr(
        provider,
        "_send_inference_failure_alert",
        lambda universe_id, intended_trade_date, error_type: captured_alerts.append(
            (universe_id, intended_trade_date, error_type)
        ),
    )

    from apps.alpha.application import tasks as alpha_tasks

    monkeypatch.setattr(
        alpha_tasks.qlib_predict_scores,
        "apply_async",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret=do-not-log")),
    )

    with caplog.at_level(logging.ERROR):
        result = provider._trigger_infer_task(
            "csi300",
            date(2026, 7, 24),
            10,
        )

    assert result == "failed"
    assert captured_alerts == [("csi300", date(2026, 7, 24), "RuntimeError")]
    assert "do-not-log" not in caplog.text


def test_inline_inference_failure_does_not_publish_task_payload(monkeypatch) -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    task_result = SimpleNamespace(
        get=lambda propagate: {"error": "secret=do-not-publish"},
        failed=lambda: True,
    )
    monkeypatch.setattr(
        qlib_adapter,
        "cache",
        SimpleNamespace(add=lambda *args, **kwargs: True, delete=lambda key: None),
    )

    from apps.alpha.application import tasks as alpha_tasks

    monkeypatch.setattr(
        alpha_tasks.qlib_predict_scores,
        "apply",
        lambda **kwargs: task_result,
    )

    result = provider._run_inline_infer_task(
        universe_id="csi300",
        intended_trade_date=date(2026, 7, 24),
        top_n=10,
    )

    assert result == {
        "status": "failed",
        "error_code": "inline_inference_failed",
    }
    assert "secret" not in str(result)


def test_invalid_request_does_not_enter_cache_or_task_chain(monkeypatch) -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(
        provider,
        "_get_from_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache called")),
    )

    invalid_universe = provider.get_stock_scores("../outside", date(2026, 7, 24))
    invalid_top_n = provider.get_stock_scores("csi300", date(2026, 7, 24), top_n=0)

    assert invalid_universe.status == "unavailable"
    assert invalid_top_n.status == "unavailable"


def test_provider_safety_decorators_redact_unhandled_error(
    monkeypatch,
    caplog,
) -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    monkeypatch.setattr(
        provider,
        "_get_from_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret=do-not-log")),
    )

    with caplog.at_level(logging.ERROR):
        result = provider.get_stock_scores("csi300", date(2026, 7, 24))

    assert result.status == "unavailable"
    assert "RuntimeError" in caplog.text
    assert "do-not-log" not in caplog.text
