"""Bridge helpers for cross-app factor runtime access."""

from __future__ import annotations


def build_factor_integration_service():
    """Return the owning factor integration service."""

    from apps.factor.infrastructure.services import FactorIntegrationService

    return FactorIntegrationService()
