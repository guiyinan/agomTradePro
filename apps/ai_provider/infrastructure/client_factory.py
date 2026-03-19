"""
AI client factory shared by prompt, terminal, and other modules.
"""

import logging
from typing import Any

from .adapters import AIFailoverHelper, OpenAICompatibleAdapter
from .repositories import AIProviderRepository


logger = logging.getLogger(__name__)


class AIClientFactory:
    """Build AI clients from provider configuration."""

    def __init__(self, provider_repo: AIProviderRepository | None = None):
        self._provider_repo = provider_repo or AIProviderRepository()
        self._clients: dict[tuple[str, Any], Any] = {}

    def get_client(self, provider_ref=None):
        """Return a single-provider client or a failover client."""
        if provider_ref is not None and provider_ref != "":
            provider = self._get_provider(provider_ref)
            if provider:
                cache_key = ("provider", provider.id)
                if cache_key not in self._clients:
                    self._clients[cache_key] = self._build_adapter(provider)
                return self._clients[cache_key]
            logger.warning("Provider '%s' not found, falling back to failover", provider_ref)

        cache_key = ("failover", "active")
        if cache_key in self._clients:
            return self._clients[cache_key]

        providers = self._provider_repo.get_active_providers()
        if not providers:
            logger.error("No active AI providers configured")
            return _NullAIClient()

        provider_dicts = []
        for provider in providers:
            provider_dicts.append({
                "name": provider.name,
                "base_url": provider.base_url,
                "api_key_decrypted": self._provider_repo.get_api_key(provider),
                "default_model": provider.default_model,
                "api_mode": getattr(provider, 'api_mode', None),
                "fallback_enabled": getattr(provider, 'fallback_enabled', None),
            })

        self._clients[cache_key] = _FailoverAIClient(AIFailoverHelper(provider_dicts))
        return self._clients[cache_key]

    def _get_provider(self, provider_ref):
        """Resolve provider by numeric id or configured name."""
        if isinstance(provider_ref, int):
            return self._provider_repo.get_by_id(provider_ref)

        if isinstance(provider_ref, str):
            text = provider_ref.strip()
            if text.isdigit():
                return self._provider_repo.get_by_id(int(text))
            return self._provider_repo.get_by_name(text)

        return None

    def _build_adapter(self, provider):
        api_key = self._provider_repo.get_api_key(provider)
        extra_config = provider.extra_config if isinstance(provider.extra_config, dict) else {}
        return OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
            default_model=provider.default_model,
            api_mode=getattr(provider, 'api_mode', None) or extra_config.get("api_mode"),
            fallback_enabled=getattr(provider, 'fallback_enabled', None),
        )


class _FailoverAIClient:
    """Adapter wrapper exposing the chat_completion interface."""

    def __init__(self, failover_helper):
        self._helper = failover_helper

    def chat_completion(
        self, messages, model=None, temperature=0.7, max_tokens=None,
        tools=None, tool_choice=None, response_format=None,
    ):
        return self._helper.chat_completion_with_failover(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )


class _NullAIClient:
    """Fallback client returned when no providers are configured."""

    def chat_completion(
        self, messages, model=None, temperature=0.7, max_tokens=None,
        tools=None, tool_choice=None, response_format=None,
    ):
        return {
            "status": "error",
            "content": "",
            "provider_used": "",
            "model": model or "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
            "error_message": "没有可用的AI提供商，请先在 ai_provider 模块配置",
            "tool_calls": None,
        }
