"""Rotation repository providers for application consumers."""

from apps.rotation.infrastructure.providers import RotationInterfaceRepository
from apps.rotation.infrastructure.services import RotationIntegrationService


def get_rotation_interface_repository() -> RotationInterfaceRepository:
    """Return the default rotation interface repository."""

    return RotationInterfaceRepository()


def get_rotation_integration_service() -> RotationIntegrationService:
    """Return the default rotation integration service."""

    return RotationIntegrationService()
