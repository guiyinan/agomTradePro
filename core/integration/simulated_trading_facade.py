"""Simulated trading facade bridge."""


def get_simulated_trading_facade_bridge():
    """Return the simulated trading facade from its owning module."""
    from apps.simulated_trading.application.facade import (
        get_simulated_trading_facade,
    )

    return get_simulated_trading_facade()
