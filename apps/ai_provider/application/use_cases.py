"""
Use cases for AI provider management.
"""

from datetime import date
from typing import Any

from ..domain.entities import AIProviderType
from ..domain.services import BudgetChecker
from ..infrastructure.adapters import OpenAICompatibleAdapter
from ..infrastructure.providers import (
    AIProviderRepository,
    AIUsageRepository,
    AIUserFallbackQuotaRepository,
)
from .dtos import (
    BatchQuotaApplyResultDTO,
    BudgetCheckResultDTO,
    OverallStatsDTO,
    ProviderListItemDTO,
    ProviderStatsDTO,
    UsageLogListItemDTO,
    UserFallbackQuotaDTO,
)


class ListProvidersUseCase:
    """获取 provider 列表，并附带日/月统计。"""

    def __init__(
        self,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
    ) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(
        self,
        *,
        include_inactive: bool = True,
        scope: str = "system",
        owner_user=None,
        include_all_scopes: bool = False,
    ) -> list[ProviderListItemDTO]:
        """List providers for admin/system or one user."""
        if include_all_scopes:
            providers = self._provider_repo.get_all_for_admin(include_inactive=include_inactive)
        elif scope == "user":
            providers = self._provider_repo.get_user_providers(
                owner_user,
                include_inactive=include_inactive,
            )
        else:
            providers = self._provider_repo.get_system_providers(include_inactive=include_inactive)

        today = date.today()
        items: list[ProviderListItemDTO] = []
        for provider in providers:
            today_usage = self._usage_repo.get_daily_usage(provider.id, today)
            month_usage = self._usage_repo.get_monthly_usage(provider.id, today.year, today.month)
            owner = provider.owner_user
            items.append(
                ProviderListItemDTO(
                    id=provider.id,
                    name=provider.name,
                    provider_type=provider.provider_type,
                    provider_type_label=provider.get_provider_type_display(),
                    scope=provider.scope,
                    owner_user_id=provider.owner_user_id,
                    owner_username=getattr(owner, "username", None),
                    is_active=provider.is_active,
                    priority=provider.priority,
                    base_url=provider.base_url,
                    default_model=provider.default_model,
                    api_mode=provider.api_mode,
                    fallback_enabled=provider.fallback_enabled,
                    daily_budget_limit=(
                        float(provider.daily_budget_limit)
                        if provider.daily_budget_limit is not None
                        else None
                    ),
                    monthly_budget_limit=(
                        float(provider.monthly_budget_limit)
                        if provider.monthly_budget_limit is not None
                        else None
                    ),
                    description=provider.description,
                    extra_config=provider.extra_config or {},
                    created_at=provider.created_at,
                    updated_at=provider.updated_at,
                    last_used_at=provider.last_used_at,
                    today_requests=today_usage["total_requests"],
                    today_cost=today_usage["total_cost"],
                    month_requests=month_usage["total_requests"],
                    month_cost=month_usage["total_cost"],
                )
            )
        return items


class CreateProviderUseCase:
    """创建 provider。"""

    VALID_API_MODES = {"dual", "responses_only", "chat_only"}

    def __init__(self, provider_repo: AIProviderRepository | None = None) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(
        self,
        *,
        name: str,
        provider_type: str,
        base_url: str,
        api_key: str,
        default_model: str = "gpt-3.5-turbo",
        api_mode: str = "dual",
        fallback_enabled: bool = True,
        is_active: bool = True,
        priority: int = 10,
        daily_budget_limit: float | None = None,
        monthly_budget_limit: float | None = None,
        description: str = "",
        extra_config: dict[str, Any] | None = None,
        scope: str = "system",
        owner_user=None,
    ) -> Any:
        self._validate_common(
            provider_type=provider_type,
            api_mode=api_mode,
            name=name,
            scope=scope,
            owner_user=owner_user,
        )
        if self._provider_repo.name_exists(name=name, scope=scope, owner_user=owner_user):
            raise ValueError(f"Provider with name '{name}' already exists in this scope")
        return self._provider_repo.create(
            name=name,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            api_mode=api_mode,
            fallback_enabled=fallback_enabled,
            is_active=is_active,
            priority=priority,
            daily_budget_limit=daily_budget_limit,
            monthly_budget_limit=monthly_budget_limit,
            description=description,
            extra_config=extra_config or {},
            scope=scope,
            owner_user=owner_user,
        )

    def _validate_common(
        self,
        *,
        provider_type: str,
        api_mode: str,
        name: str,
        scope: str,
        owner_user,
    ) -> None:
        valid_types = [item.value for item in AIProviderType]
        if provider_type not in valid_types:
            raise ValueError(
                f"Invalid provider_type: {provider_type}. Must be one of {valid_types}"
            )
        if api_mode not in self.VALID_API_MODES:
            raise ValueError(
                "Invalid api_mode. Must be one of ['dual', 'responses_only', 'chat_only']"
            )
        if scope not in {"system", "user"}:
            raise ValueError("Invalid scope. Must be one of ['system', 'user']")
        if scope == "user" and owner_user is None:
            raise ValueError("owner_user is required for user-scope providers")
        if scope == "system" and owner_user is not None:
            raise ValueError("System-scope providers cannot have owner_user")
        if not name.strip():
            raise ValueError("Provider name is required")


class UpdateProviderUseCase:
    """更新 provider。"""

    VALID_API_MODES = {"dual", "responses_only", "chat_only"}

    def __init__(self, provider_repo: AIProviderRepository | None = None) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int, *, actor_user=None, **kwargs) -> Any:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        if "provider_type" in kwargs:
            valid_types = [item.value for item in AIProviderType]
            if kwargs["provider_type"] not in valid_types:
                raise ValueError(f"Invalid provider_type. Must be one of {valid_types}")
        if "api_mode" in kwargs and kwargs["api_mode"] not in self.VALID_API_MODES:
            raise ValueError(
                "Invalid api_mode. Must be one of ['dual', 'responses_only', 'chat_only']"
            )

        scope = kwargs.get("scope", provider.scope)
        owner_user = kwargs.get("owner_user", provider.owner_user)
        if scope == "user" and owner_user is None:
            raise ValueError("owner_user is required for user-scope providers")
        if scope == "system":
            owner_user = None
            kwargs["owner_user"] = None

        if "name" in kwargs and self._provider_repo.name_exists(
            name=kwargs["name"],
            scope=scope,
            owner_user=owner_user,
            exclude_pk=pk,
        ):
            raise ValueError(f"Provider with name '{kwargs['name']}' already exists in this scope")

        success = self._provider_repo.update(pk, **kwargs)
        if not success:
            raise ValueError(f"Provider with id {pk} not found")
        updated = self._provider_repo.get_by_id(pk, user=actor_user)
        if updated is None:
            raise ValueError(f"Provider with id {pk} not found after update")
        return updated


class DeleteProviderUseCase:
    """删除 provider。"""

    def __init__(self, provider_repo: AIProviderRepository | None = None) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int, *, actor_user=None) -> bool:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")
        success = self._provider_repo.delete(pk)
        if not success:
            raise ValueError(f"Provider with id {pk} not found")
        return True


class ToggleProviderUseCase:
    """切换 provider 启用状态。"""

    def __init__(self, provider_repo: AIProviderRepository | None = None) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int, *, actor_user=None) -> Any:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")
        self._provider_repo.update(pk, is_active=not provider.is_active)
        updated = self._provider_repo.get_by_id(pk, user=actor_user)
        if updated is None:
            raise ValueError(f"Provider with id {pk} not found")
        return updated


class GetProviderStatsUseCase:
    """获取单个 provider 统计。"""

    def __init__(
        self,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
    ) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self, pk: int, days: int = 30, *, actor_user=None) -> ProviderStatsDTO:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        today = date.today()
        today_usage = self._usage_repo.get_daily_usage(pk, today)
        month_usage = self._usage_repo.get_monthly_usage(pk, today.year, today.month)
        usage_by_date = self._usage_repo.get_usage_by_date(pk, days=days)
        model_stats = self._usage_repo.get_model_stats(pk, days=days)
        return ProviderStatsDTO(
            provider_id=pk,
            provider_name=provider.name,
            today_requests=today_usage["total_requests"],
            today_cost=today_usage["total_cost"],
            month_requests=month_usage["total_requests"],
            month_cost=month_usage["total_cost"],
            usage_by_date=usage_by_date,
            model_stats=model_stats,
        )


class GetOverallStatsUseCase:
    """获取系统 provider 总体统计。"""

    def __init__(
        self,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
    ) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self) -> OverallStatsDTO:
        providers = self._provider_repo.get_system_providers(include_inactive=True)
        today = date.today()
        total_requests_today = 0
        total_cost_today = 0.0
        for provider in providers:
            today_usage = self._usage_repo.get_daily_usage(provider.id, today)
            total_requests_today += today_usage["total_requests"]
            total_cost_today += today_usage["total_cost"]
        return OverallStatsDTO(
            total_providers=len(providers),
            active_providers=len([item for item in providers if item.is_active]),
            total_requests_today=total_requests_today,
            total_cost_today=total_cost_today,
        )


class ListUsageLogsUseCase:
    """获取 usage logs。"""

    def __init__(
        self,
        usage_repo: AIUsageRepository | None = None,
        provider_repo: AIProviderRepository | None = None,
    ) -> None:
        self._usage_repo = usage_repo or AIUsageRepository()
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(
        self,
        *,
        provider_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
        user=None,
        provider_scope: str | None = None,
    ) -> list[UsageLogListItemDTO]:
        logs = self._usage_repo.get_recent_logs(
            provider_id=provider_id,
            limit=limit,
            status=status,
            user=user,
            provider_scope=provider_scope,
        )
        results: list[UsageLogListItemDTO] = []
        for log in logs:
            provider = self._provider_repo.get_by_id(log.provider_id)
            results.append(
                UsageLogListItemDTO(
                    id=log.id,
                    provider_id=log.provider_id,
                    provider_name=provider.name if provider else "Unknown",
                    provider_scope=log.provider_scope,
                    quota_charged=log.quota_charged,
                    user_id=log.user_id,
                    username=getattr(log.user, "username", None),
                    model=log.model,
                    request_type=log.request_type,
                    prompt_tokens=log.prompt_tokens,
                    completion_tokens=log.completion_tokens,
                    total_tokens=log.total_tokens,
                    estimated_cost=float(log.estimated_cost),
                    response_time_ms=log.response_time_ms,
                    status=log.status,
                    error_message=log.error_message,
                    created_at=log.created_at,
                )
            )
        return results


class CheckBudgetUseCase:
    """检查 provider 自身预算。"""

    def __init__(
        self,
        provider_repo: AIProviderRepository | None = None,
        usage_repo: AIUsageRepository | None = None,
    ) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self, pk: int, *, actor_user=None) -> BudgetCheckResultDTO:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        daily_limit = float(provider.daily_budget_limit) if provider.daily_budget_limit else None
        monthly_limit = (
            float(provider.monthly_budget_limit) if provider.monthly_budget_limit else None
        )
        budget_status = self._usage_repo.check_budget_limits(pk, daily_limit, monthly_limit)
        daily_allowed, daily_message = BudgetChecker.check_budget_limit(
            budget_status["daily"]["spent"],
            daily_limit,
        )
        monthly_allowed, monthly_message = BudgetChecker.check_budget_limit(
            budget_status["monthly"]["spent"],
            monthly_limit,
        )
        return BudgetCheckResultDTO(
            daily_allowed=daily_allowed,
            daily_message=daily_message,
            daily_spent=budget_status["daily"]["spent"],
            daily_limit=daily_limit,
            monthly_allowed=monthly_allowed,
            monthly_message=monthly_message,
            monthly_spent=budget_status["monthly"]["spent"],
            monthly_limit=monthly_limit,
        )


class GetUserFallbackQuotaUseCase:
    """获取单个用户的系统兜底额度。"""

    def __init__(
        self,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository()

    def execute(self, *, user) -> UserFallbackQuotaDTO:
        quota, daily_spent, monthly_spent = self._quota_repo.get_with_usage(user)
        return UserFallbackQuotaDTO(
            user_id=user.id,
            username=user.username,
            is_active=quota.is_active if quota else False,
            daily_limit=(
                float(quota.daily_limit) if quota and quota.daily_limit is not None else None
            ),
            monthly_limit=(
                float(quota.monthly_limit) if quota and quota.monthly_limit is not None else None
            ),
            daily_spent=daily_spent,
            monthly_spent=monthly_spent,
            daily_remaining=_remaining(
                float(quota.daily_limit) if quota and quota.daily_limit is not None else None,
                daily_spent,
            ),
            monthly_remaining=_remaining(
                float(quota.monthly_limit) if quota and quota.monthly_limit is not None else None,
                monthly_spent,
            ),
            admin_note=quota.admin_note if quota else "",
            updated_at=quota.updated_at if quota else None,
        )


class UpdateUserFallbackQuotaUseCase:
    """管理员设置单个用户的系统兜底额度。"""

    def __init__(
        self,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository()

    def execute(
        self,
        *,
        user,
        daily_limit: float | None,
        monthly_limit: float | None,
        is_active: bool = True,
        admin_note: str = "",
    ) -> UserFallbackQuotaDTO:
        quota, _ = self._quota_repo.upsert_for_user(
            user=user,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            is_active=is_active,
            admin_note=admin_note,
        )
        get_use_case = GetUserFallbackQuotaUseCase(quota_repo=self._quota_repo)
        return get_use_case.execute(user=quota.user)


class BatchApplyUserFallbackQuotaUseCase:
    """管理员批量为所有用户配置额度。"""

    def __init__(
        self,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository()

    def execute(
        self,
        *,
        daily_limit: float | None,
        monthly_limit: float | None,
        overwrite_existing: bool = False,
        is_active: bool = True,
        admin_note: str = "",
    ) -> BatchQuotaApplyResultDTO:
        result = self._quota_repo.batch_apply_to_users(
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            overwrite_existing=overwrite_existing,
            is_active=is_active,
            admin_note=admin_note,
        )
        return BatchQuotaApplyResultDTO(**result)


class ListUserFallbackQuotasUseCase:
    """管理员查看所有用户额度状态。"""

    def __init__(
        self,
        quota_repo: AIUserFallbackQuotaRepository | None = None,
    ) -> None:
        self._quota_repo = quota_repo or AIUserFallbackQuotaRepository()

    def execute(self) -> list[UserFallbackQuotaDTO]:
        users = self._quota_repo.list_active_users()
        get_use_case = GetUserFallbackQuotaUseCase(quota_repo=self._quota_repo)
        return [get_use_case.execute(user=user) for user in users]


class TestProviderConnectionUseCase:
    """测试单个 provider 的连通性。"""

    def __init__(self, provider_repo: AIProviderRepository | None = None) -> None:
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int, *, actor_user=None) -> dict[str, Any]:
        provider = self._provider_repo.get_by_id(pk, user=actor_user)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        api_key = self._provider_repo.get_api_key(provider)
        if not api_key:
            return {
                "status": "error",
                "error": "API key not available in current environment",
                "error_message": "API key not available in current environment",
            }

        adapter = OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
            default_model=provider.default_model,
            api_mode=provider.api_mode,
            fallback_enabled=provider.fallback_enabled,
        )
        available = adapter.is_available()
        if not available:
            return {
                "status": "error",
                "error": "Provider health check failed",
                "error_message": "Provider health check failed",
            }
        return {
            "status": "success",
            "provider": provider.name,
            "message": "Provider health check passed",
        }


def _remaining(limit: float | None, spent: float) -> float | None:
    if limit is None:
        return None
    return max(limit - spent, 0.0)
