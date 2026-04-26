"""Application-facing hedge integration service."""

from __future__ import annotations

from apps.hedge.application.repository_provider import (
    HedgeIntegrationService as _HedgeIntegrationService,
)


class HedgeIntegrationService(_HedgeIntegrationService):
    """Expose hedge integration through the application layer."""
