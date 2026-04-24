"""AI-provider summaries used by the system config center."""

from __future__ import annotations

from typing import Any, Protocol


class AIProviderConfigSummaryRepository(Protocol):
    """Read model contract for AI-provider config summaries."""

    def get_provider_summary(self) -> dict[str, Any]:
        """Return AI-provider configuration summary."""


class AIProviderConfigSummaryService:
    """Application service for config-center AI-provider summaries."""

    def __init__(self, repository: AIProviderConfigSummaryRepository):
        self.repository = repository

    def get_provider_summary(self, user: Any) -> dict[str, Any]:
        """Return AI-provider configuration summary."""

        return self.repository.get_provider_summary()


_config_summary_repository: AIProviderConfigSummaryRepository | None = None


def configure_ai_provider_config_summary_repository(
    repository: AIProviderConfigSummaryRepository,
) -> None:
    """Register the AI-provider config-summary repository."""

    global _config_summary_repository
    _config_summary_repository = repository


def get_ai_provider_config_summary_service() -> AIProviderConfigSummaryService:
    """Return the configured AI-provider config-summary service."""

    if _config_summary_repository is None:
        raise RuntimeError("AI-provider config summary repository is not configured")
    return AIProviderConfigSummaryService(_config_summary_repository)
