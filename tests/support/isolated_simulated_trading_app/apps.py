"""Test-only AppConfig for the physical simulated account source."""

from django.apps import AppConfig


class IsolatedSimulatedTradingConfig(AppConfig):
    """Register only the physical account row model required by Account."""

    name = "tests.support.isolated_simulated_trading_app"
    label = "simulated_trading"
