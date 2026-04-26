"""Current regime integration bridge."""

from datetime import date


def resolve_current_regime_for_pulse(*, as_of_date: date):
    """Resolve the current regime through the owning regime module."""
    from apps.regime.application.current_regime import resolve_current_regime

    return resolve_current_regime(as_of_date=as_of_date)
