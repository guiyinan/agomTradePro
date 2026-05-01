"""Pulse repository providers for application consumers."""

from __future__ import annotations

from apps.pulse.infrastructure.providers import (
    NavigatorAssetConfigRepository,
    build_navigator_asset_config_repository,
    build_pulse_data_provider,
    build_pulse_repository,
)


def get_pulse_repository():
    """Return the default pulse repository."""

    return build_pulse_repository()


def get_pulse_data_provider():
    """Return the default pulse data provider."""

    return build_pulse_data_provider()


def get_navigator_asset_config_repository() -> NavigatorAssetConfigRepository:
    """Return the navigator asset-config repository used by regime navigation."""

    return build_navigator_asset_config_repository()
