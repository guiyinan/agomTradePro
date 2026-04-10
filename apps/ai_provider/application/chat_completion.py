"""Application helpers for AI chat completion."""

from __future__ import annotations

from typing import Any

from apps.ai_provider.infrastructure.client_factory import AIClientFactory


def generate_chat_completion(
    *,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 500,
    user: Any | None = None,
    provider_ref: Any | None = None,
    factory_class: type[AIClientFactory] = AIClientFactory,
) -> dict[str, Any]:
    """Generate a chat completion through the configured AI provider."""
    ai_client = factory_class().get_client(provider_ref, user=user)
    return ai_client.chat_completion(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
