"""Freshness contracts for Decision Rhythm flow features."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.decision_rhythm.infrastructure.feature_providers import FlowFeatureProvider
from apps.realtime.domain.entities import PricePollingConfig


def _quote_payload(*, observed_at: datetime, volume: int = 150_000_000) -> dict[str, object]:
    return {
        "rows": [
            {
                "asset_code": "000001.SZ",
                "snapshot_at": observed_at.isoformat(),
                "current_price": "10.00",
                "volume": volume,
                "source": "canonical-test",
            }
        ],
        "observed_at": observed_at.isoformat(),
        "freshness_status": "fresh",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }


def test_flow_score_uses_fresh_cache_volume() -> None:
    """A fresh observation may contribute a directional flow feature."""
    with patch(
        "apps.decision_rhythm.infrastructure.feature_providers.get_published_quote_payloads",
        return_value=_quote_payload(observed_at=timezone.now()),
    ):

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
        "apps.decision_rhythm.infrastructure.feature_providers.get_published_quote_payloads",
        return_value=_quote_payload(observed_at=observed_at),
    ):

        provider = FlowFeatureProvider()
        result = provider.get_flow_score("000001.SZ")

    assert result == 0.5
    contract = provider.get_feature_freshness_contracts("000001.SZ")["flow"]
    assert contract["must_not_use_for_decision"] is True
    assert contract["blocked_reason"] == f"flow_price_{observation_kind}"


def test_flow_score_obeys_quote_publication_gate() -> None:
    """A blocked quote publication must not be replaced by Redis/cache data."""

    with patch(
        "apps.decision_rhythm.infrastructure.feature_providers.get_published_quote_payloads",
        return_value={
            "rows": [],
            "freshness_status": "stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
            "observed_at": "2026-08-01T08:00:00+00:00",
        },
    ):
        provider = FlowFeatureProvider()
        assert provider.get_flow_score("000001.SZ") == 0.5

    contract = provider.get_feature_freshness_contracts("000001.SZ")["flow"]
    assert contract["freshness_status"] == "stale"
    assert contract["must_not_use_for_decision"] is True
    assert contract["blocked_reason"] == "canonical_publication_stale"
