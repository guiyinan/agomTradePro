"""
Alpha Application Services

Alpha 服务层，实现 Provider 注册中心和 AlphaService。
"""

import logging
import time
from datetime import date
from typing import Dict, List, Optional

from ..domain.entities import AlphaResult
from ..domain.interfaces import AlphaProvider, AlphaProviderStatus
from ..infrastructure.adapters.cache_adapter import CacheAlphaProvider
from ..infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from ..infrastructure.adapters.etf_adapter import ETFFallbackProvider


logger = logging.getLogger(__name__)

# 延迟导入监控模块（避免循环依赖）
_alpha_metrics_instance = None


def get_alpha_metrics():
    """获取 Alpha 指标收集器"""
    global _alpha_metrics_instance
    if _alpha_metrics_instance is None:
        from shared.infrastructure.metrics import get_alpha_metrics as _get_metrics
        _alpha_metrics_instance = _get_metrics()
    return _alpha_metrics_instance


class AlphaProviderRegistry:
    """
    Alpha Provider 注册中心

    管理 Provider 的注册、获取和降级逻辑。
    实现自动降级链路：Qlib → Cache → Simple → ETF

    Attributes:
        _providers: 已注册的 Provider 列表（按优先级排序）

    Example:
        >>> registry = AlphaProviderRegistry()
        >>> registry.register(QlibAlphaProvider())
        >>> registry.register(CacheAlphaProvider())
        >>> result = registry.get_scores_with_fallback("csi300", date.today())
    """

    def __init__(self):
        """初始化注册中心"""
        self._providers: List[AlphaProvider] = []

    def register(self, provider: AlphaProvider) -> None:
        """
        注册 Provider

        注册后自动按 priority 排序。

        Args:
            provider: 要注册的 Provider

        Raises:
            ValueError: 如果 Provider 名称已存在
        """
        # 检查名称是否已存在
        existing_names = {p.name for p in self._providers}
        if provider.name in existing_names:
            logger.warning(f"Provider {provider.name} 已存在，将被覆盖")
            # 移除已存在的
            self._providers = [p for p in self._providers if p.name != provider.name]

        self._providers.append(provider)

        # 按 priority 排序
        self._providers.sort(key=lambda p: p.priority)

        logger.info(
            f"注册 Provider: {provider.name} (priority={provider.priority}, "
            f"总数={len(self._providers)})"
        )

    def unregister(self, provider_name: str) -> bool:
        """
        取消注册 Provider

        Args:
            provider_name: Provider 名称

        Returns:
            是否成功取消注册
        """
        initial_count = len(self._providers)
        self._providers = [p for p in self._providers if p.name != provider_name]

        if len(self._providers) < initial_count:
            logger.info(f"取消注册 Provider: {provider_name}")
            return True
        return False

    def get_provider(self, name: str) -> Optional[AlphaProvider]:
        """
        获取指定名称的 Provider

        Args:
            name: Provider 名称

        Returns:
            Provider 实例，如果不存在则返回 None
        """
        for provider in self._providers:
            if provider.name == name:
                return provider
        return None

    def get_all_providers(self) -> List[AlphaProvider]:
        """
        获取所有已注册的 Provider

        Returns:
            Provider 列表（按优先级排序）
        """
        return list(self._providers)

    def get_active_providers(self) -> List[AlphaProvider]:
        """
        获取所有可用的 Provider

        检查每个 Provider 的健康状态，返回可用的列表。

        Returns:
            可用 Provider 列表（按优先级排序）
        """
        active = []
        for provider in self._providers:
            try:
                status = provider.health_check()
                if status != AlphaProviderStatus.UNAVAILABLE:
                    active.append(provider)
                    logger.debug(f"Provider {provider.name}: {status.value}")
            except Exception as e:
                logger.error(f"检查 Provider {provider.name} 状态失败: {e}")

        return active

    def get_scores_with_fallback(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30,
        user=None,
    ) -> AlphaResult:
        """
        带降级的评分获取

        按优先级依次尝试每个 Provider，直到成功或全部失败。

        降级逻辑：
        1. 遍历 Provider（按 priority 排序）
        2. 检查健康状态
        3. 尝试获取评分
        4. 检查 staleness，如果过期且不是最后一个，继续尝试下一个
        5. 如果全部失败，返回 unavailable

        Args:
            universe_id: 股票池标识
            intended_trade_date: 计划交易日期
            top_n: 返回前 N 只

        Returns:
            AlphaResult
        """
        active_providers = self.get_active_providers()

        if not active_providers:
            logger.warning("没有可用的 Provider")

            # 记录失败指标
            try:
                metrics = get_alpha_metrics()
                metrics.record_provider_call("none", success=False, latency_ms=0)
            except Exception:
                pass  # 指标记录失败不影响主流程

            return AlphaResult(
                success=False,
                scores=[],
                source="none",
                timestamp=date.today().isoformat(),
                status="unavailable",
                error_message="所有 Alpha Provider 不可用",
            )

        # 遍历 Provider
        for i, provider in enumerate(active_providers):
            provider_start_time = time.time()
            cache_hit = False

            try:
                logger.info(
                    f"尝试 Provider: {provider.name} "
                    f"(priority={provider.priority}, {i+1}/{len(active_providers)})"
                )

                # 检查是否支持该 universe
                if not provider.supports(universe_id):
                    logger.debug(f"Provider {provider.name} 不支持 {universe_id}")
                    continue

                # 获取评分（Cache Provider 支持 user 参数）
                if provider.name == "cache":
                    result = provider.get_stock_scores(universe_id, intended_trade_date, top_n, user=user)
                else:
                    result = provider.get_stock_scores(universe_id, intended_trade_date, top_n)

                # 计算延迟
                latency_ms = (time.time() - provider_start_time) * 1000
                result.latency_ms = int(latency_ms)

                # 检查是否缓存命中（Cache Provider）
                cache_hit = (provider.name == "cache" and result.success)

                if not result.success:
                    logger.debug(f"Provider {provider.name} 返回失败: {result.error_message}")

                    # 记录失败指标
                    try:
                        metrics = get_alpha_metrics()
                        metrics.record_provider_call(
                            provider.name,
                            success=False,
                            latency_ms=latency_ms
                        )
                    except Exception:
                        pass

                    continue

                # 检查 staleness
                staleness_ok = True
                if result.staleness_days and result.staleness_days > provider.max_staleness_days:
                    logger.warning(
                        f"Provider {provider.name} 数据过期: {result.staleness_days} 天 "
                        f"(最大允许 {provider.max_staleness_days} 天)"
                    )

                    # 标记 degraded
                    result.status = "degraded"
                    staleness_ok = False

                    # 如果这是最后一个 provider，返回 degraded 结果
                    if i == len(active_providers) - 1:
                        logger.warning(f"所有 Provider 数据过期，使用 {provider.name} 的降级结果")

                        # 记录指标
                        try:
                            metrics = get_alpha_metrics()
                            metrics.record_provider_call(
                                provider.name,
                                success=True,
                                latency_ms=latency_ms,
                                staleness_days=result.staleness_days
                            )
                            if result.scores:
                                metrics.record_coverage(len(result.scores), 300)
                        except Exception:
                            pass

                        return result

                    # 否则继续尝试下一个
                    continue

                # 成功获取新鲜数据
                logger.info(
                    f"成功从 {provider.name} 获取 {len(result.scores)} 只股票评分 "
                    f"(latency={latency_ms:.0f}ms)"
                )

                # 记录成功指标
                try:
                    metrics = get_alpha_metrics()
                    metrics.record_provider_call(
                        provider.name,
                        success=True,
                        latency_ms=latency_ms,
                        staleness_days=result.staleness_days
                    )
                    if cache_hit:
                        metrics.record_cache_hit(True)
                    if result.scores:
                        metrics.record_coverage(len(result.scores), 300)
                except Exception as e:
                    logger.debug(f"记录指标失败: {e}")

                return result

            except Exception as e:
                latency_ms = (time.time() - provider_start_time) * 1000
                logger.error(f"Provider {provider.name} 调用失败: {e}", exc_info=True)

                # 记录异常指标
                try:
                    metrics = get_alpha_metrics()
                    metrics.record_provider_call(
                        provider.name,
                        success=False,
                        latency_ms=latency_ms
                    )
                except Exception:
                    pass

                continue

        # 所有 provider 都失败
        return AlphaResult(
            success=False,
            scores=[],
            source="none",
            timestamp=date.today().isoformat(),
            status="unavailable",
            error_message="所有 Alpha Provider 失败或数据过期",
        )


class AlphaService:
    """
    Alpha 服务（单例）

    Alpha 信号系统的主入口，管理 Provider 生命周期和请求路由。

    默认注册的 Provider（按优先级）：
    1. Qlib (priority=1) - 机器学习模型（需要 Qlib）
    2. Cache (priority=10) - 缓存数据
    3. Simple (priority=100) - 简单因子
    4. ETF (priority=1000) - ETF 降级

    Example:
        >>> service = AlphaService()
        >>> result = service.get_stock_scores("csi300", date.today())
        >>> if result.success:
        ...     for stock in result.scores[:5]:
        ...         print(f"{stock.rank}. {stock.code}: {stock.score:.3f}")
    """

    _instance: Optional["AlphaService"] = None

    def __new__(cls):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化服务"""
        if self._initialized:
            return

        self._registry = AlphaProviderRegistry()
        self._setup_providers()
        self._initialized = True

        logger.info("AlphaService 初始化完成")

    def _setup_providers(self) -> None:
        """
        设置默认 Provider

        按优先级注册默认 Provider：
        1. Qlib - 最优但需要 Qlib 环境
        2. Cache - 稳定快速
        3. Simple - 外部依赖
        4. ETF - 最后防线
        """
        # 1. Qlib Provider（最高优先级，但可能不可用）
        try:
            from ..infrastructure.adapters.qlib_adapter import QlibAlphaProvider
            from apps.account.infrastructure.models import SystemSettingsModel
            
            qlib_config = SystemSettingsModel.get_runtime_qlib_config()
            if qlib_config.get('enabled'):
                qlib_provider = QlibAlphaProvider(
                    provider_uri=qlib_config.get('provider_uri', '~/.qlib/qlib_data/cn_data'),
                    model_path=qlib_config.get('model_path', '/models/qlib'),
                    region=qlib_config.get('region', 'CN')
                )
                self._registry.register(qlib_provider)
                logger.info(f"Qlib Provider 已注册: {qlib_config.get('provider_uri')}")
            else:
                logger.info("Qlib 未启用，跳过注册")
        except Exception as e:
            logger.warning(f"Qlib Provider 初始化失败（预期，如果未安装 Qlib）: {e}")

        # 2. Cache Provider（稳定快速）
        try:
            cache_provider = CacheAlphaProvider()
            self._registry.register(cache_provider)
        except Exception as e:
            logger.warning(f"Cache Provider 初始化失败: {e}")

        # 3. Simple Provider（中等优先级）
        try:
            simple_provider = SimpleAlphaProvider()
            self._registry.register(simple_provider)
        except Exception as e:
            logger.warning(f"Simple Provider 初始化失败: {e}")

        # 4. ETF Provider（最低优先级，最后防线）
        try:
            etf_provider = ETFFallbackProvider()
            self._registry.register(etf_provider)
        except Exception as e:
            logger.warning(f"ETF Provider 初始化失败: {e}")

    def get_stock_scores(
        self,
        universe_id: str = "csi300",
        intended_trade_date: Optional[date] = None,
        top_n: int = 30,
        user=None,
    ) -> AlphaResult:
        """
        获取股票评分（带自动降级）

        这是主要的对外接口，自动处理 Provider 降级。

        Args:
            universe_id: 股票池标识（默认 csi300）
            intended_trade_date: 计划交易日期（默认今天）
            top_n: 返回前 N 只（默认 30）

        Returns:
            AlphaResult 包含评分列表和元数据

        Example:
            >>> service = AlphaService()
            >>> result = service.get_stock_scores("csi300")
            >>> print(f"Source: {result.source}, Status: {result.status}")
        """
        if intended_trade_date is None:
            intended_trade_date = date.today()

        logger.info(
            f"获取股票评分: universe={universe_id}, "
            f"date={intended_trade_date}, top_n={top_n}"
        )

        result = self._registry.get_scores_with_fallback(
            universe_id,
            intended_trade_date,
            top_n,
            user=user,
        )

        logger.info(
            f"评分结果: success={result.success}, source={result.source}, "
            f"status={result.status}, count={len(result.scores)}"
        )

        return result

    def get_provider_status(self) -> Dict[str, Dict[str, str]]:
        """
        获取所有 Provider 状态

        用于诊断和监控。

        Returns:
            Provider 状态字典

        Example:
            >>> service = AlphaService()
            >>> status = service.get_provider_status()
            >>> for name, info in status.items():
            ...     print(f"{name}: {info['status']} (priority={info['priority']})")
        """
        status = {}

        for provider in self._registry.get_all_providers():
            try:
                health = provider.health_check()
                provider_info = {
                    "priority": provider.priority,
                    "status": health.value,
                    "max_staleness_days": provider.max_staleness_days,
                }
                # 添加健康检查消息（用于显示降级原因）
                if hasattr(provider, '_last_health_message') and provider._last_health_message:
                    provider_info["message"] = provider._last_health_message
                status[provider.name] = provider_info
            except Exception as e:
                status[provider.name] = {
                    "priority": provider.priority,
                    "status": "error",
                    "error": str(e),
                }

        return status

    def get_available_universes(self) -> List[str]:
        """
        获取支持的股票池列表

        Returns:
            股票池标识列表
        """
        universes = set()

        for provider in self._registry.get_all_providers():
            if hasattr(provider, "get_supported_universes"):
                universes.update(provider.get_supported_universes())
            else:
                # 默认支持的股票池
                universes.update(["csi300", "csi500", "sse50", "csi1000"])

        return sorted(list(universes))

    def register_provider(self, provider: AlphaProvider) -> None:
        """
        动态注册 Provider

        用于运行时添加新的 Provider。

        Args:
            provider: 要注册的 Provider

        Example:
            >>> service = AlphaService()
            >>> custom_provider = MyCustomProvider()
            >>> service.register_provider(custom_provider)
        """
        self._registry.register(provider)
