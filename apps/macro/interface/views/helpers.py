"""
Helper functions for Macro views.
"""

import logging
from typing import Any

from apps.macro.application.interface_services import get_supported_macro_indicators
from apps.macro.application.repository_provider import MacroRepositoryProtocol, get_macro_repository
from apps.macro.application.use_cases import (
    CanonicalMacroSyncUseCase,
    build_sync_macro_data_use_case,
)

logger = logging.getLogger(__name__)


def get_repository() -> MacroRepositoryProtocol:
    """获取数据仓储实例"""
    return get_macro_repository()


def get_sync_use_case() -> CanonicalMacroSyncUseCase:
    """获取同步用例实例"""
    try:
        sync_use_case = build_sync_macro_data_use_case(source="akshare")
        logger.info("Macro sync use case 初始化成功")
        return sync_use_case
    except Exception as exc:
        logger.warning(
            "Macro sync use case initialization failed: %s",
            type(exc).__name__,
        )
        return build_sync_macro_data_use_case(source=None)


def get_supported_indicators() -> list[dict[str, Any]]:
    """获取当前默认数据源支持的指标列表。"""

    return get_supported_macro_indicators(source="akshare")
