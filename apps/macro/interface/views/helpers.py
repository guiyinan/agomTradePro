"""
Helper functions for Macro views.
"""

import logging

from apps.macro.application.use_cases import SyncMacroDataUseCase
from apps.macro.infrastructure.adapters import AKShareAdapter
from apps.macro.infrastructure.repositories import DjangoMacroRepository

logger = logging.getLogger(__name__)


def get_repository():
    """获取数据仓储实例"""
    return DjangoMacroRepository()


def get_sync_use_case():
    """获取同步用例实例"""
    repo = get_repository()
    # 初始化 AKShare 适配器
    try:
        akshare_adapter = AKShareAdapter()
        adapters = {"akshare": akshare_adapter}
        logger.info("AKShare 适配器初始化成功")
    except Exception as e:
        logger.error(f"AKShare 适配器初始化失败: {e}")
        adapters = {}
    return SyncMacroDataUseCase(repository=repo, adapters=adapters)
