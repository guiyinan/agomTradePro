"""Repository regression tests for asset analysis."""

from datetime import date, timedelta

import pytest

from apps.asset_analysis.infrastructure.models import AssetPoolEntry, WeightConfigModel
from apps.asset_analysis.infrastructure.repositories import (
    DjangoAssetPoolQueryRepository,
    DjangoWeightConfigRepository,
)


def _create_pool_entry(
    *,
    asset_code: str,
    asset_name: str,
    entry_date: date,
    total_score: float = 80.0,
) -> AssetPoolEntry:
    return AssetPoolEntry._default_manager.create(
        asset_category="equity",
        asset_code=asset_code,
        asset_name=asset_name,
        pool_type="investable",
        total_score=total_score,
        regime_score=80.0,
        policy_score=80.0,
        sentiment_score=80.0,
        signal_score=80.0,
        entry_date=entry_date,
        is_active=True,
    )


@pytest.mark.django_db
def test_weight_fallback_does_not_select_unmatched_market_condition() -> None:
    WeightConfigModel._default_manager.create(
        name="equity-crisis",
        asset_type="equity",
        market_condition="crisis",
        regime_weight=0.7,
        policy_weight=0.1,
        sentiment_weight=0.1,
        signal_weight=0.1,
        priority=100,
    )
    WeightConfigModel._default_manager.create(
        name="equity-default",
        asset_type="equity",
        market_condition=None,
        regime_weight=0.4,
        policy_weight=0.3,
        sentiment_weight=0.2,
        signal_weight=0.1,
        priority=1,
    )

    weights = DjangoWeightConfigRepository().get_active_weights(
        asset_type="equity",
        market_condition="normal",
    )

    assert weights.regime_weight == 0.4
    assert weights.policy_weight == 0.3


@pytest.mark.django_db
def test_save_config_rejects_non_finite_weights() -> None:
    repository = DjangoWeightConfigRepository()

    with pytest.raises(ValueError, match="有限值"):
        repository.save_config(
            name="invalid",
            regime_weight=float("nan"),
            policy_weight=0.3,
            sentiment_weight=0.2,
            signal_weight=0.1,
        )

    assert not WeightConfigModel._default_manager.filter(name="invalid").exists()


@pytest.mark.django_db
def test_resolve_asset_names_prefers_latest_active_entry() -> None:
    today = date.today()
    _create_pool_entry(
        asset_code="000001.SZ",
        asset_name="旧名称",
        entry_date=today - timedelta(days=1),
    )
    _create_pool_entry(
        asset_code="000001.SZ",
        asset_name="新名称",
        entry_date=today,
    )

    resolved = DjangoAssetPoolQueryRepository().resolve_asset_names([" 000001.sz ", "000001.SZ"])

    assert resolved == {"000001.SZ": "新名称"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("asset_type", "min_score", "limit"),
    [
        ("", 60.0, 10),
        ("equity", float("nan"), 10),
        ("equity", 60.0, 0),
    ],
)
def test_list_investable_assets_rejects_invalid_query(
    asset_type: str,
    min_score: float,
    limit: int,
) -> None:
    assert (
        DjangoAssetPoolQueryRepository().list_investable_assets(
            asset_type,
            min_score,
            limit,
        )
        == []
    )
