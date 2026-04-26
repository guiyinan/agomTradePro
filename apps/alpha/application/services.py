"""
Alpha Application Services

Alpha 服务层，实现 Provider 注册中心和 AlphaService。
"""

import logging
import inspect
import time
from datetime import date, timezone
from typing import Any, Optional

from core.integration.runtime_settings import (
    get_runtime_alpha_fixed_provider,
    get_runtime_qlib_config,
)

from ..domain.entities import AlphaPoolScope, AlphaResult
from ..domain.interfaces import AlphaProvider, AlphaProviderStatus
from .repository_provider import get_alpha_alert_repository
from .pool_resolver import PortfolioAlphaPoolResolver
from ..infrastructure.adapters.cache_adapter import CacheAlphaProvider
from ..infrastructure.adapters.etf_adapter import ETFFallbackProvider
from ..infrastructure.adapters.simple_adapter import SimpleAlphaProvider

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


def _get_runtime_qlib_config() -> dict[str, Any]:
    """Return runtime qlib config through account-owned application service."""

    return get_runtime_qlib_config()


def _get_runtime_alpha_fixed_provider() -> str:
    """Return runtime fixed alpha provider through account-owned application service."""

    return get_runtime_alpha_fixed_provider()


def _derive_result_asof_date(result: AlphaResult) -> str | None:
    """Extract the most reliable as-of date from result metadata or scores."""
    metadata = result.metadata or {}
    asof_date = metadata.get("asof_date") or metadata.get("fallback_source_asof_date")
    if asof_date:
        return str(asof_date)
    for score in result.scores:
        if getattr(score, "asof_date", None):
            return score.asof_date.isoformat()
    return None


def _parse_result_date(value: object) -> date | None:
    """Parse ISO-like metadata values into dates."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_latest_available_qlib_result(
    result: AlphaResult,
    intended_trade_date: date,
) -> bool:
    """Return True when the cache row is only the delivery channel for the latest Qlib output."""
    metadata = result.metadata or {}
    if result.status != "available":
        return False
    if str(metadata.get("provider_source") or "").strip().lower() != "qlib":
        return False
    if metadata.get("fallback_mode") == "forward_fill_latest_qlib_cache":
        return False

    asof_date = (
        _parse_result_date(metadata.get("effective_asof_date"))
        or _parse_result_date(metadata.get("asof_date"))
        or _parse_result_date(metadata.get("fallback_source_asof_date"))
        or next(
            (
                getattr(score, "asof_date", None)
                for score in result.scores
                if getattr(score, "asof_date", None) is not None
            ),
            None,
        )
    )
    if asof_date is None:
        return False

    if metadata.get("trade_date_adjusted"):
        effective_trade_date = _parse_result_date(metadata.get("effective_trade_date")) or asof_date
        return asof_date == effective_trade_date

    return asof_date == intended_trade_date


def _build_reliability_notice(
    result: AlphaResult,
    intended_trade_date: date,
) -> dict[str, str] | None:
    """Build a user-facing reliability notice for degraded or unavailable Alpha results."""
    metadata = result.metadata or {}
    explicit_notice = metadata.get("reliability_notice")
    if isinstance(explicit_notice, dict) and explicit_notice.get("message"):
        return explicit_notice
    asof_date = _derive_result_asof_date(result)
    fallback_mode = metadata.get("fallback_mode")
    qlib_latest_date = metadata.get("qlib_data_latest_date")

    if not result.success:
        message = result.error_message or "当前 Alpha 数据不可用。"
        if qlib_latest_date:
            message = f"{message} 本地 Qlib 数据最新交易日为 {qlib_latest_date}。"
        return {
            "level": "error",
            "code": "alpha_unavailable",
            "title": "Alpha 当前不可用",
            "message": message,
        }

    if metadata.get("trade_date_adjusted"):
        effective_trade_date = metadata.get("effective_trade_date") or asof_date or "历史日期"
        requested_trade_date = (
            metadata.get("requested_trade_date") or intended_trade_date.isoformat()
        )
        return {
            "level": "warning",
            "code": "qlib_trade_date_adjusted",
            "title": "Alpha 当前使用最新可用交易日",
            "message": (
                f"请求交易日 {requested_trade_date} 的 Qlib 日线尚未落地，"
                f"当前展示的是截至 {effective_trade_date} 的最新可用推理结果。"
            ),
        }

    if fallback_mode == "forward_fill_latest_qlib_cache":
        return {
            "level": "warning",
            "code": "qlib_forward_filled_cache",
            "title": "Alpha 当前使用前推缓存",
            "message": (
                f"Qlib 当日推理不可用，当前展示的是 {asof_date or '历史日期'} "
                f"生成并前推到 {intended_trade_date.isoformat()} 的结果。"
            ),
        }

    if result.status == "degraded" and result.source == "cache":
        age_text = (
            f"，距请求日约 {result.staleness_days} 天" if result.staleness_days is not None else ""
        )
        return {
            "level": "warning",
            "code": "historical_cache_result",
            "title": "Alpha 当前使用历史缓存",
            "message": (f"当前展示的是 {asof_date or '未知日期'} 的缓存评分{age_text}。"),
        }

    if result.status == "degraded" and result.source == "qlib":
        age_text = (
            f"，距请求日约 {result.staleness_days} 天" if result.staleness_days is not None else ""
        )
        return {
            "level": "warning",
            "code": "degraded_qlib_result",
            "title": "Alpha 当前使用降级 Qlib 结果",
            "message": (f"当前展示的是 {asof_date or '历史日期'} 的 Qlib 结果{age_text}。"),
        }

    return None


def _enrich_result_metadata(result: AlphaResult, intended_trade_date: date) -> AlphaResult:
    """Attach reliability metadata so API, frontend, and MCP consumers can show explicit notices."""
    metadata = dict(result.metadata or {})
    asof_date = _derive_result_asof_date(result)
    notice = _build_reliability_notice(result, intended_trade_date)
    latest_available_qlib = _is_latest_available_qlib_result(result, intended_trade_date)
    uses_cached_data = (
        not latest_available_qlib
        and (
            result.source == "cache"
            or metadata.get("fallback_mode") == "forward_fill_latest_qlib_cache"
            or metadata.get("provider_source") == "cache"
        )
    )
    metadata.update(
        {
            "requested_trade_date": intended_trade_date.isoformat(),
            "effective_asof_date": asof_date,
            "is_degraded": result.status == "degraded",
            "uses_cached_data": uses_cached_data,
            "latest_available_qlib_result": latest_available_qlib,
            "reliability_notice": notice,
        }
    )
    scope_metadata = metadata.get("scope_metadata") or {}
    if scope_metadata:
        metadata.setdefault("scope_hash", scope_metadata.get("scope_hash"))
        metadata.setdefault("scope_label", scope_metadata.get("display_label"))
    result.metadata = metadata
    return result


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
        self._providers: list[AlphaProvider] = []

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

    def get_provider(self, name: str) -> AlphaProvider | None:
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

    def get_all_providers(self) -> list[AlphaProvider]:
        """
        获取所有已注册的 Provider

        Returns:
            Provider 列表（按优先级排序）
        """
        return list(self._providers)

    def get_active_providers(self) -> list[AlphaProvider]:
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
        provider_filter: str = None,
        pool_scope: AlphaPoolScope | None = None,
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
            user: 当前用户（用于 Cache Provider）
            provider_filter: 强制使用指定 Provider（禁用降级）

        Returns:
            AlphaResult
        """
        # 记录请求详情
        logger.info(
            f"[AlphaRequest] universe={universe_id}, date={intended_trade_date}, "
            f"top_n={top_n}, provider_filter={provider_filter}"
        )

        # 检查是否配置了固定 Provider
        try:
            fixed_provider = _get_runtime_alpha_fixed_provider()
            if fixed_provider and not provider_filter:
                logger.info(f"[AlphaConfig] 系统配置固定使用 Provider: {fixed_provider}")
                provider_filter = fixed_provider
        except Exception as e:
            logger.debug(f"获取固定 Provider 配置失败: {e}")

        if provider_filter:
            provider = self.get_provider(provider_filter)
            if provider is None:
                logger.warning(f"指定的 Provider '{provider_filter}' 不存在或不可用")
                return AlphaResult(
                    success=False,
                    scores=[],
                    source=provider_filter,
                    timestamp=date.today().isoformat(),
                    status="unavailable",
                    error_message=f"指定的 Provider '{provider_filter}' 不存在或不可用",
                )

            try:
                status = provider.health_check()
            except Exception as exc:
                logger.error(f"检查 Provider {provider_filter} 状态失败: {exc}")
                status = AlphaProviderStatus.UNAVAILABLE

            if status == AlphaProviderStatus.UNAVAILABLE:
                logger.warning(f"指定的 Provider '{provider_filter}' 当前不可用")
                return AlphaResult(
                    success=False,
                    scores=[],
                    source=provider_filter,
                    timestamp=date.today().isoformat(),
                    status="unavailable",
                    error_message=f"指定的 Provider '{provider_filter}' 当前不可用",
                )

            logger.info(f"[AlphaFilter] 仅使用 Provider: {provider_filter}")
            active_providers = [provider]
        else:
            active_providers = self.get_active_providers()

        if not active_providers:
            logger.warning("[AlphaRequest] 没有可用的 Provider")

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
        attempted_providers = []
        best_degraded_result: AlphaResult | None = None
        best_degraded_provider_name: str | None = None
        for i, provider in enumerate(active_providers):
            provider_start_time = time.time()
            cache_hit = False

            try:
                logger.info(
                    f"[AlphaProvider] 尝试 Provider: {provider.name} "
                    f"(priority={provider.priority}, {i + 1}/{len(active_providers)})"
                )
                attempted_providers.append(provider.name)

                # 检查是否支持该 universe
                if not self._call_provider_supports(
                    provider=provider,
                    universe_id=universe_id,
                    pool_scope=pool_scope,
                ):
                    logger.debug(f"[AlphaProvider] Provider {provider.name} 不支持 {universe_id}")
                    continue

                # 获取评分（Cache Provider 支持 user 参数）
                result = self._call_provider_get_stock_scores(
                    provider=provider,
                    universe_id=universe_id,
                    intended_trade_date=intended_trade_date,
                    top_n=top_n,
                    pool_scope=pool_scope,
                    user=user,
                )

                # 计算延迟
                latency_ms = (time.time() - provider_start_time) * 1000
                result.latency_ms = int(latency_ms)

                # 检查是否缓存命中（Cache Provider）
                cache_hit = provider.name == "cache" and result.success

                if not result.success:
                    logger.warning(
                        f"[AlphaProvider] Provider {provider.name} 返回失败: {result.error_message}"
                    )

                    # 记录失败指标
                    try:
                        metrics = get_alpha_metrics()
                        metrics.record_provider_call(
                            provider.name, success=False, latency_ms=latency_ms
                        )
                    except Exception:
                        pass

                    continue

                # 检查 staleness
                if result.staleness_days and result.staleness_days > provider.max_staleness_days:
                    logger.warning(
                        f"[AlphaProvider] Provider {provider.name} 数据过期: {result.staleness_days} 天 "
                        f"(最大允许 {provider.max_staleness_days} 天)"
                    )

                    # 标记 degraded
                    result.status = "degraded"
                    if best_degraded_result is None or (result.staleness_days or 10**9) < (
                        best_degraded_result.staleness_days or 10**9
                    ):
                        best_degraded_result = result
                        best_degraded_provider_name = provider.name

                    # 如果这是最后一个 provider，返回 degraded 结果
                    if i == len(active_providers) - 1:
                        logger.warning(
                            f"[AlphaProvider] 所有 Provider 数据过期，使用 {provider.name} 的降级结果"
                        )

                        # 创建告警
                        self._create_fallback_alert(
                            provider.name,
                            attempted_providers,
                            f"所有 Provider 数据过期，使用 {provider.name} 的降级结果",
                        )

                        # 记录指标
                        try:
                            metrics = get_alpha_metrics()
                            metrics.record_provider_call(
                                provider.name,
                                success=True,
                                latency_ms=latency_ms,
                                staleness_days=result.staleness_days,
                            )
                            if result.scores:
                                metrics.record_coverage(len(result.scores), 300)
                        except Exception:
                            pass

                        return result

                    # 否则继续尝试下一个
                    continue

                # 成功获取新鲜数据
                # 检查是否发生了降级
                if i > 0:
                    fallback_from = attempted_providers[0]
                    logger.warning(
                        f"[AlphaFallback] 从 {fallback_from} 降级到 {provider.name} "
                        f"(尝试了 {i} 个 Provider)"
                    )

                    # 创建降级告警
                    self._create_fallback_alert(
                        provider.name,
                        attempted_providers,
                        f"从 {fallback_from} 降级到 {provider.name}（原因：前序 Provider 不可用）",
                    )
                else:
                    logger.info(
                        f"[AlphaSuccess] 成功从 {provider.name} 获取 {len(result.scores)} 只股票评分 "
                        f"(latency={latency_ms:.0f}ms, staleness={result.staleness_days}天)"
                    )

                # 记录成功指标
                try:
                    metrics = get_alpha_metrics()
                    metrics.record_provider_call(
                        provider.name,
                        success=True,
                        latency_ms=latency_ms,
                        staleness_days=result.staleness_days,
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
                logger.error(
                    f"[AlphaProvider] Provider {provider.name} 调用失败: {e}", exc_info=True
                )

                # 记录异常指标
                try:
                    metrics = get_alpha_metrics()
                    metrics.record_provider_call(
                        provider.name, success=False, latency_ms=latency_ms
                    )
                except Exception:
                    pass

                continue

        if best_degraded_result is not None and best_degraded_provider_name is not None:
            logger.warning(
                f"[AlphaFallback] 所有更新鲜 Provider 均失败，回退到 {best_degraded_provider_name} "
                f"的过期结果 (staleness={best_degraded_result.staleness_days}天)"
            )
            self._create_fallback_alert(
                best_degraded_provider_name,
                attempted_providers,
                (
                    f"所有更新鲜 Provider 均失败，回退到 {best_degraded_provider_name} "
                    f"的过期结果"
                ),
            )

            try:
                metrics = get_alpha_metrics()
                metrics.record_provider_call(
                    best_degraded_provider_name,
                    success=True,
                    latency_ms=best_degraded_result.latency_ms or 0,
                    staleness_days=best_degraded_result.staleness_days,
                )
                if best_degraded_result.scores:
                    metrics.record_coverage(len(best_degraded_result.scores), 300)
            except Exception:
                pass

            return best_degraded_result

        # 所有 provider 都失败
        logger.error(f"[AlphaFailed] 所有 Provider 失败，尝试顺序: {attempted_providers}")

        # 创建严重告警
        try:
            get_alpha_alert_repository().create_alert(
                alert_type="provider_unavailable",
                severity="error",
                title="所有 Alpha Provider 不可用",
                message=f"尝试顺序: {', '.join(attempted_providers)}",
                metadata={
                    "universe_id": universe_id,
                    "intended_trade_date": intended_trade_date.isoformat(),
                    "attempted_providers": attempted_providers,
                },
            )
        except Exception as e:
            logger.debug(f"创建告警失败: {e}")

        return AlphaResult(
            success=False,
            scores=[],
            source="none",
            timestamp=date.today().isoformat(),
            status="unavailable",
            error_message="所有 Alpha Provider 失败或数据过期",
        )

    def _call_provider_get_stock_scores(
        self,
        *,
        provider: AlphaProvider,
        universe_id: str,
        intended_trade_date: date,
        top_n: int,
        pool_scope: AlphaPoolScope | None,
        user,
    ) -> AlphaResult:
        """Call providers with only the optional context parameters they support."""
        signature = inspect.signature(provider.get_stock_scores)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        kwargs: dict[str, Any] = {}
        if accepts_kwargs or "pool_scope" in parameters:
            kwargs["pool_scope"] = pool_scope
        if accepts_kwargs or "user" in parameters:
            kwargs["user"] = user
        return provider.get_stock_scores(
            universe_id,
            intended_trade_date,
            top_n,
            **kwargs,
        )

    def _call_provider_supports(
        self,
        *,
        provider: AlphaProvider,
        universe_id: str,
        pool_scope: AlphaPoolScope | None,
    ) -> bool:
        """Call provider.supports with optional pool scope only when supported."""
        signature = inspect.signature(provider.supports)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        if accepts_kwargs or "pool_scope" in parameters:
            return provider.supports(universe_id, pool_scope=pool_scope)
        return provider.supports(universe_id)

    def _create_fallback_alert(
        self, current_provider: str, attempted_providers: list, reason: str
    ) -> None:
        """
        创建 Provider 降级告警

        Args:
            current_provider: 当前使用的 Provider
            attempted_providers: 尝试过的 Provider 列表
            reason: 降级原因
        """
        try:
            alert_repository = get_alpha_alert_repository()
            # 检查是否已有相同告警（避免重复）
            recent_alert = alert_repository.get_open_alert(alert_type="model_degraded")

            # 如果有未解决的降级告警，更新它；否则创建新的
            if recent_alert:
                alert_repository.update_alert(
                    alert_id=recent_alert.id,
                    message=reason,
                    metadata={
                        "current_provider": current_provider,
                        "attempted_providers": attempted_providers,
                        "alert_updated_at": timezone.now().isoformat(),
                    },
                )
                logger.info(f"[AlphaAlert] 更新降级告警: {reason}")
            else:
                alert_repository.create_alert(
                    alert_type="model_degraded",
                    severity="warning",
                    title="Alpha Provider 降级",
                    message=reason,
                    metadata={
                        "current_provider": current_provider,
                        "attempted_providers": attempted_providers,
                    },
                )
                logger.warning(f"[AlphaAlert] 创建降级告警: {reason}")
        except Exception as e:
            logger.debug(f"创建降级告警失败: {e}")


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

            qlib_config = _get_runtime_qlib_config()
            if qlib_config.get("enabled"):
                qlib_provider = QlibAlphaProvider(
                    provider_uri=qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data"),
                    model_path=qlib_config.get("model_path", "/models/qlib"),
                    region=qlib_config.get("region", "CN"),
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
        intended_trade_date: date | None = None,
        top_n: int = 30,
        user=None,
        provider_filter: str | None = None,
        pool_scope: AlphaPoolScope | None = None,
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

        result = self._registry.get_scores_with_fallback(
            effective_universe_id,
            intended_trade_date,
            top_n,
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

        return _enrich_result_metadata(result, intended_trade_date)

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

    def get_provider_status(self) -> dict[str, dict[str, str]]:
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
                if hasattr(provider, "_last_health_message") and provider._last_health_message:
                    provider_info["message"] = provider._last_health_message
                status[provider.name] = provider_info
            except Exception as e:
                status[provider.name] = {
                    "priority": provider.priority,
                    "status": "error",
                    "error": str(e),
                }

        return status

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
