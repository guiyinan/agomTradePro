"""Policy repository provider for application consumers."""

from __future__ import annotations

from apps.policy.infrastructure.adapters import FeedparserAdapter, create_content_extractor
from apps.policy.infrastructure.adapters.ai_policy_classifier import (
    create_ai_policy_classifier,
)
from apps.policy.infrastructure.adapters.content_extractor import ContentExtractorError
from apps.policy.infrastructure.interface_repositories import (
    PolicyAdminInterfaceRepository,
    PolicyPageInterfaceRepository,
    PolicyRssApiInterfaceRepository,
    PolicyWorkbenchInterfaceRepository,
)
from apps.policy.infrastructure.notification_service import NotificationServiceFactory
from apps.policy.infrastructure.providers import (
    DjangoPolicyRepository,
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


__all__ = [
    "ContentExtractorError",
    "DjangoPolicyRepository",
    "FeedparserAdapter",
    "HedgePositionRepository",
    "NotificationServiceFactory",
    "PolicyAdminInterfaceRepository",
    "PolicyAdminInterfaceService",  # noqa: F822
    "PolicyWorkbenchInterfaceRepository",
    "PolicyWorkbenchInterfaceService",  # noqa: F822
    "PolicyRssApiInterfaceRepository",
    "PolicyRssApiInterfaceService",  # noqa: F822
    "RSSRepository",
    "WorkbenchRepository",
    "create_ai_policy_classifier",
    "create_content_extractor",
    "get_current_policy_repository",
    "get_policy_page_interface_service",
    "get_policy_rss_api_interface_service",
    "get_policy_workbench_interface_service",
    "get_rss_repository",
    "get_workbench_repository",
]


def get_policy_admin_interface_service():
    """Return the policy admin interface service."""

    from apps.policy.application.interface_services import PolicyAdminInterfaceService

    return PolicyAdminInterfaceService(admin_repo=PolicyAdminInterfaceRepository())


def get_policy_workbench_interface_service():
    """Return the policy workbench interface service."""

    from apps.policy.application.interface_services import PolicyWorkbenchInterfaceService

    return PolicyWorkbenchInterfaceService(
        workbench_repo=get_workbench_repository(),
        interface_repo=PolicyWorkbenchInterfaceRepository(),
    )


def get_policy_page_interface_service():
    """Return the policy page interface service."""

    from apps.policy.application.interface_services import PolicyPageInterfaceService

    return PolicyPageInterfaceService(page_repo=PolicyPageInterfaceRepository())


def get_policy_rss_api_interface_service():
    """Return the policy RSS API interface service."""

    from apps.policy.application.interface_services import PolicyRssApiInterfaceService

    return PolicyRssApiInterfaceService(api_repo=PolicyRssApiInterfaceRepository())


def get_hedge_position_repository() -> HedgePositionRepository:
    """Return the hedge position repository."""

    return HedgePositionRepository()


def get_policy_notification_service():
    """Return the alert notification service."""

    return NotificationServiceFactory.get_alert_service()


def get_ai_policy_classifier():
    """Return the configured AI policy classifier, if available."""

    return create_ai_policy_classifier()
