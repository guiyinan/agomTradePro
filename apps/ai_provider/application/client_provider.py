"""Application-side helpers for resolving AI client factories."""

from __future__ import annotations

from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter
from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.ai_provider.infrastructure.providers import AIProviderRepository


def get_ai_client_factory() -> AIClientFactory:
    """Return the default AI client factory."""

    return AIClientFactory()


def get_ai_provider_repository() -> AIProviderRepository:
    """Return the default AI provider repository."""

    return AIProviderRepository()


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
