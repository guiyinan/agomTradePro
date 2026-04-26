"""Pulse refresh bridge."""

from datetime import date


def refresh_pulse_snapshot(*, target_date: date):
    """Refresh the latest pulse snapshot through the owning pulse module."""
    from apps.pulse.application.use_cases import CalculatePulseUseCase

    return CalculatePulseUseCase().execute(as_of_date=target_date)
