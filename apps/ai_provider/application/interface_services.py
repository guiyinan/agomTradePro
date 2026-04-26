"""Application helpers consumed by ai_provider interface adapters."""

from __future__ import annotations

from apps.ai_provider.application.repository_provider import get_ai_provider_repository


def get_masked_provider_api_key(provider) -> str:
    """Return a masked API key string for admin display."""

    api_key = get_ai_provider_repository().get_api_key(provider)
    if api_key:
        return f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"
    return "****"
