from datetime import date
from types import SimpleNamespace

from core.integration.current_regime import resolve_current_regime_for_pulse


def test_resolve_current_regime_for_pulse_uses_regime_module(monkeypatch):
    expected = SimpleNamespace(dominant_regime="Recovery")

    def _fake_resolver(*, as_of_date):
        assert as_of_date == date(2026, 4, 26)
        return expected

    monkeypatch.setattr(
        "apps.regime.application.current_regime.resolve_current_regime",
        _fake_resolver,
    )

    result = resolve_current_regime_for_pulse(as_of_date=date(2026, 4, 26))

    assert result is expected
