"""Register Pulse runtime access for Data Center."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.application.business_runtime_gateway import register_pulse_refresher

from . import use_cases


def _refresh_pulse(*, target_date: date) -> Any:
    return use_cases.CalculatePulseUseCase().execute(as_of_date=target_date)


def register_pulse_data_center_runtime() -> None:
    """Register the Pulse snapshot refresher."""

    register_pulse_refresher(_refresh_pulse)


__all__ = ["register_pulse_data_center_runtime"]
