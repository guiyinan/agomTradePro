"""Bridge helpers for simulated-trading position access."""

from __future__ import annotations

from apps.simulated_trading.application.repository_provider import get_simulated_position_repository
from apps.simulated_trading.infrastructure.models import PositionModel


def get_simulated_position_price_updater():
    """Return the default simulated position repository for price updates."""

    return get_simulated_position_repository()


def list_held_simulated_asset_codes() -> list[str]:
    """Return distinct asset codes held in simulated-trading positions."""

    positions = PositionModel._default_manager.filter(
        quantity__gt=0,
    ).values_list("asset_code", flat=True).distinct()
    return list(positions)
