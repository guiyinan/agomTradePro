from __future__ import annotations

from datetime import date

import pytest

from apps.asset_analysis.application.pool_service import (
    AssetPoolClassifier,
    AssetPoolManager,
)
from apps.asset_analysis.domain.entities import AssetScore, AssetType
from apps.asset_analysis.domain.pool import (
    PoolCategory,
    PoolConfig,
    PoolType,
)
from apps.asset_analysis.domain.value_objects import ScoreContext
from apps.asset_analysis.infrastructure.repositories import (
    DjangoAssetPoolQueryRepository,
)


def _config(
    category: PoolCategory = PoolCategory.EQUITY,
    *,
    min_total_score: float = 60.0,
) -> PoolConfig:
    return PoolConfig(
        pool_type=PoolType.INVESTABLE,
        asset_category=category,
        min_total_score=min_total_score,
        min_regime_score=50.0,
        min_policy_score=50.0,
        max_total_score=30.0,
        max_regime_score=40.0,
        max_policy_score=40.0,
    )


def _context() -> ScoreContext:
    return ScoreContext(
        current_regime="Recovery",
        policy_level="P1",
        sentiment_index=0.0,
        active_signals=[],
        score_date=date(2026, 7, 24),
    )


def _score(
    asset_type: AssetType = AssetType.EQUITY,
    *,
    total_score: float = 80.0,
) -> AssetScore:
    return AssetScore(
        asset_type=asset_type,
        asset_code="600000.SH",
        asset_name="测试资产",
        total_score=total_score,
        regime_score=80.0,
        policy_score=80.0,
        sentiment_score=70.0,
        signal_score=70.0,
    )


def test_classifier_uses_injected_thresholds() -> None:
    strict_classifier = AssetPoolClassifier([_config(min_total_score=90.0)])
    permissive_classifier = AssetPoolClassifier([_config(min_total_score=60.0)])

    strict_entry = strict_classifier.classify(_score(), _context())
    permissive_entry = permissive_classifier.classify(_score(), _context())

    assert strict_entry.pool_type == PoolType.CANDIDATE
    assert permissive_entry.pool_type == PoolType.INVESTABLE


def test_classifier_rejects_missing_duplicate_and_unsupported_config() -> None:
    with pytest.raises(ValueError, match="Duplicate active pool config"):
        AssetPoolClassifier([_config(), _config()])

    classifier = AssetPoolClassifier([_config()])
    with pytest.raises(ValueError, match="Missing active pool config"):
        classifier.classify(_score(AssetType.FUND), _context())

    with pytest.raises(ValueError, match="Unsupported pool asset type"):
        classifier.classify(_score(AssetType.SECTOR), _context())


def test_classifier_rejects_non_finite_score_and_category_mismatch() -> None:
    classifier = AssetPoolClassifier([_config()])
    with pytest.raises(ValueError, match="total_score must be finite"):
        classifier.classify(_score(total_score=float("nan")), _context())

    manager = AssetPoolManager([_config()])
    with pytest.raises(ValueError, match="Asset category mismatch"):
        manager.create_pools(
            [_score()],
            _context(),
            PoolCategory.FUND,
        )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("min_total_score", float("nan")),
        ("watch_min_score", 60.0),
        ("max_pe_ratio", -1.0),
    ],
)
def test_pool_config_rejects_invalid_financial_thresholds(
    field_name: str,
    field_value: float,
) -> None:
    values = {
        "pool_type": PoolType.INVESTABLE,
        "asset_category": PoolCategory.EQUITY,
        field_name: field_value,
    }
    with pytest.raises(ValueError):
        PoolConfig(**values)


@pytest.mark.django_db
def test_repository_reads_seeded_pool_thresholds() -> None:
    configs = DjangoAssetPoolQueryRepository().list_active_pool_configs()

    configs_by_category = {config.asset_category: config for config in configs}
    assert configs_by_category[PoolCategory.EQUITY].min_total_score == 60.0
    assert configs_by_category[PoolCategory.FUND].min_total_score == 65.0
    assert configs_by_category[PoolCategory.BOND].min_policy_score == 60.0
