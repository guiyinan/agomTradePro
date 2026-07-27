"""Process-wide owner for the canonical configured provider registry."""

from __future__ import annotations

import logging

from apps.data_center.composition import get_provider_config_repository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

_global_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Return the lazily built process-wide provider registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = _build_registry()
    return _global_registry


def refresh_registry() -> ProviderRegistry:
    """Replace the registry only after current active providers build successfully."""

    global _global_registry
    previous = _global_registry
    try:
        candidate = ProviderRegistry.from_repository(get_provider_config_repository())
    except Exception as exc:
        logger.warning(
            "Failed to refresh Data Center provider registry: %s",
            type(exc).__name__,
        )
        if previous is None:
            previous = ProviderRegistry()
        _global_registry = previous
        return previous
    _global_registry = candidate
    return _global_registry


def reset_registry() -> None:
    """Reset the process-wide provider registry for tests."""
    global _global_registry
    _global_registry = None


def _build_registry() -> ProviderRegistry:
    """Build the canonical registry without failing application startup."""
    try:
        return ProviderRegistry.from_repository(get_provider_config_repository())
    except Exception as exc:
        logger.warning(
            "Failed to build Data Center provider registry: %s",
            type(exc).__name__,
        )
        return ProviderRegistry()
