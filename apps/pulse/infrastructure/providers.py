"""Repository provider re-exports for application composition roots."""

from .data_provider import DjangoPulseDataProvider
from .repositories import *  # noqa: F401,F403
from .repositories import NavigatorAssetConfigRepository, PulseRepository


def build_pulse_repository() -> PulseRepository:
    """Build the default pulse repository."""

    return PulseRepository()


def build_pulse_data_provider() -> DjangoPulseDataProvider:
    """Build the default pulse data provider."""

    return DjangoPulseDataProvider()


def build_navigator_asset_config_repository() -> NavigatorAssetConfigRepository:
    """Build the repository used by regime navigation asset configs."""

    return NavigatorAssetConfigRepository()
