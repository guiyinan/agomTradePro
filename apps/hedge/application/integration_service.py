"""Application-facing hedge integration service."""

from __future__ import annotations

from apps.hedge.infrastructure.services import HedgeIntegrationService as _HedgeIntegrationService


class HedgeIntegrationService(_HedgeIntegrationService):
    """Expose hedge integration through the application layer."""
