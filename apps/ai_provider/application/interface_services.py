"""Application helpers consumed by ai_provider interface adapters."""

from __future__ import annotations

from apps.ai_provider.application.repository_provider import get_ai_provider_repository
from apps.ai_provider.models import AIProviderConfig


def get_masked_provider_api_key(provider: AIProviderConfig) -> str:
    """Return a fixed mask without disclosing a credential fingerprint."""

    api_key = get_ai_provider_repository().get_api_key(provider)
    return "****" if api_key else "Not configured"
