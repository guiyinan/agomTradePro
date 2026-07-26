from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import pandas as pd

from apps.alpha.infrastructure.adapters import qlib_adapter
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider


def test_cached_scores_reject_future_asof_and_non_finite_values() -> None:
    provider = QlibAlphaProvider(provider_uri=".", model_path=".")
    intended_date = date(2026, 7, 24)

    scores = provider._parse_scores(
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
    monkeypatch.setattr(qlib_adapter.cache, "get", lambda key: None)
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
    monkeypatch.setattr(qlib_adapter.cache, "add", lambda *args, **kwargs: True)
    monkeypatch.setattr(qlib_adapter.cache, "delete", lambda key: None)

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
