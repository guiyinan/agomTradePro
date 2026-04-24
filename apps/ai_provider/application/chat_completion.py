"""Application helpers for AI chat completion."""

from __future__ import annotations

import inspect
from typing import Any

from apps.ai_provider.infrastructure.client_factory import AIClientFactory


def _resolve_ai_client(
    *,
    factory: AIClientFactory,
    provider_ref: Any | None,
    user: Any | None,
) -> Any:
    """Call `get_client` with only the parameters the injected factory accepts."""
    get_client = factory.get_client
    try:
        parameters = inspect.signature(get_client).parameters
    except (TypeError, ValueError):
        parameters = {}

    kwargs: dict[str, Any] = {}
    if "provider_ref" in parameters:
        kwargs["provider_ref"] = provider_ref
    if "user" in parameters:
        kwargs["user"] = user

    if kwargs:
        return get_client(**kwargs)
    return get_client()


def generate_chat_completion(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 500,
    user: Any | None = None,
    provider_ref: Any | None = None,
    factory_class: type[AIClientFactory] = AIClientFactory,
) -> dict[str, Any]:
    """Generate a chat completion through the configured AI provider."""
    ai_client = _resolve_ai_client(
        factory=factory_class(),
        provider_ref=provider_ref,
        user=user,
    )
    request_payload: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model:
        request_payload["model"] = model
    return ai_client.chat_completion(**request_payload)
