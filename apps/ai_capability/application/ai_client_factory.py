"""Typed AI client factory boundary for capability fallback routing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from apps.ai_provider.application.repository_provider import get_ai_client_factory


class AIChatClientProtocol(Protocol):
    """Narrow chat client contract consumed by capability fallback routing."""

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Generate one non-streaming chat completion."""


class AIClientFactoryProtocol(Protocol):
    """Narrow provider factory contract consumed by capability routing."""

    def get_client(
        self,
        provider_ref: str | None = None,
        user: object | None = None,
    ) -> AIChatClientProtocol:
        """Return a user-scoped chat client."""


def _create_ai_client_factory() -> AIClientFactoryProtocol:
    """Build the default typed AI client factory."""

    return cast(AIClientFactoryProtocol, get_ai_client_factory())


AIClientFactory: Callable[[], AIClientFactoryProtocol] = _create_ai_client_factory

__all__ = ["AIClientFactory"]
