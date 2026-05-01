"""Query helpers for AI provider metadata consumed by other apps."""

from __future__ import annotations

from typing import Any

from apps.ai_provider.application.repository_provider import get_ai_provider_repository


def list_active_provider_summaries() -> list[dict[str, Any]]:
    """Return active providers formatted for prompt selector UIs."""

    providers = get_ai_provider_repository().get_active_providers()
    return [
        {
            "name": provider.name,
            "provider_type": provider.provider_type,
            "default_model": provider.default_model,
            "is_active": provider.is_active,
            "priority": provider.priority,
            "display_label": f"{provider.name} ({provider.default_model})",
        }
        for provider in providers
    ]


def list_supported_models(provider_name: str | None = None) -> list[str]:
    """Return models for the requested provider name/type or all active providers."""

    provider_repo = get_ai_provider_repository()
    normalized_name = (provider_name or "").strip()

    if normalized_name:
        provider = provider_repo.get_by_name(normalized_name)
        if provider:
            extra = provider.extra_config or {}
            models = extra.get("supported_models")
            if models:
                return list(models)
            if provider.default_model:
                return [provider.default_model]
            return []

        providers = provider_repo.get_by_type(normalized_name)
        if providers:
            return list(
                dict.fromkeys(
                    provider.default_model for provider in providers if provider.default_model
                )
            )

    active_providers = provider_repo.get_active_providers()
    return list(
        dict.fromkeys(
            provider.default_model for provider in active_providers if provider.default_model
        )
    )


def get_primary_system_provider_payload() -> dict[str, Any] | None:
    """Return the first active configured system provider with a usable API key."""

    provider_repo = get_ai_provider_repository()
    provider = next(iter(provider_repo.get_active_configured_system_providers()), None)
    if provider is None:
        return None

    api_key = provider_repo.get_api_key(provider)
    if not api_key:
        return None

    return {
        "name": provider.name,
        "base_url": provider.base_url,
        "provider_type": provider.provider_type,
        "default_model": provider.default_model,
        "api_key": api_key,
    }
