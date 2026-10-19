"""Fixtures for controlled M5 live-server journeys."""

from tests.playwright.tests.uat.m5_calendar_fixture import m5_synthetic_calendar_transport
from tests.playwright.tests.uat.universe_config_fixture import m5_synthetic_universe_config

__all__ = ["m5_synthetic_calendar_transport", "m5_synthetic_universe_config"]
