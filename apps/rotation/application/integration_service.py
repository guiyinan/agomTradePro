"""Application-facing rotation integration service."""

from __future__ import annotations

from apps.rotation.application.repository_provider import (
    RotationIntegrationService as _RotationIntegrationService,
)


class RotationIntegrationService(_RotationIntegrationService):
    """Expose rotation integration through the application layer."""
