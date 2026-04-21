from datetime import date

import pytest

from apps.alpha.domain.entities import AlphaPoolScope
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel


@pytest.mark.django_db
def test_cache_provider_reuses_broader_qlib_cache_for_scoped_pool():
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
        pool_mode="strict_valuation",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 4, 20),
        display_label="默认组合 · 严格估值覆盖池",
        portfolio_id=135,
        portfolio_name="默认组合",
    )

    result = CacheAlphaProvider().get_stock_scores(
        universe_id=pool_scope.universe_id,
        intended_trade_date=date(2026, 4, 20),
        top_n=10,
        pool_scope=pool_scope,
        user=None,
    )

    assert result.success is True
    assert result.source == "cache"
    assert [score.code for score in result.scores] == ["000001.SZ"]
    assert result.metadata["scope_fallback"] is True
    assert result.metadata["scope_fallback_universe_id"] == "csi300"
    assert result.metadata["derived_from_broader_cache"] is True
    assert result.metadata["provider_source"] == AlphaScoreCacheModel.PROVIDER_QLIB


@pytest.mark.django_db
def test_cache_provider_surfaces_trade_date_adjusted_metadata_for_latest_qlib_result():
    AlphaScoreCacheModel._default_manager.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 21),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 4, 20),
        model_id="qlib-v1",
        model_artifact_hash="hash-1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260420",
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.3},
                "source": "qlib",
                "confidence": 0.88,
            }
        ],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        metrics_snapshot={
            "requested_trade_date": "2026-04-21",
            "effective_trade_date": "2026-04-20",
            "trade_date_adjusted": True,
        },
    )

    result = CacheAlphaProvider().get_stock_scores(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 21),
        top_n=10,
        user=None,
    )

    assert result.success is True
    assert result.status == "available"
    assert result.metadata["trade_date_adjusted"] is True
    assert result.metadata["effective_trade_date"] == "2026-04-20"


@pytest.mark.django_db
def test_cache_provider_preserves_degraded_forward_filled_cache_status():
    AlphaScoreCacheModel._default_manager.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 21),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 4, 20),
        model_id="qlib-v1",
        model_artifact_hash="hash-1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260420",
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.3},
                "source": "qlib",
                "confidence": 0.88,
            }
        ],
        status=AlphaScoreCacheModel.STATUS_DEGRADED,
        metrics_snapshot={
            "fallback_mode": "forward_fill_latest_qlib_cache",
            "fallback_reason": "Qlib 实时推理失败，已前推最近可用缓存。",
        },
    )

    result = CacheAlphaProvider().get_stock_scores(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 21),
        top_n=10,
        user=None,
    )

    assert result.success is True
    assert result.status == "degraded"
    assert result.metadata["fallback_mode"] == "forward_fill_latest_qlib_cache"
    assert result.metadata["fallback_reason"] == "Qlib 实时推理失败，已前推最近可用缓存。"


@pytest.mark.django_db
def test_cache_provider_prefers_fresh_broader_qlib_cache_over_scoped_forward_fill():
    pool_scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="price_covered",
        instrument_codes=("000001.SZ",),
        selection_reason="test",
        trade_date=date(2026, 4, 21),
        display_label="默认组合 · 价格覆盖池",
        portfolio_id=135,
        portfolio_name="默认组合",
    )
    AlphaScoreCacheModel._default_manager.create(
        universe_id=pool_scope.universe_id,
        intended_trade_date=date(2026, 4, 21),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 4, 20),
        model_id="qlib-v1",
        model_artifact_hash="hash-1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260420",
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.3},
                "source": "qlib",
                "confidence": 0.88,
            }
        ],
        status=AlphaScoreCacheModel.STATUS_DEGRADED,
        metrics_snapshot={
            "fallback_mode": "forward_fill_latest_qlib_cache",
            "fallback_reason": "Qlib 预测未返回任何评分",
            "scope_fallback_universe_id": "csi300",
        },
        scope_hash=pool_scope.scope_hash,
        scope_label=pool_scope.display_label,
        scope_metadata=pool_scope.to_dict(),
    )
    AlphaScoreCacheModel._default_manager.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 4, 21),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 4, 20),
        model_id="qlib-v1",
        model_artifact_hash="hash-1",
        feature_set_id="alpha158",
        label_id="label",
        data_version="20260420",
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.91,
                "rank": 1,
                "factors": {"quality": 0.3},
                "source": "qlib",
                "confidence": 0.88,
            }
        ],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        metrics_snapshot={
            "requested_trade_date": "2026-04-21",
            "effective_trade_date": "2026-04-20",
            "trade_date_adjusted": True,
        },
    )

    result = CacheAlphaProvider().get_stock_scores(
        universe_id=pool_scope.universe_id,
        intended_trade_date=date(2026, 4, 21),
        top_n=10,
        pool_scope=pool_scope,
        user=None,
    )

    assert result.success is True
    assert result.status == "available"
    assert result.metadata["derived_from_broader_cache"] is True
    assert result.metadata["trade_date_adjusted"] is True
