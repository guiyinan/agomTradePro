from datetime import date

from apps.alpha.application.services import _enrich_result_metadata
from apps.alpha.domain.entities import AlphaResult, StockScore


def _build_score(*, asof_date: date) -> StockScore:
    return StockScore(
        code="000001.SZ",
        score=0.91,
        rank=1,
        factors={"quality": 0.3},
        source="qlib",
        confidence=0.88,
        asof_date=asof_date,
        intended_trade_date=asof_date,
        universe_id="csi300",
    )


def test_enrich_result_metadata_treats_latest_available_qlib_cache_as_live():
    result = AlphaResult(
        success=True,
        scores=[_build_score(asof_date=date(2026, 4, 20))],
        source="cache",
        timestamp="2026-04-21T08:00:00+08:00",
        status="available",
        staleness_days=1,
        metadata={
            "provider_source": "qlib",
            "requested_trade_date": "2026-04-21",
            "effective_trade_date": "2026-04-20",
            "trade_date_adjusted": True,
        },
    )

    enriched = _enrich_result_metadata(result, date(2026, 4, 21))

    assert enriched.metadata["uses_cached_data"] is False
    assert enriched.metadata["latest_available_qlib_result"] is True
    assert enriched.metadata["reliability_notice"]["code"] == "qlib_trade_date_adjusted"


def test_enrich_result_metadata_preserves_explicit_provider_notice():
    result = AlphaResult(
        success=True,
        scores=[_build_score(asof_date=date(2026, 4, 20))],
        source="cache",
        timestamp="2026-04-21T08:00:00+08:00",
        status="available",
        staleness_days=1,
        metadata={
            "provider_source": "qlib",
            "reliability_notice": {
                "level": "warning",
                "code": "scoped_cache_derived_from_broader_cache",
                "title": "Alpha 当前使用账户池映射缓存",
                "message": "账户池专属缓存尚未生成。",
            },
        },
    )

    enriched = _enrich_result_metadata(result, date(2026, 4, 21))

    assert enriched.metadata["reliability_notice"]["code"] == "scoped_cache_derived_from_broader_cache"
