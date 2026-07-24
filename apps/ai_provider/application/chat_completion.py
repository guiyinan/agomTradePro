"""Application helpers for AI chat completion."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from apps.ai_provider.application.repository_provider import (
    AIClientFactory as AIClientFactory,
)
from apps.ai_provider.application.repository_provider import (
    get_ai_client_factory,
)


class ChatCompletionClientProtocol(Protocol):
    """Client surface used by the application chat helper."""

    def chat_completion(self, **kwargs: Any) -> dict[str, Any]: ...


class AIClientFactoryProtocol(Protocol):
    """Factory surface used by the application chat helper."""

    def get_client(
        self,
        provider_ref: Any | None = None,
        user: Any | None = None,
    ) -> ChatCompletionClientProtocol: ...


def _resolve_ai_client(
    *,
    factory: AIClientFactoryProtocol,
    provider_ref: Any | None,
    user: Any | None,
) -> ChatCompletionClientProtocol:
    """Call `get_client` with only the parameters the injected factory accepts."""
    get_client = factory.get_client
    try:
        parameters: Mapping[str, inspect.Parameter] = inspect.signature(get_client).parameters
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
    factory_builder: Callable[[], AIClientFactoryProtocol] = get_ai_client_factory,
) -> dict[str, Any]:
    """Generate a chat completion through the configured AI provider."""
    ai_client = _resolve_ai_client(
        factory=factory_builder(),
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
