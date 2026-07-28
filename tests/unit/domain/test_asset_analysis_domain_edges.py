"""Boundary and matcher tests for the Asset Analysis Domain."""

from dataclasses import dataclass
from datetime import date

import pytest

from apps.asset_analysis.domain.entities import (
    AssetScore,
    AssetStyle,
    AssetType,
)
from apps.asset_analysis.domain.pool import (
    EntryReason,
    ExitReason,
    PoolCategory,
    PoolConfig,
    PoolEntry,
    PoolStatistics,
    PoolType,
)
from apps.asset_analysis.domain.services import (
    PolicyMatcher,
    RegimeMatcher,
    SentimentMatcher,
    SignalMatcher,
)
from apps.asset_analysis.domain.value_objects import ScoreContext, WeightConfig


def _asset(
    asset_type: AssetType = AssetType.EQUITY,
    *,
    style: AssetStyle | None = None,
    sector: str | None = None,
) -> AssetScore:
    """Build a valid asset score."""
    return AssetScore(
        asset_type=asset_type,
        asset_code="000001.SZ",
        asset_name="Asset",
        style=style,
        sector=sector,
    )


def test_asset_score_rejects_invalid_allocation_and_serializes_style() -> None:
    """Allocation is bounded and optional classification remains explicit."""
    with pytest.raises(ValueError, match="allocation_percent"):
        AssetScore(
            asset_type=AssetType.EQUITY,
            asset_code="000001.SZ",
            asset_name="Asset",
            allocation_percent=101,
        )
    payload = _asset(
        style=AssetStyle.QUALITY,
        sector="科技",
    ).to_dict()
    assert payload["style"] == "quality"
    assert payload["sector"] == "科技"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"asset_code": "  "}, "asset_code"),
        ({"asset_name": ""}, "asset_name"),
        ({"regime_score": True}, "regime_score"),
        ({"custom_scores": {"quality": float("nan")}}, "custom_scores.quality"),
        ({"total_score": float("inf")}, "total_score"),
        ({"rank": -1}, "rank"),
        ({"allocation_percent": False}, "allocation_percent"),
    ],
)
def test_asset_score_rejects_invalid_identity_and_numeric_boundaries(
    change: dict[str, object],
    message: str,
) -> None:
    """Invalid dynamic values never enter the shared scoring entity."""

    kwargs: dict[str, object] = {
        "asset_type": AssetType.EQUITY,
        "asset_code": "000001.SZ",
        "asset_name": "Asset",
    }
    kwargs.update(change)

    with pytest.raises(ValueError, match=message):
        AssetScore(**kwargs)  # type: ignore[arg-type]


def test_pool_value_objects_publish_dates_reasons_and_thresholds() -> None:
    """Pool contracts preserve lifecycle metadata and exact score boundaries."""
    entry = PoolEntry(
        asset_type=PoolCategory.EQUITY,
        asset_code="000001.SZ",
        asset_name="Asset",
        pool_type=PoolType.WATCH,
        entry_date=date(2026, 7, 1),
        entry_reason=EntryReason.MANUAL_ADD,
        exit_date=date(2026, 7, 24),
        exit_reason=ExitReason.SCORE_DECLINE,
        is_active=False,
    )
    payload = entry.to_dict()
    assert payload["entry_reason"] == "manual_add"
    assert payload["exit_reason"] == "score_decline"

    statistics = PoolStatistics(
        pool_type=PoolType.INVESTABLE,
        asset_category=PoolCategory.EQUITY,
        total_count=2,
        avg_score=66.666,
        last_updated=date(2026, 7, 24),
    )
    assert statistics.to_dict()["avg_score"] == 66.67

    config = PoolConfig(
        pool_type=PoolType.INVESTABLE,
        asset_category=PoolCategory.EQUITY,
    )
    assert config.is_investable(60, 50, 50) is True
    assert config.is_prohibited(31, 40, 50) is True
    assert config.is_watch(30) is False
    assert config.is_watch(45) is True
    assert config.is_watch(60) is False


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"current_regime": "Unknown"}, "current_regime"),
        ({"policy_level": "P4"}, "policy_level"),
    ],
)
def test_score_context_rejects_unknown_regime_or_policy(
    change: dict[str, object], message: str
) -> None:
    """Only governed macro and policy states enter scoring."""
    kwargs: dict[str, object] = {
        "current_regime": "Recovery",
        "policy_level": "P0",
        "sentiment_index": 0.0,
        "active_signals": [],
    }
    kwargs.update(change)
    with pytest.raises(ValueError, match=message):
        ScoreContext(**kwargs)  # type: ignore[arg-type]


def test_weight_and_context_serialization_are_stable() -> None:
    """Scoring configuration exposes all weights and signal cardinality."""
    assert WeightConfig().to_dict() == {
        "regime": 0.4,
        "policy": 0.25,
        "sentiment": 0.2,
        "signal": 0.15,
    }
    context = ScoreContext(
        current_regime="Recovery",
        policy_level="P1",
        sentiment_index=0.2,
        active_signals=[object()],
        score_date=date(2026, 7, 24),
    )
    assert context.to_dict()["active_signals_count"] == 1


def test_regime_and_policy_matchers_cover_unknown_and_sector_adjustments() -> None:
    """Unknown matrix entries use bounded defaults; sector evidence can adjust."""
    sector_asset = _asset(style=AssetStyle.GROWTH, sector="科技")
    assert RegimeMatcher.match(sector_asset, "Recovery") == 99.5
    assert RegimeMatcher.match(_asset(), "Unknown") == 58.0
    assert RegimeMatcher._get_sector_regime_score("unknown", "Recovery") == 70
    assert PolicyMatcher.match(_asset(), "Unknown") == 50.0


@pytest.mark.parametrize(
    ("asset_type", "score", "expected"),
    [
        (AssetType.EQUITY, 0.0, 50.0),
        (AssetType.EQUITY, -2.0, 50.0),
        (AssetType.BOND, 0.0, 50.0),
        (AssetType.COMMODITY, 2.5, 80.0),
        (AssetType.COMMODITY, 1.5, 65.0),
        (AssetType.COMMODITY, 0.5, 50.0),
        (AssetType.SECTOR, 0.0, 50.0),
    ],
)
def test_sentiment_matcher_covers_all_asset_classes(
    asset_type: AssetType, score: float, expected: float
) -> None:
    """Risk-on, defensive, commodity, and fallback branches stay explicit."""
    assert SentimentMatcher.match(_asset(asset_type), score) == expected


@dataclass
class _Signal:
    asset_code: str = ""
    asset_class: str = ""
    sector: str = ""


def test_signal_matcher_counts_code_class_sector_and_nonmatches() -> None:
    """All supported signal scopes contribute exactly one match each."""
    asset = _asset(sector="科技")
    assert (
        SignalMatcher.match(
            asset,
            [
                _Signal(asset_code="000001.SZ"),
                _Signal(asset_class="equity"),
                _Signal(sector="科技"),
            ],
        )
        == 90.0
    )
    assert SignalMatcher.match(asset, [_Signal(asset_class="equity")] * 2) == 75.0
    assert SignalMatcher.match(asset, [_Signal(asset_code="other")]) == 40.0
