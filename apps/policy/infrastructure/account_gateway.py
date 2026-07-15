"""Register Policy cold-start readiness for Account orchestration."""

from __future__ import annotations

from django.apps import apps as django_apps

from apps.policy.management.commands.init_authoritative_rss_sources import (
    AUTHORITATIVE_RSS_SOURCES,
)
from core.integration.policy_readiness_registry import (
    register_policy_readiness_checker,
)


def _authoritative_rss_sources_ready() -> bool:
    rsshub_config_model = django_apps.get_model("policy", "RSSHubGlobalConfig")
    rss_source_model = django_apps.get_model("policy", "RSSSourceConfigModel")
    config = rsshub_config_model._default_manager.filter(singleton_id=1).first()
    if config is None or not config.enabled:
        return False

    expected_routes = {source.route_path for source in AUTHORITATIVE_RSS_SOURCES}
    active_routes = set(
        rss_source_model._default_manager.filter(
            is_active=True,
            rsshub_enabled=True,
            rsshub_route_path__in=expected_routes,
        ).values_list("rsshub_route_path", flat=True)
    )
    return expected_routes.issubset(active_routes)


def register_policy_account_gateway() -> None:
    """Register the Policy-owned authoritative RSS readiness checker."""

    register_policy_readiness_checker(_authoritative_rss_sources_ready)


__all__ = ["register_policy_account_gateway"]
