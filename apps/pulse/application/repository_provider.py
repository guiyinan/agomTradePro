"""Pulse repository providers for application consumers."""

from __future__ import annotations

from typing import Any

from apps.pulse.infrastructure.providers import get_navigator_asset_config_repository


def get_pulse_repository():
    """Return the default pulse repository."""

    from apps.pulse.infrastructure.providers import PulseRepository

    return PulseRepository()


def get_pulse_data_provider():
    """Return the default pulse data provider."""

    from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider

    return DjangoPulseDataProvider()
