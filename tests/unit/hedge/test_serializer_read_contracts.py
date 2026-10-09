"""Persisted read formatting must remain stable after removing ORM serializers."""

from datetime import UTC, date, datetime

from apps.hedge.infrastructure.models import (
    CorrelationHistoryModel,
    HedgeAlertModel,
    HedgePairModel,
    HedgePerformanceModel,
    HedgePortfolioSnapshotModel,
)
from apps.hedge.interface.serializers import (
    CorrelationHistorySerializer,
    HedgeAlertSerializer,
    HedgePairSerializer,
    HedgePerformanceSerializer,
    HedgePortfolioSnapshotSerializer,
)


def test_persisted_read_serializers_keep_ids_dates_nulls_and_numeric_types():
    observed = date(2026, 10, 8)
    created = datetime(2026, 10, 8, tzinfo=UTC)
    pair = HedgePairModel(
        pk=7, name="pair", long_asset="A", hedge_asset="B", created_at=created, updated_at=created
    )
    snapshot = HedgePortfolioSnapshotModel(
        pk=8,
        pair=pair,
        trade_date=observed,
        long_weight=0.6,
        hedge_weight=0.4,
        hedge_ratio=0.7,
        current_correlation=-0.5,
        created_at=created,
    )
    payload = HedgePortfolioSnapshotSerializer(snapshot).data
    assert payload["pair"] == 7
    assert payload["pair_name"] == "pair"
    assert payload["trade_date"] == "2026-10-08"
    assert payload["current_correlation"] == -0.5
    assert isinstance(payload["rebalance_needed"], bool)
    assert len(payload) == 22
    assert HedgePairSerializer(pair).data["beta_target"] is None
    history = CorrelationHistoryModel(
        pk=9,
        asset1="A",
        asset2="B",
        calc_date=observed,
        window_days=60,
        correlation=-0.5,
        created_at=created,
    )
    history_data = CorrelationHistorySerializer(history).data
    assert history_data["calc_date"] == "2026-10-08"
    assert history_data["window_days"] == 60
    assert len(history_data) == 15
    alert = HedgeAlertModel(
        pk=10,
        pair_name="pair",
        alert_date=observed,
        alert_type="beta_change",
        message="drift",
        created_at=created,
    )
    alert_data = HedgeAlertSerializer(alert).data
    assert alert_data["resolved_at"] is None
    assert len(alert_data) == 13
    performance = HedgePerformanceModel(
        pk=11,
        pair_name="pair",
        period_start=observed,
        period_end=observed,
        total_return=0.1,
        annual_return=0.2,
        sharpe_ratio=1.0,
        volatility_reduction=0.3,
        drawdown_reduction=0.4,
        hedge_effectiveness=0.5,
        avg_correlation=-0.6,
        created_at=created,
    )
    performance_data = HedgePerformanceSerializer(performance).data
    assert performance_data["period_end"] == "2026-10-08"
    assert performance_data["avg_correlation"] == -0.6
    assert len(performance_data) == 15
