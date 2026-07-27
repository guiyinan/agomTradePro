from datetime import date
from types import SimpleNamespace

import pytest

from apps.pulse.application.use_cases import (
    PULSE_MACRO_SYNC_INDICATORS,
    CalculatePulseUseCase,
    GetLatestPulseUseCase,
    resolve_current_regime_for_pulse,
)
from apps.pulse.domain.entities import PulseIndicatorReading


@pytest.mark.django_db
def test_calculate_pulse_refreshes_macro_inputs_before_calculation(monkeypatch):
    captured: dict[str, object] = {}

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
        "apps.pulse.application.use_cases.refresh_pulse_macro_inputs",
        lambda **kwargs: captured.update({"repair_kwargs": kwargs}),
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.resolve_current_regime_for_pulse",
        lambda as_of_date=None: SimpleNamespace(dominant_regime="Recovery"),
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.providers.DjangoPulseDataProvider",
        FakeProvider,
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.providers.PulseRepository",
        FakeRepository,
    )

    snapshot = CalculatePulseUseCase().execute(as_of_date=date(2026, 4, 20))

    assert snapshot is not None
    assert captured["provider_date"] == date(2026, 4, 20)
    assert captured["saved_snapshot"].observed_at == date(2026, 4, 20)
    assert captured["repair_kwargs"]["target_date"] == date(2026, 4, 20)
    assert captured["repair_kwargs"]["macro_indicator_codes"] == PULSE_MACRO_SYNC_INDICATORS
    assert captured["repair_kwargs"]["asset_codes"] == ("000300.SH",)


def test_resolve_current_regime_for_pulse_uses_regime_module(monkeypatch):
    expected = SimpleNamespace(dominant_regime="Recovery")

    def _fake_resolver(*, as_of_date):
        assert as_of_date == date(2026, 4, 26)
        return expected

    monkeypatch.setattr(
        "apps.pulse.application.use_cases.resolve_current_regime",
        _fake_resolver,
    )

    result = resolve_current_regime_for_pulse(as_of_date=date(2026, 4, 26))

    assert result is expected


@pytest.mark.parametrize(
    ("field_name", "kwargs"),
    [
        ("require_reliable", {"require_reliable": 1}),
        ("refresh_if_stale", {"refresh_if_stale": "yes"}),
        ("max_age_days", {"max_age_days": True}),
        ("max_age_days", {"max_age_days": -1}),
    ],
)
def test_get_latest_pulse_validates_controls_before_repository_access(
    monkeypatch,
    field_name,
    kwargs,
):
    """Malformed reliability controls must not touch persisted Pulse state."""

    repository_calls = 0

    def get_repository():
        nonlocal repository_calls
        repository_calls += 1
        return object()

    monkeypatch.setattr(
        "apps.pulse.application.use_cases.get_pulse_repository",
        get_repository,
    )

    with pytest.raises(ValueError, match=field_name):
        GetLatestPulseUseCase().execute(**kwargs)

    assert repository_calls == 0


def test_calculate_pulse_does_not_log_provider_exception_text(monkeypatch, caplog):
    """Dynamic provider failures return unavailable without leaking credentials."""

    class FailingProvider:
        def get_all_readings(self, as_of_date):
            raise RuntimeError("postgresql://user:secret@database")

    monkeypatch.setattr(
        "apps.pulse.application.use_cases.resolve_current_regime_for_pulse",
        lambda as_of_date=None: SimpleNamespace(dominant_regime="Recovery"),
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases._refresh_macro_inputs_for_pulse",
        lambda target_date: None,
    )
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.get_pulse_data_provider",
        lambda: FailingProvider(),
    )

    with caplog.at_level("ERROR"):
        snapshot = CalculatePulseUseCase().execute(as_of_date=date(2026, 4, 20))

    assert snapshot is None
    assert "secret" not in caplog.text
    assert any(
        getattr(record, "exception_type", None) == "RuntimeError" for record in caplog.records
    )
