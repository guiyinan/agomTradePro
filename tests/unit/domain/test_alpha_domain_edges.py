"""Behavioral boundary tests for the Alpha Domain."""

from datetime import date

import pytest

from apps.alpha.domain.entities import (
    AlphaPoolScope,
    AlphaProviderConfig,
    AlphaResult,
    InvalidationCondition,
    InvalidationType,
    StockScore,
    UniverseDefinition,
    normalize_stock_code,
)
from apps.alpha.domain.rules import is_actionable_score, is_reliable_result
from apps.alpha.domain.services import select_actionable_scores


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("000001.sz", "000001.SZ"),
        ("SH600000", "600000.SH"),
        ("legacy=('430047',)", "430047.BJ"),
        ("600000", "600000.SH"),
        ("000001", "000001.SZ"),
        ("not-a-stock", "NOT-A-STOCK"),
    ],
)
def test_normalize_stock_code_handles_legacy_exchange_formats(raw: object, expected: str) -> None:
    """Stock identifiers normalize without losing unknown upstream values."""
    assert normalize_stock_code(raw) == expected


def _score(
    *,
    code: str = "000001.SZ",
    score: float = 0.8,
    confidence: float = 0.9,
) -> StockScore:
    """Build a complete deterministic score."""
    return StockScore(
        code=code,
        score=score,
        rank=1,
        factors={"momentum": 0.7},
        source="test",
        confidence=confidence,
        model_id="model-1",
        model_artifact_hash="sha256:abc",
        asof_date=date(2026, 7, 23),
        intended_trade_date=date(2026, 7, 24),
        universe_id="cn-a",
        feature_set_id="features-1",
        label_id="label-1",
        data_version="v1",
    )


def test_alpha_value_objects_round_trip_without_dropping_audit_fields() -> None:
    """Serialization preserves dates, invalidations, and model lineage."""
    condition = InvalidationCondition(
        condition_type=InvalidationType.MODEL_DRIFT,
        min_ic=0.03,
        description="IC below production floor",
    )
    assert InvalidationCondition.from_dict(condition.to_dict()) == condition

    score = _score()
    assert StockScore.from_dict(score.to_dict()) == score
    invalid_factors = score.to_dict() | {"factors": "not-a-mapping"}
    assert StockScore.from_dict(invalid_factors).factors == {}

    result = AlphaResult(
        success=True,
        scores=[score],
        source="qlib",
        timestamp="2026-07-23T08:00:00+00:00",
        staleness_days=1,
        invalidation_conditions=[condition],
        metadata={"run_id": "run-1"},
    )
    payload = result.to_dict()
    assert payload["stocks"] == [score.to_dict()]
    assert payload["invalidation_conditions"] == [condition.to_dict()]
    assert payload["metadata"]["run_id"] == "run-1"


def test_pool_scope_normalizes_deduplicates_and_builds_stable_identity() -> None:
    """Pool identity is canonical, deterministic, and portfolio-aware."""
    scope = AlphaPoolScope(
        pool_type="portfolio_market",
        market="CN",
        pool_mode="strict_valuation",
        instrument_codes=("000001", "SZ000001", "", "600000"),
        selection_reason="eligible holdings",
        trade_date=date(2026, 7, 24),
        portfolio_id=42,
        portfolio_name="Core",
    )

    assert scope.instrument_codes == ("000001.SZ", "600000.SH")
    assert scope.pool_size == 2
    assert scope.universe_id == f"portfolio-42-{scope.scope_hash}"
    assert AlphaPoolScope.from_dict(scope.to_dict()) == scope

    market_scope = AlphaPoolScope.from_dict(
        {
            "instrument_codes": ["430047"],
            "selection_reason": "fallback",
        }
    )
    assert market_scope.universe_id.startswith("cn-portfolio_market-")
    assert market_scope.trade_date == date.today()


def test_provider_config_and_universe_publish_json_safe_contracts() -> None:
    """Configuration defaults and overrides remain stable at the boundary."""
    config = AlphaProviderConfig.from_dict(
        {
            "max_staleness_days": 5,
            "max_latency_ms": 900,
            "enable_cache": False,
            "cache_ttl_seconds": 60,
            "retry_attempts": 1,
            "retry_delay_seconds": 0,
            "timeout_seconds": 3,
        }
    )
    assert AlphaProviderConfig.from_dict(config.to_dict()) == config
    assert AlphaProviderConfig.from_dict({}) == AlphaProviderConfig()

    universe = UniverseDefinition(
        universe_id="csi300",
        name="沪深300",
        description="large caps",
        stock_codes=["600000.SH"],
        index_code="000300.SH",
        weight_method="market_cap",
        rebalance_frequency="quarterly",
    )
    assert universe.to_dict()["stock_codes"] == ["600000.SH"]
    assert universe.to_dict()["rebalance_frequency"] == "quarterly"


@pytest.mark.parametrize(
    ("score", "minimum", "confidence", "expected"),
    [
        (0.01, 0.0, 0.5, True),
        (0.0, 0.0, 0.9, False),
        (0.8, 0.0, 0.49, False),
    ],
)
def test_actionable_score_uses_strict_score_and_inclusive_confidence_floors(
    score: float,
    minimum: float,
    confidence: float,
    expected: bool,
) -> None:
    """Threshold semantics do not silently change at exact boundaries."""
    assert (
        is_actionable_score(
            _score(score=score, confidence=confidence),
            min_score=minimum,
            min_confidence=0.5,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("success", "status", "staleness", "expected"),
    [
        (False, "available", None, False),
        (True, "unavailable", None, False),
        (True, "available", None, True),
        (True, "degraded", 3, True),
        (True, "degraded", 4, False),
    ],
)
def test_result_reliability_is_fail_closed_and_freshness_aware(
    success: bool,
    status: str,
    staleness: int | None,
    expected: bool,
) -> None:
    """Unavailable or stale results cannot create downstream candidates."""
    result = AlphaResult(
        success=success,
        scores=[],
        source="test",
        timestamp="2026-07-24T00:00:00+00:00",
        status=status,
        staleness_days=staleness,
    )
    assert is_reliable_result(result, max_staleness_days=3) is expected


def test_select_actionable_scores_filters_and_fails_closed() -> None:
    """Selection returns only scores satisfying both business thresholds."""
    scores = [
        _score(code="000001.SZ", score=0.8, confidence=0.9),
        _score(code="600000.SH", score=0.4, confidence=0.4),
        _score(code="430047.BJ", score=-0.2, confidence=0.9),
    ]
    result = AlphaResult(
        success=True,
        scores=scores,
        source="test",
        timestamp="2026-07-24T00:00:00+00:00",
        staleness_days=1,
    )
    assert select_actionable_scores(
        result,
        min_score=0.0,
        min_confidence=0.5,
        max_staleness_days=2,
    ) == [scores[0]]

    result.staleness_days = 5
    assert select_actionable_scores(result, max_staleness_days=2) == []
