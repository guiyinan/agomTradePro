"""Alpha service facade separated from provider-registry orchestration."""

from collections.abc import Callable
from datetime import date
from typing import Any

from ..domain.entities import AlphaPoolScope, AlphaResult
from ..domain.interfaces import AlphaProvider
from .ai_filter import AlphaAISecondPassFilterService, get_ai_filter_candidate_limit
from .pool_resolver import PortfolioAlphaPoolResolver
from .repository_provider import (
    CacheAlphaProvider,
    ETFFallbackProvider,
    SimpleAlphaProvider,
    build_qlib_alpha_provider,
    require_usable_qlib_runtime,
)
from .services import (
    RECOVERABLE_ALPHA_SERVICE_EXCEPTIONS,
    AlphaProviderRegistry,
    _enrich_result_metadata,
    _get_provider_health_or_unavailable,
    _get_runtime_qlib_config,
    logger,
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

    _instance: "AlphaService | None" = None
    _initialized: bool = False

    def __new__(cls) -> "AlphaService":
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
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

        def _register_optional_provider(
            factory: Callable[[], AlphaProvider],
            *,
            failure_message: str,
        ) -> None:
            """Optional provider startup must not block Alpha service boot."""

            try:
                self._registry.register(factory())
            except Exception as exc:
                logger.warning("%s: %s", failure_message, exc)

        # 1. Qlib Provider（最高优先级，但可能不可用）
        try:
            qlib_config = _get_runtime_qlib_config()
            if qlib_config.get("enabled"):
                require_usable_qlib_runtime(qlib_config)
                provider_uri = qlib_config.get("provider_uri")
                model_path = qlib_config.get("model_path")
                region = qlib_config.get("region")
                if not isinstance(provider_uri, str) or not provider_uri.strip():
                    raise RuntimeError("runtime_config_snapshot_unavailable")
                if not isinstance(model_path, str) or not model_path.strip():
                    raise RuntimeError("runtime_config_snapshot_unavailable")
                if not isinstance(region, str) or not region.strip():
                    raise RuntimeError("runtime_config_snapshot_unavailable")
                _register_optional_provider(
                    lambda: build_qlib_alpha_provider(
                        provider_uri=provider_uri,
                        model_path=model_path,
                        region=region,
                    ),
                    failure_message="Qlib Provider 初始化失败（预期，如果未安装 Qlib）",
                )
                logger.info(f"Qlib Provider 已注册: {qlib_config.get('provider_uri')}")
            else:
                logger.info("Qlib 未启用，跳过注册")
        except RECOVERABLE_ALPHA_SERVICE_EXCEPTIONS as e:
            logger.warning(f"Qlib Provider 初始化失败（预期，如果未安装 Qlib）: {e}")

        # 2. Cache Provider（稳定快速）
        _register_optional_provider(
            CacheAlphaProvider,
            failure_message="Cache Provider 初始化失败",
        )

        # 3. Simple Provider（中等优先级）
        _register_optional_provider(
            SimpleAlphaProvider,
            failure_message="Simple Provider 初始化失败",
        )

        # 4. ETF Provider（最低优先级，最后防线）
        _register_optional_provider(
            ETFFallbackProvider,
            failure_message="ETF Provider 初始化失败",
        )

    def get_stock_scores(
        self,
        universe_id: str = "csi300",
        intended_trade_date: date | None = None,
        top_n: int = 30,
        user: Any = None,
        provider_filter: str | None = None,
        pool_scope: AlphaPoolScope | None = None,
        ai_filter: bool = False,
    ) -> AlphaResult:
        """
        获取股票评分（带自动降级）

        这是主要的对外接口，自动处理 Provider 降级。

        Args:
            universe_id: 股票池标识（默认 csi300）
            intended_trade_date: 计划交易日期（默认今天）
            top_n: 返回前 N 只（默认 30）
            user: 当前用户（用于 Cache Provider）
            provider_filter: 强制使用指定 Provider（禁用降级），如 "qlib"/"cache"/"simple"/"etf"

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
            f"date={intended_trade_date}, top_n={top_n}, provider_filter={provider_filter}"
        )

        effective_universe_id = pool_scope.universe_id if pool_scope is not None else universe_id

        provider_top_n = get_ai_filter_candidate_limit(top_n) if ai_filter else top_n

        result = self._registry.get_scores_with_fallback(
            effective_universe_id,
            intended_trade_date,
            provider_top_n,
            user=user,
            provider_filter=provider_filter,
            pool_scope=pool_scope,
        )

        if pool_scope is not None:
            metadata = dict(result.metadata or {})
            metadata.setdefault("scope_hash", pool_scope.scope_hash)
            metadata.setdefault("scope_label", pool_scope.display_label)
            metadata.setdefault("scope_metadata", pool_scope.to_dict())
            result.metadata = metadata

        logger.info(
            f"评分结果: success={result.success}, source={result.source}, "
            f"status={result.status}, count={len(result.scores)}"
        )

        enriched = _enrich_result_metadata(result, intended_trade_date)
        if ai_filter:
            return AlphaAISecondPassFilterService().apply(
                enriched,
                top_n=top_n,
                user=user,
                trade_date=intended_trade_date,
            )
        return enriched

    def resolve_portfolio_pool_scope(
        self,
        *,
        user_id: int,
        trade_date: date | None = None,
        portfolio_id: int | None = None,
    ) -> AlphaPoolScope:
        """Resolve a portfolio-driven Alpha pool scope."""
        resolved = PortfolioAlphaPoolResolver().resolve(
            user_id=user_id,
            trade_date=trade_date or date.today(),
            portfolio_id=portfolio_id,
        )
        return resolved.scope

    def get_provider_status(self) -> dict[str, dict[str, Any]]:
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
        status: dict[str, dict[str, Any]] = {}

        for provider in self._registry.get_all_providers():
            health, error = _get_provider_health_or_unavailable(
                provider,
                context="get_provider_status",
            )
            if error is not None:
                status[provider.name] = {
                    "priority": provider.priority,
                    "status": "error",
                    "error": error,
                }
                continue

            if health is None:
                status[provider.name] = {
                    "priority": provider.priority,
                    "status": "error",
                    "error": "Provider health check returned no status",
                }
                continue

            provider_info = {
                "priority": provider.priority,
                "status": health.value,
                "max_staleness_days": provider.max_staleness_days,
            }
            # 添加健康检查消息（用于显示降级原因）
            if hasattr(provider, "_last_health_message") and provider._last_health_message:
                provider_info["message"] = provider._last_health_message
            status[provider.name] = provider_info

        return status

    def get_factor_exposure(
        self,
        *,
        stock_code: str,
        trade_date: date,
        provider_name: str = "simple",
    ) -> dict[str, Any]:
        """Return factor exposure from one explicitly selected registered provider."""

        provider = self._registry.get_provider(provider_name)
        if provider is None:
            raise ValueError(f"Provider '{provider_name}' does not exist")
        return provider.get_factor_exposure(stock_code, trade_date)

    def get_provider_registry_status(self) -> dict[str, dict[str, Any]]:
        """Return registered provider metadata without running health checks."""
        status = {}

        for provider in self._registry.get_all_providers():
            provider_info = {
                "priority": provider.priority,
                "status": "registered",
                "max_staleness_days": provider.max_staleness_days,
            }
            if hasattr(provider, "_last_health_message") and provider._last_health_message:
                provider_info["message"] = provider._last_health_message
            status[provider.name] = provider_info

        return status

    def get_available_universes(self) -> list[str]:
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

        return sorted(universes)

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
