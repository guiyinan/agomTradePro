from datetime import date

from core.integration.pulse_refresh import refresh_pulse_snapshot


class _FakeCalculatePulseUseCase:
    def execute(self, *, as_of_date):
        return {"as_of_date": as_of_date.isoformat()}


def test_refresh_pulse_snapshot_uses_pulse_module(monkeypatch):
    monkeypatch.setattr(
        "apps.pulse.application.use_cases.CalculatePulseUseCase",
        _FakeCalculatePulseUseCase,
    )

    assert refresh_pulse_snapshot(target_date=date(2026, 4, 26)) == {
        "as_of_date": "2026-04-26"
    }
