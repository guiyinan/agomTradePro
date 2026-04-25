from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.alpha.application.tasks import (
    _reuse_latest_qlib_cache,
    qlib_daily_inference_alias,
    qlib_daily_scoped_inference_alias,
    qlib_refresh_cache_alias,
)
from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.models import AlphaScoreCacheModel


@pytest.mark.django_db
def test_reuse_latest_qlib_cache_uses_broader_cache_for_scoped_pool():
    AlphaScoreCacheModel._default_manager.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 18),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 4, 14),
        model_id="qlib-v1",
        model_artifact_hash="hash-1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260414",
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.3},
                "source": "qlib",
                "confidence": 0.88,
            },
            {
                "code": "600519.SH",
                "score": 0.89,
                "rank": 2,
                "factors": {"quality": 0.2},
                "source": "qlib",
                "confidence": 0.81,
            },
        ],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        metrics_snapshot={},
    )
    pool_scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ", "000002.SZ"),
        selection_reason="test",
        trade_date=date(2026, 4, 20),
        display_label="默认组合 · 价格覆盖池",
        portfolio_id=135,
        portfolio_name="默认组合",
    )
    active_model = SimpleNamespace(
        artifact_hash="hash-1",
        model_name="qlib-v1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260414",
    )

    result = _reuse_latest_qlib_cache(
        active_model=active_model,
        universe_id=pool_scope.universe_id,
        trade_date=date(2026, 4, 20),
        top_n=10,
        failure_reason="Qlib 预测未返回任何评分",
        pool_scope=pool_scope,
        extra_metadata={"requested_trade_date": "2026-04-20"},
    )

    assert result is not None
    assert result["status"] == "success"
    assert result["fallback_used"] is True
    assert result["scope_fallback_universe_id"] == "csi300"

    scoped_cache = AlphaScoreCacheModel._default_manager.get(scope_hash=pool_scope.scope_hash)
    assert scoped_cache.status == AlphaScoreCacheModel.STATUS_DEGRADED
    assert scoped_cache.universe_id == pool_scope.universe_id
    assert scoped_cache.metrics_snapshot["scope_fallback"] is True


def test_qlib_refresh_cache_alias_forwards_top_n_without_type_error():
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 4, 24)

    with (
        patch("apps.alpha.application.tasks.date", FixedDate),
        patch("apps.alpha.application.tasks.qlib_predict_scores.delay") as delay_mock,
    ):
        delay_mock.return_value = SimpleNamespace(id="task-1")

        result = qlib_refresh_cache_alias.run(
            universe_id="csi300",
            days_back=0,
            top_n=15,
        )

    assert result["status"] == "success"
    assert result["top_n"] == 15
    delay_mock.assert_called_once_with("csi300", "2026-04-24", 15)


def test_qlib_daily_inference_refreshes_data_before_queueing_prediction():
    with (
        patch("apps.alpha.application.tasks._refresh_qlib_runtime_data") as refresh_mock,
        patch("apps.alpha.application.tasks.qlib_predict_scores.delay") as delay_mock,
    ):
        refresh_mock.return_value = {"status": "success", "latest_local_date_after": "2026-04-24"}
        delay_mock.return_value = SimpleNamespace(id="task-1")

        result = qlib_daily_inference_alias.run(
            universe_id="csi300",
            top_n=20,
            refresh_data=True,
            refresh_universes="csi300,csi500",
            lookback_days=120,
        )

    assert result["status"] == "queued"
    assert result["refresh_result"]["status"] == "success"
    refresh_mock.assert_called_once()
    assert refresh_mock.call_args.kwargs["universes"] == "csi300,csi500"
    assert refresh_mock.call_args.kwargs["lookback_days"] == 120
    delay_mock.assert_called_once_with("csi300", date.today().isoformat(), 20)


def test_qlib_daily_scoped_inference_queues_active_portfolio_scopes():
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ", "600000.SH"),
        selection_reason="test",
        trade_date=date.today(),
        display_label="默认组合 · 价格覆盖池",
        portfolio_id=135,
        portfolio_name="默认组合",
    )

    with (
        patch(
            "apps.alpha.infrastructure.repositories.AlphaPoolDataRepository.list_active_portfolio_refs",
            return_value=[{"portfolio_id": 135, "user_id": 182, "name": "默认组合"}],
        ) as list_refs_mock,
        patch(
            "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver.resolve",
            return_value=SimpleNamespace(scope=scope),
        ) as resolve_mock,
        patch("apps.alpha.application.tasks.qlib_predict_scores.delay") as delay_mock,
    ):
        delay_mock.return_value = SimpleNamespace(id="task-1")

        result = qlib_daily_scoped_inference_alias.run(
            top_n=12,
            portfolio_limit=10,
            pool_mode="price_covered",
        )

    assert result["status"] == "queued"
    assert result["queued_count"] == 1
    assert result["queued"][0]["scope_hash"] == scope.scope_hash
    list_refs_mock.assert_called_once_with(limit=10)
    resolve_mock.assert_called_once()
    delay_mock.assert_called_once_with(
        scope.universe_id,
        date.today().isoformat(),
        12,
        scope_payload=scope.to_dict(),
    )
