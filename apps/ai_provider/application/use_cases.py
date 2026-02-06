"""
Use Cases for AI Provider Management.

用例编排，协调 Domain 层和 Infrastructure 层完成业务逻辑。
遵循项目架构约束：Application 层通过依赖注入使用 Infrastructure 层。
"""

from typing import List, Optional, Dict, Any
from datetime import date, datetime

from ..infrastructure.models import AIProviderConfig, AIUsageLog
from ..infrastructure.repositories import AIProviderRepository, AIUsageRepository
from ..domain.entities import AIProviderType
from ..domain.services import AICostCalculator, BudgetChecker
from .dtos import (
    ProviderStatsDTO,
    UsageStatsDTO,
    OverallStatsDTO,
    ProviderListItemDTO,
    BudgetCheckResultDTO,
    UsageLogListItemDTO,
)


class ListProvidersUseCase:
    """
    获取提供商列表用例

    返回所有提供商及其今日/本月统计。
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None,
        usage_repo: Optional[AIUsageRepository] = None
    ):
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self, include_inactive: bool = True) -> List[ProviderListItemDTO]:
        """
        执行用例

        Args:
            include_inactive: 是否包含未启用的提供商

        Returns:
            List[ProviderListItemDTO]: 提供商列表
        """
        if include_inactive:
            providers = self._provider_repo.get_all()
        else:
            providers = self._provider_repo.get_active_providers()

        today = date.today()

        result = []
        for provider in providers:
            # 获取统计数据
            today_usage = self._usage_repo.get_daily_usage(provider.id, today)
            month_usage = self._usage_repo.get_monthly_usage(
                provider.id, today.year, today.month
            )

            result.append(
                ProviderListItemDTO(
                    id=provider.id,
                    name=provider.name,
                    provider_type=provider.provider_type,
                    is_active=provider.is_active,
                    priority=provider.priority,
                    base_url=provider.base_url,
                    default_model=provider.default_model,
                    description=provider.description,
                    created_at=provider.created_at,
                    updated_at=provider.updated_at,
                    last_used_at=provider.last_used_at,
                    today_requests=today_usage["total_requests"],
                    today_cost=today_usage["total_cost"],
                    month_requests=month_usage["total_requests"],
                    month_cost=month_usage["total_cost"],
                )
            )

        return result


class CreateProviderUseCase:
    """
    创建提供商用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None
    ):
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(
        self,
        name: str,
        provider_type: str,
        base_url: str,
        api_key: str,
        default_model: str = "gpt-3.5-turbo",
        is_active: bool = True,
        priority: int = 10,
        daily_budget_limit: Optional[float] = None,
        monthly_budget_limit: Optional[float] = None,
        description: str = "",
        extra_config: Optional[Dict] = None,
    ) -> AIProviderConfig:
        """
        创建新的 AI 提供商配置

        Args:
            name: 配置名称
            provider_type: 提供商类型
            base_url: API Base URL
            api_key: API Key
            default_model: 默认模型
            is_active: 是否启用
            priority: 优先级
            daily_budget_limit: 每日预算限制
            monthly_budget_limit: 每月预算限制
            description: 描述
            extra_config: 额外配置

        Returns:
            AIProviderConfig: 创建的提供商配置
        """
        # 验证提供商类型
        valid_types = [t.value for t in AIProviderType]
        if provider_type not in valid_types:
            raise ValueError(f"Invalid provider_type: {provider_type}. Must be one of {valid_types}")

        # 检查名称是否已存在
        existing = self._provider_repo.get_by_name(name)
        if existing is not None:
            raise ValueError(f"Provider with name '{name}' already exists")

        return self._provider_repo.create(
            name=name,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            is_active=is_active,
            priority=priority,
            daily_budget_limit=daily_budget_limit,
            monthly_budget_limit=monthly_budget_limit,
            description=description,
            extra_config=extra_config or {},
        )


class UpdateProviderUseCase:
    """
    更新提供商用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None
    ):
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int, **kwargs) -> AIProviderConfig:
        """
        更新提供商配置

        Args:
            pk: 提供商 ID
            **kwargs: 要更新的字段

        Returns:
            AIProviderConfig: 更新后的提供商配置

        Raises:
            ValueError: 提供商不存在
        """
        # 验证提供商类型
        if "provider_type" in kwargs:
            valid_types = [t.value for t in AIProviderType]
            if kwargs["provider_type"] not in valid_types:
                raise ValueError(f"Invalid provider_type. Must be one of {valid_types}")

        # 如果更新名称，检查是否重复
        if "name" in kwargs:
            existing = self._provider_repo.get_by_name(kwargs["name"])
            if existing is not None and existing.id != pk:
                raise ValueError(f"Provider with name '{kwargs['name']}' already exists")

        success = self._provider_repo.update(pk, **kwargs)
        if not success:
            raise ValueError(f"Provider with id {pk} not found")

        return self._provider_repo.get_by_id(pk)


class DeleteProviderUseCase:
    """
    删除提供商用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None
    ):
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int) -> bool:
        """
        删除提供商配置

        Args:
            pk: 提供商 ID

        Returns:
            bool: 是否删除成功

        Raises:
            ValueError: 提供商不存在
        """
        success = self._provider_repo.delete(pk)
        if not success:
            raise ValueError(f"Provider with id {pk} not found")
        return True


class ToggleProviderUseCase:
    """
    切换提供商启用状态用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None
    ):
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(self, pk: int) -> AIProviderConfig:
        """
        切换提供商的启用/禁用状态

        Args:
            pk: 提供商 ID

        Returns:
            AIProviderConfig: 更新后的提供商配置

        Raises:
            ValueError: 提供商不存在
        """
        provider = self._provider_repo.get_by_id(pk)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        new_status = not provider.is_active
        self._provider_repo.update(pk, is_active=new_status)

        return self._provider_repo.get_by_id(pk)


class GetProviderStatsUseCase:
    """
    获取提供商统计数据用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None,
        usage_repo: Optional[AIUsageRepository] = None,
    ):
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self, pk: int, days: int = 30) -> ProviderStatsDTO:
        """
        获取提供商的详细统计

        Args:
            pk: 提供商 ID
            days: 统计天数

        Returns:
            ProviderStatsDTO: 提供商统计数据

        Raises:
            ValueError: 提供商不存在
        """
        provider = self._provider_repo.get_by_id(pk)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        today = date.today()

        # 今日统计
        today_usage = self._usage_repo.get_daily_usage(pk, today)

        # 本月统计
        month_usage = self._usage_repo.get_monthly_usage(
            pk, today.year, today.month
        )

        # 按日期统计
        usage_by_date = self._usage_repo.get_usage_by_date(pk, days=days)

        # 按模型统计
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
    """
    获取总体统计数据用例
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None,
        usage_repo: Optional[AIUsageRepository] = None,
    ):
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self) -> OverallStatsDTO:
        """
        获取所有提供商的总体统计

        Returns:
            OverallStatsDTO: 总体统计数据
        """
        providers = self._provider_repo.get_all()
        today = date.today()

        total_providers = len(providers)
        active_providers = len([p for p in providers if p.is_active])

        # 今日总请求和成本
        total_requests_today = 0
        total_cost_today = 0.0

        for provider in providers:
            today_usage = self._usage_repo.get_daily_usage(provider.id, today)
            total_requests_today += today_usage["total_requests"]
            total_cost_today += today_usage["total_cost"]

        return OverallStatsDTO(
            total_providers=total_providers,
            active_providers=active_providers,
            total_requests_today=total_requests_today,
            total_cost_today=total_cost_today,
        )


class ListUsageLogsUseCase:
    """
    获取使用日志列表用例
    """

    def __init__(
        self,
        usage_repo: Optional[AIUsageRepository] = None,
        provider_repo: Optional[AIProviderRepository] = None,
    ):
        self._usage_repo = usage_repo or AIUsageRepository()
        self._provider_repo = provider_repo or AIProviderRepository()

    def execute(
        self,
        provider_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[UsageLogListItemDTO]:
        """
        获取使用日志列表

        Args:
            provider_id: 提供商 ID（可选）
            status: 状态过滤（可选）
            limit: 返回数量限制

        Returns:
            List[UsageLogListItemDTO]: 日志列表
        """
        logs = self._usage_repo.get_recent_logs(
            provider_id=provider_id,
            limit=limit,
            status=status,
        )

        result = []
        for log in logs:
            provider = self._provider_repo.get_by_id(log.provider_id)
            provider_name = provider.name if provider else "Unknown"

            result.append(
                UsageLogListItemDTO(
                    id=log.id,
                    provider_id=log.provider_id,
                    provider_name=provider_name,
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

        return result


class CheckBudgetUseCase:
    """
    检查预算限制用例

    协调 Domain 层的 BudgetChecker 和 Infrastructure 层的 AIUsageRepository
    完成预算检查逻辑。
    """

    def __init__(
        self,
        provider_repo: Optional[AIProviderRepository] = None,
        usage_repo: Optional[AIUsageRepository] = None,
    ):
        self._provider_repo = provider_repo or AIProviderRepository()
        self._usage_repo = usage_repo or AIUsageRepository()

    def execute(self, pk: int) -> BudgetCheckResultDTO:
        """
        检查提供商的预算限制

        Args:
            pk: 提供商 ID

        Returns:
            BudgetCheckResultDTO: 预算检查结果

        Raises:
            ValueError: 提供商不存在
        """
        provider = self._provider_repo.get_by_id(pk)
        if provider is None:
            raise ValueError(f"Provider with id {pk} not found")

        daily_limit = float(provider.daily_budget_limit) if provider.daily_budget_limit else None
        monthly_limit = float(provider.monthly_budget_limit) if provider.monthly_budget_limit else None

        # 使用 Repository 获取当前消费
        budget_status = self._usage_repo.check_budget_limits(
            pk, daily_limit, monthly_limit
        )

        # 使用 Domain 层的 BudgetChecker 进行业务规则验证
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
