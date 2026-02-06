"""
Application Layer for AI Provider Management.

用例编排层，负责协调 Domain 层和 Infrastructure 层完成业务用例。
遵循项目架构约束：Application 层依赖 Domain 层，通过依赖注入使用 Infrastructure 层。
"""

from .dtos import (
    ProviderStatsDTO,
    UsageStatsDTO,
    OverallStatsDTO,
    ProviderListItemDTO,
)
from .use_cases import (
    ListProvidersUseCase,
    CreateProviderUseCase,
    UpdateProviderUseCase,
    DeleteProviderUseCase,
    ToggleProviderUseCase,
    GetProviderStatsUseCase,
    GetOverallStatsUseCase,
    ListUsageLogsUseCase,
    CheckBudgetUseCase,
)

__all__ = [
    # DTOs
    "ProviderStatsDTO",
    "UsageStatsDTO",
    "OverallStatsDTO",
    "ProviderListItemDTO",
    # Use Cases
    "ListProvidersUseCase",
    "CreateProviderUseCase",
    "UpdateProviderUseCase",
    "DeleteProviderUseCase",
    "ToggleProviderUseCase",
    "GetProviderStatsUseCase",
    "GetOverallStatsUseCase",
    "ListUsageLogsUseCase",
    "CheckBudgetUseCase",
]
