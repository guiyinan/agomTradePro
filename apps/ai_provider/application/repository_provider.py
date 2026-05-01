"""Repository providers for ai_provider application consumers."""

from __future__ import annotations

from typing import Any

from apps.ai_provider.infrastructure.adapters import AIFailoverHelper, OpenAICompatibleAdapter
from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.ai_provider.infrastructure.providers import (
    AIProviderRepository,
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)


def get_ai_client_factory() -> AIClientFactory:
    """Return the default AI client factory."""

    return AIClientFactory()


def get_ai_provider_repository() -> AIProviderRepository:
    """Return the default AI provider repository."""

    return AIProviderRepository()


def get_ai_usage_repository() -> AIUsageRepository:
    """Return the default AI usage repository."""

    return AIUsageRepository()


def get_ai_user_fallback_quota_repository() -> AIUserFallbackQuotaRepository:
    """Return the default fallback quota repository."""

    return AIUserFallbackQuotaRepository()


def build_openai_compatible_adapter(
    *,
    base_url: str,
    api_key: str,
    default_model: str,
    api_mode: str | None = None,
    fallback_enabled: bool | None = None,
) -> OpenAICompatibleAdapter:
    """Build an OpenAI-compatible adapter for application consumers."""

    return OpenAICompatibleAdapter(
        base_url=base_url,
        api_key=api_key,
        default_model=default_model,
        api_mode=api_mode,
        fallback_enabled=fallback_enabled,
    )


def list_active_system_provider_payloads() -> list[dict[str, Any]]:
    """Return usable active system providers as failover-ready payloads."""

    provider_repo = get_ai_provider_repository()
    payloads: list[dict[str, Any]] = []

    for provider in provider_repo.get_active_configured_system_providers():
        extra_config = provider.extra_config if isinstance(provider.extra_config, dict) else {}
        api_key = provider_repo.get_api_key(provider)
        if not api_key:
            continue
        payloads.append(
            {
                "name": provider.name,
                "base_url": provider.base_url,
                "api_key": api_key,
                "default_model": provider.default_model,
                "priority": provider.priority,
                "api_mode": extra_config.get("api_mode"),
                "fallback_enabled": extra_config.get("fallback_enabled"),
            }
        )

    return payloads


def build_ai_failover_helper(providers: list[dict[str, Any]]) -> AIFailoverHelper:
    """Build the default AI failover helper for application consumers."""

    return AIFailoverHelper(providers)
