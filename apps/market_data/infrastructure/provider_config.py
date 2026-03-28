"""
Market Data provider config loaders.

将统一财经数据源配置解析为运行时 provider 定义。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def load_active_qmt_provider_configs() -> list[dict[str, Any]]:
    """读取激活的 QMT provider 配置。"""
    try:
        from apps.macro.infrastructure.models import DataSourceConfig

        return list(
            DataSourceConfig._default_manager.filter(
                source_type="qmt",
                is_active=True,
            ).values("name", "priority", "extra_config")
        )
    except Exception:
        logger.warning("读取 QMT 数据源配置失败，跳过 DB 注册", exc_info=True)
        return []
