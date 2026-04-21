from datetime import date
from types import SimpleNamespace

import pytest

from apps.pulse.application.use_cases import (
    CalculatePulseUseCase,
    PULSE_MACRO_SYNC_INDICATORS,
)
from apps.pulse.domain.entities import PulseIndicatorReading


@pytest.mark.django_db
def test_calculate_pulse_refreshes_macro_inputs_before_calculation(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSyncUseCase:
        def execute(self, request):
            captured["sync_request"] = request
            return SimpleNamespace(success=True, synced_count=6, skipped_count=0, errors=[])

    class FakeProvider:
        def get_all_readings(self, as_of_date):
            captured["provider_date"] = as_of_date
            return [
                PulseIndicatorReading(
                    code="CN_PMI",
                    name="制造业PMI",
                    dimension="growth",
                    value=50.4,
                    z_score=1.2,
                    direction="improving",
                    signal="bullish",
                    signal_score=1.0,
                    weight=1.0,
                    data_age_days=0,
                    is_stale=False,
                )
            ]

    class FakeRepository:
        def save_snapshot(self, snapshot):
            captured["saved_snapshot"] = snapshot

    monkeypatch.setattr(
        "apps.macro.application.use_cases.build_sync_macro_data_use_case",
        lambda source=None: FakeSyncUseCase(),
    )
    monkeypatch.setattr(
        "apps.regime.application.current_regime.resolve_current_regime",
        lambda as_of_date=None: SimpleNamespace(dominant_regime="Recovery"),
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.data_provider.DjangoPulseDataProvider",
        FakeProvider,
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.repositories.PulseRepository",
        FakeRepository,
    )

    snapshot = CalculatePulseUseCase().execute(as_of_date=date(2026, 4, 20))

    assert snapshot is not None
    assert captured["provider_date"] == date(2026, 4, 20)
    assert captured["saved_snapshot"].observed_at == date(2026, 4, 20)
    assert captured["sync_request"].end_date == date(2026, 4, 20)
    assert captured["sync_request"].indicators == list(PULSE_MACRO_SYNC_INDICATORS)
