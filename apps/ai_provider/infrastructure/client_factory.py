"""
AI client factory shared by prompt, terminal, and other modules.
"""

import logging
from typing import Any

from django.contrib.auth import get_user_model

from ..domain.services import AICostCalculator
from .adapters import OpenAICompatibleAdapter
from .repositories import (
    AIProviderRepository,
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)

logger = logging.getLogger(__name__)


class AIClientFactory:
    """Build user-aware AI clients from provider configuration."""

    def __init__(
        self,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository(usage_repo=self._usage_repo)
        self._clients: dict[tuple[str, Any], Any] = {}

    def get_client(self, provider_ref=None, user=None):
        """Return a user-aware AI client."""
        resolved_user = _resolve_user(user)
        cache_key = ("scoped", provider_ref, getattr(resolved_user, "id", None))
        if cache_key not in self._clients:
            self._clients[cache_key] = _ScopedAIClient(
                provider_ref=provider_ref,
                user=resolved_user,
                provider_repo=self._provider_repo,
                usage_repo=self._usage_repo,
                quota_repo=self._quota_repo,
                adapter_builder=self._build_adapter,
            )
        return self._clients[cache_key]

    def _build_adapter(self, provider):
        api_key = self._provider_repo.get_api_key(provider)
        return OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
            default_model=provider.default_model,
            api_mode=provider.api_mode,
            fallback_enabled=provider.fallback_enabled,
        )


class _ScopedAIClient:
    """Route one chat completion through personal-first resolution."""

    def __init__(
        self,
        *,
        provider_ref,
        user,
        provider_repo: AIProviderRepository,
        usage_repo: AIUsageRepository,
        quota_repo: AIUserFallbackQuotaRepository,
        adapter_builder,
    ) -> None:
        self._provider_ref = provider_ref
        self._user = user
        self._provider_repo = provider_repo
        self._usage_repo = usage_repo
        self._quota_repo = quota_repo
        self._adapter_builder = adapter_builder
        self._adapter_cache: dict[int, Any] = {}

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._user is None:
            return self._chat_with_system_only(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
            )

        personal_candidates, system_candidates = self._resolve_candidates()

        last_error = None
        for provider in personal_candidates:
            result = self._call_provider(
                provider=provider,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                provider_scope="personal",
                quota_charged=False,
            )
            if result["status"] == "success":
                return result
            last_error = result.get("error_message") or last_error

        quota_status = self._get_fallback_quota_status()
        if system_candidates and not quota_status["allowed"]:
            return {
                "content": None,
                "model": model or "",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "finish_reason": None,
                "response_time_ms": 0,
                "status": "error",
                "error_message": quota_status["message"],
                "estimated_cost": 0.0,
                "provider_used": None,
                "provider_scope": "system_fallback",
                "quota_charged": False,
                "request_type": "chat",
                "api_mode_used": None,
                "fallback_used": False,
                "tool_calls": None,
            }

        for provider in system_candidates:
            if not self._provider_budget_allows(provider):
                continue
            result = self._call_provider(
                provider=provider,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                provider_scope="system_fallback",
                quota_charged=True,
            )
            if result["status"] == "success":
                return result
            last_error = result.get("error_message") or last_error

        return {
            "content": None,
            "model": model or "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": last_error or "No available AI providers",
            "estimated_cost": 0.0,
            "provider_used": None,
            "provider_scope": "personal" if personal_candidates else "system_fallback",
            "quota_charged": False,
            "request_type": "chat",
            "api_mode_used": None,
            "fallback_used": False,
            "tool_calls": None,
        }

    def _chat_with_system_only(self, **kwargs) -> dict[str, Any]:
        provider = self._provider_repo.get_provider_for_reference(self._provider_ref, user=None)
        if provider is not None and self._provider_repo.has_usable_api_key(provider):
            providers = [provider]
        else:
            providers = self._provider_repo.get_active_configured_system_providers()

        last_error = None
        for candidate in providers:
            if not self._provider_budget_allows(candidate):
                continue
            result = self._call_provider(
                provider=candidate,
                provider_scope="system_global",
                quota_charged=False,
                **kwargs,
            )
            if result["status"] == "success":
                return result
            last_error = result.get("error_message") or last_error

        return {
            "content": None,
            "model": kwargs.get("model") or "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": last_error or "No active AI providers configured",
            "estimated_cost": 0.0,
            "provider_used": None,
            "provider_scope": "system_global",
            "quota_charged": False,
            "request_type": "chat",
            "api_mode_used": None,
            "fallback_used": False,
            "tool_calls": None,
        }

    def _resolve_candidates(self):
        explicit = self._provider_repo.get_provider_for_reference(self._provider_ref, user=self._user)
        personal = self._provider_repo.get_active_configured_user_providers(self._user)
        system = self._provider_repo.get_active_configured_system_providers()

        if (
            explicit is not None
            and explicit.scope == "user"
            and self._provider_repo.has_usable_api_key(explicit)
        ):
            personal = _move_to_front(personal, explicit.id)
        if (
            explicit is not None
            and explicit.scope == "system"
            and self._provider_repo.has_usable_api_key(explicit)
        ):
            system = _move_to_front(system, explicit.id)
        return personal, system

    def _get_adapter(self, provider):
        if provider.id not in self._adapter_cache:
            self._adapter_cache[provider.id] = self._adapter_builder(provider)
        return self._adapter_cache[provider.id]

    def _provider_budget_allows(self, provider) -> bool:
        budget = self._usage_repo.check_budget_limits(
            provider.id,
            float(provider.daily_budget_limit) if provider.daily_budget_limit is not None else None,
            float(provider.monthly_budget_limit) if provider.monthly_budget_limit is not None else None,
        )
        return not budget["daily"]["exceeded"] and not budget["monthly"]["exceeded"]

    def _get_fallback_quota_status(self) -> dict[str, Any]:
        quota, daily_spent, monthly_spent = self._quota_repo.get_with_usage(self._user)
        if quota is None or not quota.is_active:
            return {
                "allowed": False,
                "message": "System fallback quota is not configured for this user.",
            }
        daily_limit = float(quota.daily_limit) if quota.daily_limit is not None else None
        monthly_limit = float(quota.monthly_limit) if quota.monthly_limit is not None else None
        if daily_limit is not None and daily_spent >= daily_limit:
            return {
                "allowed": False,
                "message": "System fallback quota exhausted for today.",
            }
        if monthly_limit is not None and monthly_spent >= monthly_limit:
            return {
                "allowed": False,
                "message": "System fallback quota exhausted for this month.",
            }
        return {"allowed": True, "message": "Fallback quota available."}

    def _call_provider(
        self,
        *,
        provider,
        messages,
        model,
        temperature,
        max_tokens,
        stream,
        tools,
        tool_choice,
        response_format,
        provider_scope: str,
        quota_charged: bool,
    ) -> dict[str, Any]:
        adapter = self._get_adapter(provider)
        result = adapter.chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )
        estimated_cost = result.get("estimated_cost") or AICostCalculator.calculate_cost(
            result.get("model") or model or provider.default_model,
            int(result.get("prompt_tokens", 0) or 0),
            int(result.get("completion_tokens", 0) or 0),
        )
        result["estimated_cost"] = estimated_cost
        result["provider_used"] = provider.name
        result["provider_scope"] = provider_scope
        result["quota_charged"] = quota_charged and result.get("status") == "success"

        self._usage_repo.log_usage(
            provider=provider,
            user=self._user,
            provider_scope=provider_scope,
            quota_charged=result["quota_charged"],
            model=result.get("model") or model or provider.default_model,
            prompt_tokens=int(result.get("prompt_tokens", 0) or 0),
            completion_tokens=int(result.get("completion_tokens", 0) or 0),
            total_tokens=int(result.get("total_tokens", 0) or 0),
            estimated_cost=float(estimated_cost),
            response_time_ms=int(result.get("response_time_ms", 0) or 0),
            status=result.get("status", "error"),
            request_type=result.get("request_type", "chat"),
            error_message=result.get("error_message") or "",
            request_metadata={
                "requested_provider_ref": self._provider_ref,
                "fallback_used": bool(result.get("fallback_used")),
                "api_mode_used": result.get("api_mode_used"),
            },
        )
        return result


class _NullAIClient:
    """Legacy null client fallback."""

    def chat_completion(self, *args, **kwargs):
        return {
            "content": None,
            "model": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "finish_reason": None,
            "response_time_ms": 0,
            "status": "error",
            "error_message": "No active AI providers configured",
            "estimated_cost": 0.0,
            "provider_used": None,
            "provider_scope": "system_global",
            "quota_charged": False,
            "request_type": "chat",
            "api_mode_used": None,
            "fallback_used": False,
            "tool_calls": None,
        }


def _resolve_user(user):
    if user is None:
        return None
    if hasattr(user, "is_authenticated"):
        return user if user.is_authenticated else None
    try:
        user_id = int(user)
    except (TypeError, ValueError):
        return None
    user_model = get_user_model()
    try:
        return user_model._default_manager.get(pk=user_id)
    except user_model.DoesNotExist:
        return None


def _move_to_front(providers: list[Any], provider_id: int) -> list[Any]:
    target = None
    remainder: list[Any] = []
    for item in providers:
        if item.id == provider_id and target is None:
            target = item
            continue
        remainder.append(item)
    if target is None:
        return providers
    return [target, *remainder]
