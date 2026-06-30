"""Infrastructure read models for data-center diagnostics."""

from __future__ import annotations

from datetime import date

from apps.data_center.infrastructure.models import MacroFactModel, ProviderConfigModel


class DataCenterDiagnosticRepository:
    """Read data-center summary counts for operational diagnostics."""

    def get_summary(self) -> dict[str, int]:
        """Return macro fact and provider configuration counts."""

        return {
            "macro_fact_count": MacroFactModel.objects.count(),
            "provider_config_count": ProviderConfigModel.objects.count(),
            "active_provider_config_count": ProviderConfigModel.objects.filter(
                is_active=True
            ).count(),
        }

    def macro_fact_exists_on_or_before(self, reporting_period: date) -> bool:
        """Return whether a macro fact exists on or before the reporting period."""

        return bool(
            MacroFactModel.objects.filter(reporting_period__lte=reporting_period).exists()
        )
