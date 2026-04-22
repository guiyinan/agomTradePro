from datetime import date

import pytest
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APIClient

from apps.pulse.domain.entities import DimensionScore, PulseIndicatorReading, PulseSnapshot
from apps.pulse.infrastructure.models import PulseLog
from apps.pulse.infrastructure.repositories import PulseRepository


def _pulse_snapshot() -> PulseSnapshot:
    return PulseSnapshot(
        observed_at=date(2026, 3, 24),
        regime_context="Recovery",
        dimension_scores=[
            DimensionScore("growth", 0.4, "bullish", 2, "增长脉搏偏强"),
            DimensionScore("inflation", 0.0, "neutral", 1, "通胀脉搏中性"),
            DimensionScore("liquidity", -0.3, "bearish", 2, "流动性脉搏偏弱"),
            DimensionScore("sentiment", 0.2, "neutral", 2, "情绪脉搏中性"),
        ],
        composite_score=0.075,
        regime_strength="moderate",
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
                is_stale=False,
            )
        ],
        data_source="calculated",
        stale_indicator_count=0,
    )


def _stale_pulse_snapshot() -> PulseSnapshot:
    return PulseSnapshot(
        observed_at=date(2026, 4, 21),
        regime_context="Recovery",
        dimension_scores=[
            DimensionScore("growth", 0.4, "bullish", 2, "增长脉搏偏强"),
            DimensionScore("inflation", 0.0, "neutral", 1, "通胀脉搏中性"),
            DimensionScore("liquidity", -0.3, "bearish", 2, "流动性脉搏偏弱"),
            DimensionScore("sentiment", 0.2, "neutral", 2, "情绪脉搏中性"),
        ],
        composite_score=0.351,
        regime_strength="strong",
        transition_warning=False,
        transition_direction=None,
        transition_reasons=[],
        indicator_readings=[
            PulseIndicatorReading(
                code="CN_PMI",
                name="中国 PMI",
                dimension="growth",
                value=49.4,
                z_score=0.5,
                direction="deteriorating",
                signal="bearish",
                signal_score=-0.4,
                weight=1.0,
                data_age_days=3762,
                is_stale=True,
            ),
            PulseIndicatorReading(
                code="000300.SH",
                name="沪深300",
                dimension="sentiment",
                value=3900.0,
                z_score=0.1,
                direction="stable",
                signal="neutral",
                signal_score=0.0,
                weight=1.0,
                data_age_days=15,
                is_stale=True,
            ),
        ],
        data_source="stale",
        stale_indicator_count=2,
    )


@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username="pulse-api", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_pulse_current_api_contract(authenticated_client):
    PulseRepository().save_snapshot(_pulse_snapshot())

    response = authenticated_client.get("/api/pulse/current/")

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["regime_context"] == "Recovery"
    assert "dimensions" in payload["data"]
    assert payload["data"]["must_not_use_for_decision"] is False
    assert payload["data"]["contract"]["must_not_use_for_decision"] is False


@pytest.mark.django_db
def test_pulse_current_api_marks_stale_snapshot_as_diagnostic_only(authenticated_client):
    PulseRepository().save_snapshot(_stale_pulse_snapshot())

    response = authenticated_client.get("/api/pulse/current/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    contract = payload["data"]["contract"]
    assert payload["success"] is True
    assert payload["data"]["data_source"] == "stale"
    assert payload["data"]["is_reliable"] is False
    assert payload["data"]["is_stale"] is True
    assert payload["data"]["must_not_use_for_decision"] is True
    assert payload["data"]["stale_indicator_codes"] == ["CN_PMI", "000300.SH"]
    assert contract["must_not_use_for_decision"] is True
    assert contract["stale_indicator_codes"] == ["CN_PMI", "000300.SH"]
    assert "仅可用于诊断" in contract["blocked_reason"]


@pytest.mark.django_db
def test_pulse_history_api_contract(authenticated_client):
    PulseRepository().save_snapshot(_pulse_snapshot())
    PulseLog.objects.create(
        observed_at=date(2026, 3, 1),
        regime_context="Recovery",
        growth_score=0.2,
        inflation_score=0.1,
        liquidity_score=-0.1,
        sentiment_score=0.0,
        composite_score=0.05,
        regime_strength="moderate",
        transition_warning=False,
        transition_direction=None,
        indicator_readings=[],
        transition_reasons=[],
        data_source="calculated",
    )

    response = authenticated_client.get("/api/pulse/history/?months=6")

    assert response.status_code == status.HTTP_200_OK
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["success"] is True
    assert payload["count"] >= 2
    assert isinstance(payload["data"], list)


@pytest.mark.django_db
def test_pulse_current_requests_refresh_when_snapshot_missing(authenticated_client, monkeypatch):
    snapshot = _pulse_snapshot()
    captured: dict[str, object] = {}

    def _fake_execute(self, *args, **kwargs):
        captured.update(kwargs)
        return snapshot

    monkeypatch.setattr("apps.pulse.application.use_cases.GetLatestPulseUseCase.execute", _fake_execute)

    response = authenticated_client.get("/api/pulse/current/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["regime_context"] == snapshot.regime_context
    assert captured["refresh_if_stale"] is True
    assert captured["as_of_date"] == date.today()
