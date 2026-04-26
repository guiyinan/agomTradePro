"""Application helpers consumed by ai_provider interface adapters."""

from __future__ import annotations

from apps.ai_provider.infrastructure.providers import AIProviderRepository


def get_masked_provider_api_key(provider) -> str:
    """Return a masked API key string for admin display."""

    api_key = AIProviderRepository().get_api_key(provider)
    if api_key:
        return f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"
    return "****"
