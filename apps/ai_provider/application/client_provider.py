"""Application-side helpers for resolving AI client factories."""

from __future__ import annotations

from apps.ai_provider.infrastructure.client_factory import AIClientFactory


def get_ai_client_factory() -> AIClientFactory:
    """Return the default AI client factory."""

    return AIClientFactory()
