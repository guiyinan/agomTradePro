"""Rotation app configuration"""

import logging
from django.apps import AppConfig


class RotationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rotation"
    verbose_name = "资产轮动"

    def ready(self):
        """Register rotation-owned asset-analysis integrations."""
        logger = logging.getLogger(__name__)
        try:
            from apps.rotation.application.repository_provider import (
                resolve_rotation_asset_names,
            )
            from shared.infrastructure.asset_analysis_registry import (
                get_asset_analysis_market_registry,
            )

            registry = get_asset_analysis_market_registry()
            registry.register_name_resolver("rotation", resolve_rotation_asset_names)
        except Exception as exc:
            logger.error("Failed to register rotation market providers: %s", exc)
