"""
Unit tests for ProviderRegistry — priority, failover, circuit-breaker.
"""


from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus
from apps.data_center.infrastructure.provider_registry import (
    _CIRCUIT_OPEN_THRESHOLD,
    ProviderRegistry,
)

# ---------------------------------------------------------------------------
# Stub provider for testing
# ---------------------------------------------------------------------------

class _StubProvider:
    def __init__(self, name: str, capabilities: list[DataCapability]) -> None:
        self._name = name
        self._caps = set(capabilities)

    def provider_name(self) -> str:
        return self._name

    def supports(self, cap: DataCapability) -> bool:
        return cap in self._caps


class _ProviderConfigRepository:
    def __init__(self, configs: list[ProviderConfig]) -> None:
        self._configs = configs

    def list_active(self) -> list[ProviderConfig]:
        return list(self._configs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProviderRegistryPriority:
    def test_repository_build_registers_real_provider_for_lookup_and_routing(self):
        config = ProviderConfig(
            id=7,
            name="macro-primary",
            source_type="akshare",
            is_active=True,
            priority=5,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )
        provider = _StubProvider("macro-primary", [DataCapability.MACRO])
        registry = ProviderRegistry.from_repository(
            _ProviderConfigRepository([config]),
            builder=lambda _: provider,
        )

        assert registry.get_by_id(7) is provider
        assert registry.get_by_name("macro-primary") is provider
        assert registry.get_provider(DataCapability.MACRO) is provider

    def test_register_and_get(self):
        reg = ProviderRegistry()
        p = _StubProvider("p1", [DataCapability.MACRO])
        reg.register(p, priority=10)
        assert reg.get_provider(DataCapability.MACRO) is p

    def test_higher_priority_returned_first(self):
        reg = ProviderRegistry()
        p_low = _StubProvider("p_low", [DataCapability.MACRO])
        p_high = _StubProvider("p_high", [DataCapability.MACRO])
        reg.register(p_low, priority=50)
        reg.register(p_high, priority=10)
        assert reg.get_provider(DataCapability.MACRO) is p_high

    def test_get_providers_returns_all(self):
        reg = ProviderRegistry()
        p1 = _StubProvider("p1", [DataCapability.CAPITAL_FLOW])
        p2 = _StubProvider("p2", [DataCapability.CAPITAL_FLOW])
        reg.register(p1, priority=20)
        reg.register(p2, priority=10)
        providers = reg.get_providers(DataCapability.CAPITAL_FLOW)
        assert providers[0] is p2
        assert providers[1] is p1

    def test_unknown_capability_returns_none(self):
        reg = ProviderRegistry()
        assert reg.get_provider(DataCapability.NEWS) is None
        assert reg.get_providers(DataCapability.NEWS) == []


class TestProviderRegistryFailover:
    def test_failover_skips_failed_provider(self):
        reg = ProviderRegistry()
        p_bad = _StubProvider("bad", [DataCapability.MACRO])
        p_good = _StubProvider("good", [DataCapability.MACRO])
        reg.register(p_bad, priority=10)
        reg.register(p_good, priority=20)

        call_order: list[str] = []

        def fetch(provider):
            call_order.append(provider.provider_name())
            if provider.provider_name() == "bad":
                raise RuntimeError("simulated failure")
            return ["data"]

        result = reg.call_with_failover(DataCapability.MACRO, fetch)
        assert result == ["data"]
        assert call_order == ["bad", "good"]

    def test_failover_returns_none_if_all_fail(self):
        reg = ProviderRegistry()
        p = _StubProvider("p", [DataCapability.HISTORICAL_PRICE])
        reg.register(p, priority=10)

        result = reg.call_with_failover(
            DataCapability.HISTORICAL_PRICE, lambda _: None
        )
        assert result is None

    def test_empty_list_result_treated_as_failure(self):
        reg = ProviderRegistry()
        p1 = _StubProvider("empty", [DataCapability.MACRO])
        p2 = _StubProvider("full", [DataCapability.MACRO])
        reg.register(p1, priority=10)
        reg.register(p2, priority=20)

        result = reg.call_with_failover(
            DataCapability.MACRO,
            lambda prov: [] if prov.provider_name() == "empty" else ["row"],
        )
        assert result == ["row"]


class TestProviderRegistryCircuitBreaker:
    def test_circuit_opens_after_threshold(self):
        reg = ProviderRegistry()
        p = _StubProvider("flaky", [DataCapability.FUND_NAV])
        reg.register(p, priority=10)

        # Fail threshold times
        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            reg.record_failure("flaky", DataCapability.FUND_NAV)

        # Provider is now circuit-open → not available
        assert reg.get_provider(DataCapability.FUND_NAV) is None

    def test_healthy_provider_not_circuit_open(self):
        reg = ProviderRegistry()
        p = _StubProvider("healthy", [DataCapability.NEWS])
        reg.register(p, priority=10)
        assert reg.get_provider(DataCapability.NEWS) is p

    def test_success_resets_failure_count(self):
        reg = ProviderRegistry()
        p = _StubProvider("recoverable", [DataCapability.VALUATION])
        reg.register(p, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD - 1):
            reg.record_failure("recoverable", DataCapability.VALUATION)

        reg.record_success("recoverable", DataCapability.VALUATION, 10.0)
        # Should still be available after a success resets failures
        assert reg.get_provider(DataCapability.VALUATION) is p


class TestProviderRegistryHealthSnapshots:
    def test_get_all_statuses_empty(self):
        reg = ProviderRegistry()
        assert reg.get_all_statuses() == []

    def test_get_all_statuses_returns_snapshots(self):
        reg = ProviderRegistry()
        p = _StubProvider("p", [DataCapability.MACRO, DataCapability.NEWS])
        reg.register(p, priority=10)
        statuses = reg.get_all_statuses()
        capabilities = {s.capability for s in statuses}
        assert DataCapability.MACRO in capabilities
        assert DataCapability.NEWS in capabilities

    def test_snapshot_healthy_by_default(self):
        reg = ProviderRegistry()
        p = _StubProvider("fresh", [DataCapability.SECTOR_MEMBERSHIP])
        reg.register(p, priority=10)
        snaps = reg.get_all_statuses()
        assert all(s.status == ProviderHealthStatus.HEALTHY for s in snaps)
