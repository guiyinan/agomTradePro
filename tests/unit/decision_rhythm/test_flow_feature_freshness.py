"""Freshness contracts for Decision Rhythm flow features."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.decision_rhythm.infrastructure.feature_providers import FlowFeatureProvider
from apps.realtime.domain.entities import AssetType, PricePollingConfig, RealtimePrice


def _price(*, observed_at: datetime, volume: int = 150_000_000) -> RealtimePrice:
    return RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("10.00"),
        change=None,
        change_pct=None,
        volume=volume,
        timestamp=observed_at,
        source="redis",
    )


def test_flow_score_uses_fresh_cache_volume() -> None:
    """A fresh observation may contribute a directional flow feature."""
    with patch(
        "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
    ) as repository_class:
        repository_class.return_value.get_latest_price.return_value = _price(
            observed_at=timezone.now()
        )

        provider = FlowFeatureProvider()
        result = provider.get_flow_score("000001.SZ")

    assert result > 0.5


@pytest.mark.parametrize(
    "observation_kind",
    [
        "stale",
        "future",
        "naive",
    ],
)
def test_flow_score_returns_neutral_for_unusable_cache(observation_kind: str) -> None:
    """Stale, future, and naive observations must not create a flow signal."""
    now = timezone.now()
    if observation_kind == "stale":
        observed_at = now - timedelta(seconds=PricePollingConfig().max_price_age_seconds + 1)
    elif observation_kind == "future":
        observed_at = now + timedelta(hours=1)
    else:
        observed_at = datetime(2026, 7, 30, 10, 0)

    with patch(
        "apps.realtime.infrastructure.repositories.RedisRealtimePriceRepository"
    ) as repository_class:
        repository_class.return_value.get_latest_price.return_value = _price(
            observed_at=observed_at
        )

        provider = FlowFeatureProvider()
        result = provider.get_flow_score("000001.SZ")

    assert result == 0.5
    contract = provider.get_feature_freshness_contracts("000001.SZ")["flow"]
    assert contract["must_not_use_for_decision"] is True
    assert contract["blocked_reason"] == f"flow_price_{observation_kind}"
