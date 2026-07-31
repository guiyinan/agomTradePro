"""Initialize database-owned policy sentiment gate defaults."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.policy.infrastructure.models import SentimentGateConfig


class Command(BaseCommand):
    """Create missing gate rows without overriding operator configuration."""

    help = "Initialize missing policy sentiment-gate configurations idempotently."

    def handle(self, *args: object, **options: Any) -> None:
        """Create one row for every model-owned canonical asset class."""

        del args, options
        created_count = 0
        existing_count = 0
        with transaction.atomic():
            for asset_class, _label in SentimentGateConfig.ASSET_CLASS_CHOICES:
                _config, created = SentimentGateConfig._default_manager.get_or_create(
                    asset_class=asset_class
                )
                if created:
                    created_count += 1
                else:
                    existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Policy sentiment-gate defaults ready: "
                f"created={created_count}, existing={existing_count}"
            )
        )
