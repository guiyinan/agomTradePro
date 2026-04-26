"""Policy repository provider for application consumers."""

from __future__ import annotations

from apps.policy.infrastructure.adapters.ai_policy_classifier import (
    create_ai_policy_classifier,
)
from apps.policy.application.interface_services import (
    PolicyAdminInterfaceService,
    PolicyWorkbenchInterfaceService,
)
from apps.policy.infrastructure.interface_repositories import (
    PolicyAdminInterfaceRepository,
    PolicyWorkbenchInterfaceRepository,
)
from apps.policy.infrastructure.notification_service import NotificationServiceFactory
from apps.policy.infrastructure.providers import (
    HedgePositionRepository,
    RSSRepository,
    WorkbenchRepository,
    get_policy_repository,
)


def get_current_policy_repository():
    """Return the configured policy repository."""

    return get_policy_repository()


def get_rss_repository() -> RSSRepository:
    """Return the policy RSS repository."""

    return RSSRepository()


def get_workbench_repository() -> WorkbenchRepository:
    """Return the policy workbench repository."""

    return WorkbenchRepository()


def get_policy_admin_interface_service() -> PolicyAdminInterfaceService:
    """Return the policy admin interface service."""

    return PolicyAdminInterfaceService(admin_repo=PolicyAdminInterfaceRepository())


def get_policy_workbench_interface_service() -> PolicyWorkbenchInterfaceService:
    """Return the policy workbench interface service."""

    return PolicyWorkbenchInterfaceService(
        workbench_repo=get_workbench_repository(),
        interface_repo=PolicyWorkbenchInterfaceRepository(),
    )


def get_hedge_position_repository() -> HedgePositionRepository:
    """Return the hedge position repository."""

    return HedgePositionRepository()


def get_policy_notification_service():
    """Return the alert notification service."""

    return NotificationServiceFactory.get_alert_service()


def get_ai_policy_classifier():
    """Return the configured AI policy classifier, if available."""

    return create_ai_policy_classifier()
