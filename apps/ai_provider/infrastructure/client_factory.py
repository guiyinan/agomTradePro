"""
AI client factory shared by prompt, terminal, and other modules.
"""

import logging
from collections.abc import Callable
from typing import Any, Protocol, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User

from ..domain.services import AICostCalculator
from .adapters import OpenAICompatibleAdapter
from .models import AIProviderConfig
from .repositories import (
    AIProviderRepository,
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)

logger = logging.getLogger(__name__)
ProviderReference = int | str | None
ChatResult = dict[str, Any]
ChatMessages = list[dict[str, Any]]


class _ChatAdapter(Protocol):
    """Minimal adapter contract consumed by the routing client."""

    def chat_completion(
        self,
        messages: ChatMessages,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Return one normalized chat result."""


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
        self._clients: dict[tuple[str, ProviderReference, int | None], _ScopedAIClient] = {}

    def get_client(
        self,
        provider_ref: ProviderReference = None,
        user: User | int | str | object | None = None,
    ) -> "_ScopedAIClient":
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

    def _build_adapter(self, provider: AIProviderConfig) -> _ChatAdapter:
        """Build an adapter from the provider's latest persisted configuration."""
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
        provider_ref: ProviderReference,
        user: User | None,
        provider_repo: AIProviderRepository,
        usage_repo: AIUsageRepository,
        quota_repo: AIUserFallbackQuotaRepository,
        adapter_builder: Callable[[AIProviderConfig], _ChatAdapter],
    ) -> None:
        self._provider_ref = provider_ref
        self._user = user
        self._provider_repo = provider_repo
        self._usage_repo = usage_repo
        self._quota_repo = quota_repo
        self._adapter_builder = adapter_builder

    def chat_completion(
        self,
        messages: ChatMessages,
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

        last_error: str | None = None
        for provider in personal_candidates:
            if not self._provider_budget_allows(provider):
                last_error = f"Provider budget exhausted: {provider.name}"
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

    def _chat_with_system_only(
        self,
        *,
        messages: ChatMessages,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        response_format: dict[str, Any] | None,
    ) -> ChatResult:
        provider = self._provider_repo.get_provider_for_reference(self._provider_ref, user=None)
        if provider is not None and self._provider_repo.has_usable_api_key(provider):
            providers = [provider]
        else:
            providers = self._provider_repo.get_active_configured_system_providers()

        last_error: str | None = None
        for candidate in providers:
            if not self._provider_budget_allows(candidate):
                last_error = f"Provider budget exhausted: {candidate.name}"
                continue
            result = self._call_provider(
                provider=candidate,
                provider_scope="system_global",
                quota_charged=False,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
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

    def _resolve_candidates(
        self,
    ) -> tuple[list[AIProviderConfig], list[AIProviderConfig]]:
        explicit = self._provider_repo.get_provider_for_reference(
            self._provider_ref, user=self._user
        )
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

    def _provider_budget_allows(self, provider: AIProviderConfig) -> bool:
        budget = self._usage_repo.check_budget_limits(
            provider.id,
            float(provider.daily_budget_limit) if provider.daily_budget_limit is not None else None,
            (
                float(provider.monthly_budget_limit)
                if provider.monthly_budget_limit is not None
                else None
            ),
        )
        return not budget["daily"]["exceeded"] and not budget["monthly"]["exceeded"]

    def _get_fallback_quota_status(self) -> dict[str, Any]:
        if self._user is None:
            raise RuntimeError("Fallback quota requires an authenticated user")
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
        provider: AIProviderConfig,
        messages: ChatMessages,
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        response_format: dict[str, Any] | None,
        provider_scope: str,
        quota_charged: bool,
    ) -> ChatResult:
        try:
            adapter = self._adapter_builder(provider)
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
        except Exception as exc:
            logger.warning(
                "AI provider call failed before returning a normalized result: "
                "provider=%s exception_type=%s",
                provider.name,
                type(exc).__name__,
            )
            result = _error_result(
                model=model or provider.default_model,
                error_message=f"Provider {provider.name} request failed ({type(exc).__name__})",
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


def _resolve_user(user: User | int | str | object | None) -> User | None:
    """Resolve an explicit user reference without downgrading invalid IDs to anonymous."""
    if user is None:
        return None
    if hasattr(user, "is_authenticated"):
        return cast(User, user) if bool(cast(Any, user).is_authenticated) else None
    if not isinstance(user, (int, str)):
        raise ValueError("Invalid user reference") from None
    try:
        user_id = int(user)
    except ValueError:
        raise ValueError("Invalid user reference") from None
    user_model = get_user_model()
    try:
        return user_model._default_manager.get(pk=user_id)
    except user_model.DoesNotExist:
        raise ValueError("Unknown user reference") from None


def _move_to_front(
    providers: list[AIProviderConfig],
    provider_id: int,
) -> list[AIProviderConfig]:
    target: AIProviderConfig | None = None
    remainder: list[AIProviderConfig] = []
    for item in providers:
        if item.id == provider_id and target is None:
            target = item
            continue
        remainder.append(item)
    if target is None:
        return providers
    return [target, *remainder]


def _error_result(*, model: str, error_message: str) -> ChatResult:
    """Build the normalized error shape shared by routing failures."""
    return {
        "content": None,
        "model": model,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "finish_reason": None,
        "response_time_ms": 0,
        "status": "error",
        "error_message": error_message,
        "estimated_cost": 0.0,
        "provider_used": None,
        "provider_scope": None,
        "quota_charged": False,
        "request_type": "chat",
        "api_mode_used": None,
        "fallback_used": False,
        "tool_calls": None,
    }
