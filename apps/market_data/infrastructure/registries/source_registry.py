"""
Market Data Source Registry

统一由注册表分发 provider，按能力注册，不按站点写死。
支持优先级、健康检查、熔断、failover。
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timezone
from typing import Dict, List, Optional, TypeVar

from apps.market_data.domain.entities import ProviderStatus
from apps.market_data.domain.enums import DataCapability, ProviderHealth
from apps.market_data.domain.protocols import MarketDataProviderProtocol

T = TypeVar("T")

logger = logging.getLogger(__name__)

# 连续失败次数阈值 → 触发熔断
_CIRCUIT_OPEN_THRESHOLD = 5
# 熔断恢复等待时间（秒）
_CIRCUIT_OPEN_DURATION_SEC = 300


class _ProviderState:
    """单个 provider 在单个 capability 下的运行时状态"""

    def __init__(
        self,
        provider: MarketDataProviderProtocol,
        priority: int,
        capability: DataCapability,
    ) -> None:
        self.provider = provider
        self.priority = priority
        self.capability = capability
        self.consecutive_failures: int = 0
        self.last_success_at: datetime | None = None
        self.circuit_open_until: float | None = None
        self.total_calls: int = 0
        self.total_failures: int = 0
        self.total_latency_ms: float = 0.0

    @property
    def health(self) -> ProviderHealth:
        if self.circuit_open_until and time.monotonic() < self.circuit_open_until:
            return ProviderHealth.CIRCUIT_OPEN
        if self.consecutive_failures > 0:
            return ProviderHealth.DEGRADED
        return ProviderHealth.HEALTHY

    @property
    def is_available(self) -> bool:
        """provider 是否可用（未熔断或熔断已到期）"""
        if self.circuit_open_until is None:
            return True
        return time.monotonic() >= self.circuit_open_until

    def record_success(self, latency_ms: float) -> None:
        self.consecutive_failures = 0
        self.last_success_at = datetime.now(UTC)
        self.circuit_open_until = None
        self.total_calls += 1
        self.total_latency_ms += latency_ms

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.total_calls += 1
        self.total_failures += 1
        if self.consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
            self.circuit_open_until = (
                time.monotonic() + _CIRCUIT_OPEN_DURATION_SEC
            )
            logger.warning(
                "Provider %s 熔断开启（连续失败 %d 次），%d 秒后恢复",
                self.provider.provider_name(),
                self.consecutive_failures,
                _CIRCUIT_OPEN_DURATION_SEC,
            )

    def to_status(self, capability: str) -> ProviderStatus:
        avg_latency = None
        if self.total_calls > self.total_failures:
            avg_latency = self.total_latency_ms / (
                self.total_calls - self.total_failures
            )
        return ProviderStatus(
            provider_name=self.provider.provider_name(),
            capability=capability,
            is_healthy=self.health == ProviderHealth.HEALTHY,
            last_success_at=self.last_success_at,
            consecutive_failures=self.consecutive_failures,
            avg_latency_ms=avg_latency,
        )


class SourceRegistry:
    """数据源注册表

    按能力管理 providers，支持：
    - 优先级排序
    - 自动 failover
    - 熔断与恢复
    - 健康状态查询

    Usage:
        registry = SourceRegistry()
        registry.register(eastmoney_provider, priority=10)
        registry.register(tushare_provider, priority=20)

        provider = registry.get_provider(DataCapability.REALTIME_QUOTE)
    """

    def __init__(self) -> None:
        # capability → [_ProviderState] (按 priority 排序，小值优先)
        self._registry: dict[DataCapability, list[_ProviderState]] = {}

    def register(
        self,
        provider: MarketDataProviderProtocol,
        priority: int = 100,
    ) -> None:
        """注册一个 provider

        provider 通过 supports() 声明自己支持的能力，
        自动注册到对应的能力列表中。

        Args:
            provider: 实现了 MarketDataProviderProtocol 的 provider
            priority: 优先级（数字越小越优先）
        """
        for capability in DataCapability:
            if provider.supports(capability):
                state = _ProviderState(provider, priority, capability)
                if capability not in self._registry:
                    self._registry[capability] = []
                self._registry[capability].append(state)
                self._registry[capability].sort(key=lambda s: s.priority)
                logger.info(
                    "注册 provider: %s → %s (priority=%d)",
                    provider.provider_name(),
                    capability.value,
                    priority,
                )

    def get_provider(
        self, capability: DataCapability
    ) -> MarketDataProviderProtocol | None:
        """获取某能力的最高优先可用 provider"""
        states = self._registry.get(capability, [])
        for state in states:
            if state.is_available:
                return state.provider
        return None

    def get_providers(
        self, capability: DataCapability
    ) -> list[MarketDataProviderProtocol]:
        """获取某能力的所有可用 providers（按优先级排序）"""
        states = self._registry.get(capability, [])
        return [s.provider for s in states if s.is_available]

    def record_success(
        self, provider_name: str, capability: DataCapability, latency_ms: float
    ) -> None:
        """记录一次成功调用"""
        state = self._find_state(provider_name, capability)
        if state:
            state.record_success(latency_ms)

    def record_failure(
        self, provider_name: str, capability: DataCapability
    ) -> None:
        """记录一次失败调用"""
        state = self._find_state(provider_name, capability)
        if state:
            state.record_failure()

    def call_with_failover(
        self,
        capability: DataCapability,
        fn: Callable[[MarketDataProviderProtocol], T],
    ) -> T | None:
        """对某能力的所有可用 provider 依次调用 fn，直到成功为止。

        成功 = fn 返回非空（非 None、非空列表）结果。
        失败 = fn 抛异常或返回空结果。

        每次成功/失败自动记录到熔断器。

        Args:
            capability: 需要的数据能力
            fn: 接收 provider 并返回结果的回调

        Returns:
            第一个成功的结果，或全部失败时返回 None
        """
        states = self._registry.get(capability, [])
        for state in states:
            if not state.is_available:
                continue
            provider = state.provider
            t0 = time.monotonic()
            try:
                result = fn(provider)
                # 将空列表视为失败（数据源返回了空）
                if result is None or (isinstance(result, list) and len(result) == 0):
                    state.record_failure()
                    logger.info(
                        "Provider %s 对 %s 返回空结果，尝试下一个",
                        provider.provider_name(),
                        capability.value,
                    )
                    continue
                latency_ms = (time.monotonic() - t0) * 1000
                state.record_success(latency_ms)
                return result
            except Exception:
                state.record_failure()
                logger.warning(
                    "Provider %s 对 %s 调用异常，尝试下一个",
                    provider.provider_name(),
                    capability.value,
                    exc_info=True,
                )
                continue
        logger.error("所有 provider 均失败: %s", capability.value)
        return None

    def get_all_statuses(self) -> list[ProviderStatus]:
        """获取所有 provider 状态"""
        statuses: list[ProviderStatus] = []
        for capability, states in self._registry.items():
            for state in states:
                statuses.append(state.to_status(capability.value))
        return statuses

    def _find_state(
        self, provider_name: str, capability: DataCapability
    ) -> _ProviderState | None:
        states = self._registry.get(capability, [])
        for state in states:
            if state.provider.provider_name() == provider_name:
                return state
        return None
