"""
SourceRegistry 测试

测试 provider 注册、优先级、failover、熔断。
"""

import pytest
from typing import List, Optional
from unittest.mock import patch

from apps.market_data.domain.entities import QuoteSnapshot, CapitalFlowSnapshot
from apps.market_data.domain.enums import DataCapability, ProviderHealth
from apps.market_data.domain.protocols import MarketDataProviderProtocol
from apps.market_data.infrastructure.registries.source_registry import (
    SourceRegistry,
    _CIRCUIT_OPEN_THRESHOLD,
)


class FakeProvider(MarketDataProviderProtocol):
    """测试用 fake provider"""

    def __init__(self, name: str, capabilities: set):
        self._name = name
        self._capabilities = capabilities

    def provider_name(self) -> str:
        return self._name

    def supports(self, capability: DataCapability) -> bool:
        return capability in self._capabilities


class TestSourceRegistry:
    def test_register_and_get_provider(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        result = registry.get_provider(DataCapability.REALTIME_QUOTE)
        assert result is not None
        assert result.provider_name() == "p1"

    def test_get_provider_returns_none_for_unregistered(self):
        registry = SourceRegistry()
        assert registry.get_provider(DataCapability.CAPITAL_FLOW) is None

    def test_priority_ordering(self):
        registry = SourceRegistry()
        p1 = FakeProvider("low_priority", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("high_priority", {DataCapability.REALTIME_QUOTE})

        registry.register(p1, priority=100)
        registry.register(p2, priority=10)

        result = registry.get_provider(DataCapability.REALTIME_QUOTE)
        assert result.provider_name() == "high_priority"

    def test_get_providers_returns_all(self):
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})

        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        providers = registry.get_providers(DataCapability.REALTIME_QUOTE)
        assert len(providers) == 2
        assert providers[0].provider_name() == "p1"
        assert providers[1].provider_name() == "p2"

    def test_record_success(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        registry.record_success("p1", DataCapability.REALTIME_QUOTE, 50.0)
        statuses = registry.get_all_statuses()
        assert len(statuses) == 1
        assert statuses[0].is_healthy is True
        assert statuses[0].consecutive_failures == 0

    def test_record_failure_increments(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        registry.record_failure("p1", DataCapability.REALTIME_QUOTE)
        registry.record_failure("p1", DataCapability.REALTIME_QUOTE)

        statuses = registry.get_all_statuses()
        assert statuses[0].consecutive_failures == 2

    def test_circuit_breaker_opens(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            registry.record_failure("p1", DataCapability.REALTIME_QUOTE)

        # Provider should be unavailable (circuit open)
        result = registry.get_provider(DataCapability.REALTIME_QUOTE)
        assert result is None

    def test_circuit_breaker_recovery(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            registry.record_failure("p1", DataCapability.REALTIME_QUOTE)

        # Simulate time passing beyond circuit open duration
        state = registry._find_state("p1", DataCapability.REALTIME_QUOTE)
        state.circuit_open_until = 0  # Already expired

        result = registry.get_provider(DataCapability.REALTIME_QUOTE)
        assert result is not None

    def test_success_resets_failure_count(self):
        registry = SourceRegistry()
        provider = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(provider, priority=10)

        registry.record_failure("p1", DataCapability.REALTIME_QUOTE)
        registry.record_failure("p1", DataCapability.REALTIME_QUOTE)
        registry.record_success("p1", DataCapability.REALTIME_QUOTE, 10.0)

        statuses = registry.get_all_statuses()
        assert statuses[0].consecutive_failures == 0

    def test_multi_capability_provider(self):
        registry = SourceRegistry()
        provider = FakeProvider(
            "multi",
            {DataCapability.REALTIME_QUOTE, DataCapability.CAPITAL_FLOW},
        )
        registry.register(provider, priority=10)

        assert registry.get_provider(DataCapability.REALTIME_QUOTE) is not None
        assert registry.get_provider(DataCapability.CAPITAL_FLOW) is not None
        assert registry.get_provider(DataCapability.STOCK_NEWS) is None

    def test_multi_capability_failure_is_isolated_per_capability(self):
        registry = SourceRegistry()
        provider = FakeProvider(
            "multi",
            {DataCapability.REALTIME_QUOTE, DataCapability.CAPITAL_FLOW},
        )
        registry.register(provider, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            registry.record_failure("multi", DataCapability.CAPITAL_FLOW)

        assert registry.get_provider(DataCapability.CAPITAL_FLOW) is None
        assert registry.get_provider(DataCapability.REALTIME_QUOTE) is not None

        quote_state = registry._find_state("multi", DataCapability.REALTIME_QUOTE)
        flow_state = registry._find_state("multi", DataCapability.CAPITAL_FLOW)
        assert quote_state is not flow_state
        assert quote_state.consecutive_failures == 0
        assert flow_state.consecutive_failures == _CIRCUIT_OPEN_THRESHOLD

    def test_failover_to_next_provider(self):
        registry = SourceRegistry()
        p1 = FakeProvider("primary", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("fallback", {DataCapability.REALTIME_QUOTE})

        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        # Circuit-break primary
        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            registry.record_failure("primary", DataCapability.REALTIME_QUOTE)

        # Should fall back to secondary
        result = registry.get_provider(DataCapability.REALTIME_QUOTE)
        assert result is not None
        assert result.provider_name() == "fallback"


class TestCallWithFailover:
    """测试 call_with_failover: 一个源挂了自动用下一个"""

    def test_first_provider_succeeds(self):
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)

        result = registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda p: ["data_from_" + p.provider_name()],
        )
        assert result == ["data_from_p1"]

    def test_first_provider_exception_falls_to_second(self):
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        call_count = {"n": 0}

        def fn(provider):
            call_count["n"] += 1
            if provider.provider_name() == "p1":
                raise ConnectionError("network down")
            return ["data_from_" + provider.provider_name()]

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result == ["data_from_p2"]
        assert call_count["n"] == 2

    def test_first_provider_empty_falls_to_second(self):
        """第一个源返回空列表 → 自动尝试第二个"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        def fn(provider):
            if provider.provider_name() == "p1":
                return []  # 空结果
            return ["data"]

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result == ["data"]

    def test_first_returns_none_falls_to_second(self):
        """第一个源返回 None → 自动尝试第二个"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        def fn(provider):
            if provider.provider_name() == "p1":
                return None
            return ["ok"]

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result == ["ok"]

    def test_all_providers_fail_returns_none(self):
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        def fn(provider):
            raise Exception("broken")

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result is None

    def test_all_providers_return_empty_returns_none(self):
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        result = registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda p: [],
        )
        assert result is None

    def test_no_providers_returns_none(self):
        registry = SourceRegistry()
        result = registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda p: ["data"],
        )
        assert result is None

    def test_skips_circuit_broken_provider(self):
        """已熔断的 provider 被跳过，直接用下一个"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        # 把 p1 熔断
        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            registry.record_failure("p1", DataCapability.REALTIME_QUOTE)

        called_providers = []

        def fn(provider):
            called_providers.append(provider.provider_name())
            return ["data"]

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result == ["data"]
        # p1 被跳过，只调了 p2
        assert called_providers == ["p2"]

    def test_failure_increments_counter(self):
        """call_with_failover 中的失败会记录到熔断器"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)

        def fn(provider):
            if provider.provider_name() == "p1":
                raise Exception("fail")
            return ["ok"]

        registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)

        state = registry._find_state("p1", DataCapability.REALTIME_QUOTE)
        assert state.consecutive_failures == 1

    def test_success_records_latency(self):
        """成功调用会记录延迟"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)

        registry.call_with_failover(
            DataCapability.REALTIME_QUOTE,
            lambda p: ["data"],
        )

        state = registry._find_state("p1", DataCapability.REALTIME_QUOTE)
        assert state.total_calls == 1
        assert state.total_failures == 0
        assert state.total_latency_ms > 0

    def test_three_providers_first_two_fail(self):
        """三个源，前两个挂了，第三个能用"""
        registry = SourceRegistry()
        p1 = FakeProvider("p1", {DataCapability.REALTIME_QUOTE})
        p2 = FakeProvider("p2", {DataCapability.REALTIME_QUOTE})
        p3 = FakeProvider("p3", {DataCapability.REALTIME_QUOTE})
        registry.register(p1, priority=10)
        registry.register(p2, priority=20)
        registry.register(p3, priority=30)

        def fn(provider):
            if provider.provider_name() in ("p1", "p2"):
                raise Exception("down")
            return ["from_p3"]

        result = registry.call_with_failover(DataCapability.REALTIME_QUOTE, fn)
        assert result == ["from_p3"]
