"""A hard refresh block must not fan out doomed prediction tasks."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.alpha.application.daily_inference_orchestration import (
    run_daily_inference,
    run_scoped_inference,
)
from apps.alpha.domain.entities import AlphaPoolScope
from core.exceptions import ConfigurationError, DataFetchError


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        DataFetchError("quota", code="TUSHARE_DAILY_QUOTA_EXHAUSTED"),
        DataFetchError("conflict", code="MODEL_MARKET_SOURCE_CONFLICT"),
        ConfigurationError("config", code="MODEL_MARKET_CONFIG_UNAVAILABLE"),
        {"status": "blocked", "reason": "runtime_unavailable"},
    ],
)
def test_daily_refresh_block_does_not_queue_predictions(monkeypatch, scoped, failure):
    refresh = Mock()
    if isinstance(failure, Exception):
        refresh.side_effect = failure
        reason = failure.code.lower()
    else:
        refresh.return_value = failure
        reason = failure["reason"]
    queue = Mock(return_value=SimpleNamespace(id="should-not-be-queued"))
    common = {
        "top_n": 30,
        "refresh_data": True,
        "lookback_days": 120,
        "trade_date": "2026-09-18",
        "resolve_trade_date": lambda: date(2026, 9, 18),
        "queue_prediction": queue,
    }
    if scoped:
        scope = AlphaPoolScope(
            pool_type="portfolio_market",
            market="CN",
            pool_mode="price_covered",
            selection_reason="test",
            trade_date=date(2026, 9, 18),
            portfolio_id=1,
            instrument_codes=("000001.SZ",),
        )
        monkeypatch.setattr(
            "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
            lambda: SimpleNamespace(resolve=lambda **kw: SimpleNamespace(scope=scope)),
        )
        result = run_scoped_inference(
            **common,
            portfolio_limit=0,
            pool_mode="price_covered",
            only_missing=False,
            get_active_model=lambda: SimpleNamespace(artifact_hash="model"),
            get_score_cache_repository=lambda: Mock(),
            get_pool_repository=lambda: SimpleNamespace(
                list_active_portfolio_refs=lambda **kw: [{"portfolio_id": 1, "user_id": 1}]
            ),
            cache_is_fresh=lambda *_: False,
            refresh_runtime_for_codes=refresh,
        )
        assert result["queued_count"] == 0
        assert result["queued"] == []
    else:
        result = run_daily_inference(
            **common,
            universe_id="csi300",
            refresh_universes=None,
            refresh_runtime_data=refresh,
        )
    assert result["status"] == result["outcome"] == "blocked"
    assert result["blocked_reason"] == reason
    assert result["must_not_use_for_decision"] is True
    assert result["success"] is False
    assert result["stored"] == 0
    assert result["succeeded"] == 0
    refresh.assert_called_once()
    queue.assert_not_called()
