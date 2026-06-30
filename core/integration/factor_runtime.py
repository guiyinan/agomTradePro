"""Bridge helpers for cross-app factor runtime access."""

from __future__ import annotations


def build_factor_integration_service():
    """Return the owning factor integration service."""

    from apps.factor.application.repository_provider import get_factor_integration_service

    return get_factor_integration_service()
