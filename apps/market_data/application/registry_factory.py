"""
Registry 工厂

创建并配置全局 SourceRegistry 实例。
通过配置决定注册哪些 provider 以及优先级。
"""

import logging
from typing import Optional

from django.conf import settings

from apps.market_data.infrastructure.gateways.akshare_eastmoney_gateway import (
    AKShareEastMoneyGateway,
)
from apps.market_data.infrastructure.gateways.akshare_general_gateway import (
    AKShareGeneralGateway,
)
from apps.market_data.infrastructure.gateways.qmt_gateway import QMTGateway
from apps.market_data.infrastructure.gateways.tushare_gateway import (
    TushareGateway,
)
from apps.market_data.infrastructure.provider_config import (
    load_active_qmt_provider_configs,
)
from apps.market_data.infrastructure.registries.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

_global_registry: SourceRegistry | None = None


def get_registry() -> SourceRegistry:
    """获取全局 SourceRegistry 单例

    首次调用时根据配置初始化。
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = _build_registry()
    return _global_registry


def _build_registry() -> SourceRegistry:
    """根据 Django settings 构建 registry

    注册顺序和优先级：
      - 东方财富 (priority=10) — 主源，覆盖 4 种能力
      - QMT (priority=15) — 本地终端直连行情源
      - AKShare 通用 (priority=20) — 备用，行情+技术指标
      - Tushare (priority=30) — 第三备用，日线级行情

    任何一个 gateway 构造失败（如依赖包缺失），跳过该源继续注册其他源。
    """
    registry = SourceRegistry()

    # 1. 东方财富（通过 AKShare 封装）— 主数据源
    eastmoney_enabled = getattr(
        settings, "MARKET_DATA_EASTMONEY_ENABLED", True
    )
    if eastmoney_enabled:
        try:
            interval = getattr(
                settings, "MARKET_DATA_EASTMONEY_INTERVAL_SEC", 0.5
            )
            gateway = AKShareEastMoneyGateway(request_interval_sec=interval)
            priority = getattr(settings, "MARKET_DATA_EASTMONEY_PRIORITY", 10)
            registry.register(gateway, priority=priority)
            logger.info("已注册东方财富 provider (priority=%d)", priority)
        except Exception:
            logger.warning("东方财富 provider 注册失败，跳过", exc_info=True)

    # 2. QMT — 本地终端行情源
    qmt_registered = _register_qmt_providers(registry)
    if not qmt_registered:
        qmt_enabled = getattr(settings, "MARKET_DATA_QMT_ENABLED", False)
        if qmt_enabled:
            try:
                qmt_priority = getattr(settings, "MARKET_DATA_QMT_PRIORITY", 15)
                registry.register(QMTGateway(), priority=qmt_priority)
                logger.info("已注册 QMT provider (priority=%d)", qmt_priority)
            except Exception:
                logger.warning("QMT provider 注册失败，跳过", exc_info=True)

    # 3. AKShare 通用 — 备用数据源
    akshare_general_enabled = getattr(
        settings, "MARKET_DATA_AKSHARE_GENERAL_ENABLED", True
    )
    if akshare_general_enabled:
        try:
            akshare_gw = AKShareGeneralGateway()
            akshare_priority = getattr(
                settings, "MARKET_DATA_AKSHARE_GENERAL_PRIORITY", 20
            )
            registry.register(akshare_gw, priority=akshare_priority)
            logger.info("已注册 AKShare 通用 provider (priority=%d)", akshare_priority)
        except Exception:
            logger.warning("AKShare 通用 provider 注册失败，跳过", exc_info=True)

    # 4. Tushare — 第三备用数据源
    tushare_enabled = getattr(
        settings, "MARKET_DATA_TUSHARE_ENABLED", True
    )
    if tushare_enabled:
        try:
            tushare_gw = TushareGateway()
            tushare_priority = getattr(
                settings, "MARKET_DATA_TUSHARE_PRIORITY", 30
            )
            registry.register(tushare_gw, priority=tushare_priority)
            logger.info("已注册 Tushare provider (priority=%d)", tushare_priority)
        except Exception:
            logger.warning("Tushare provider 注册失败，跳过", exc_info=True)

    if not registry.get_all_statuses():
        logger.error("所有数据源注册失败！系统将无法获取行情数据")

    return registry


def _register_qmt_providers(registry: SourceRegistry) -> bool:
    """从统一数据源配置中注册 QMT provider。"""
    rows = load_active_qmt_provider_configs()
    if not rows:
        return False

    registered = False
    for row in rows:
        try:
            gateway = QMTGateway(
                source_name=row["name"],
                extra_config=row.get("extra_config") or {},
            )
            registry.register(gateway, priority=row["priority"])
            logger.info(
                "已从统一数据源配置注册 QMT provider: %s (priority=%d)",
                row["name"],
                row["priority"],
            )
            registered = True
        except Exception:
            logger.warning("QMT 数据源 %s 注册失败，跳过", row.get("name"), exc_info=True)
    return registered


def reset_registry() -> None:
    """重置全局 registry（主要用于测试）"""
    global _global_registry
    _global_registry = None
