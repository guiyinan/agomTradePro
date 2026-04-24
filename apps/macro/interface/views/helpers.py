"""
Helper functions for Macro views.
"""

import logging

from apps.macro.application.interface_services import get_supported_macro_indicators
from apps.macro.application.repository_provider import get_macro_repository
from apps.macro.application.use_cases import build_sync_macro_data_use_case

logger = logging.getLogger(__name__)


def get_repository():
    """获取数据仓储实例"""
    return get_macro_repository()


def get_sync_use_case():
    """获取同步用例实例"""
    try:
        sync_use_case = build_sync_macro_data_use_case(source="akshare")
        logger.info("Macro sync use case 初始化成功")
        return sync_use_case
    except Exception as e:
        logger.error(f"Macro sync use case 初始化失败: {e}")
        return build_sync_macro_data_use_case(source=None)


def get_supported_indicators():
    """获取当前默认数据源支持的指标列表。"""

    return get_supported_macro_indicators(source="akshare")
