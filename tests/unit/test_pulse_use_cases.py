from datetime import date

import pytest

from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.pulse.domain.entities import DimensionScore, PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.models import PulseLog
from apps.pulse.infrastructure.repositories import PulseRepository


def _pulse_snapshot(
    *,
    observed_at: date = date(2026, 4, 1),
    composite_score: float = 0.12,
    regime_strength: str = "moderate",
    data_source: str = "calculated",
    stale_indicator_count: int = 0,
) -> PulseSnapshot:
    return PulseSnapshot(
        observed_at=observed_at,
        regime_context="Recovery",
        dimension_scores=[
            DimensionScore("growth", 0.4, "bullish", 2, "增长脉搏偏强"),
            DimensionScore("inflation", 0.0, "neutral", 1, "通胀脉搏中性"),
            DimensionScore("liquidity", -0.1, "neutral", 2, "流动性脉搏中性"),
            DimensionScore("sentiment", 0.2, "neutral", 2, "情绪脉搏中性"),
        ],
        composite_score=composite_score,
        regime_strength=regime_strength,
        transition_warning=False,
        transition_direction=None,
        transition_reasons=[],
        indicator_readings=[
            PulseIndicatorReading(
                code="CN_TERM_SPREAD_10Y2Y",
                name="国债利差(10Y-2Y)",
                dimension="growth",
                value=90.0,
                z_score=0.5,
                direction="improving",
                signal="bullish",
                signal_score=0.4,
                weight=1.0,
                data_age_days=1,
                is_stale=stale_indicator_count > 0,
            )
        ],
        data_source=data_source,
        stale_indicator_count=stale_indicator_count,
    )


@pytest.mark.django_db
def test_save_snapshot_updates_existing_observed_date():
    repo = PulseRepository()

    repo.save_snapshot(_pulse_snapshot(composite_score=0.10, regime_strength="moderate"))
    repo.save_snapshot(_pulse_snapshot(composite_score=-0.35, regime_strength="weak"))

    assert PulseLog.objects.count() == 1
    log = PulseLog.objects.get()
    assert log.composite_score == pytest.approx(-0.35)
    assert log.regime_strength == "weak"


@pytest.mark.django_db
def test_get_latest_reliable_snapshot_returns_none_without_refresh():
    PulseRepository().save_snapshot(
        _pulse_snapshot(
            observed_at=date(2026, 4, 6),
            data_source="stale",
            stale_indicator_count=1,
        )
    )

    snapshot = GetLatestPulseUseCase().execute(
        as_of_date=date(2026, 4, 8),
        require_reliable=True,
    )

    assert snapshot is None


@pytest.mark.django_db
def test_get_latest_refreshes_stale_snapshot_when_requested(monkeypatch):
    repo = PulseRepository()
    repo.save_snapshot(
        _pulse_snapshot(
            observed_at=date(2026, 4, 6),
            data_source="stale",
            stale_indicator_count=1,
        )
    )
    refreshed = _pulse_snapshot(
        observed_at=date(2026, 4, 8),
        composite_score=0.38,
        regime_strength="strong",
    )
    captured: dict[str, date | None] = {}

    def _fake_calculate(self, as_of_date=None):
        captured["as_of_date"] = as_of_date
        return refreshed

    monkeypatch.setattr(
        "apps.pulse.application.use_cases.CalculatePulseUseCase.execute",
        _fake_calculate,
    )

    snapshot = GetLatestPulseUseCase().execute(
        as_of_date=date(2026, 4, 8),
        require_reliable=True,
        refresh_if_stale=True,
    )

    assert snapshot == refreshed
    assert captured["as_of_date"] == date(2026, 4, 8)
