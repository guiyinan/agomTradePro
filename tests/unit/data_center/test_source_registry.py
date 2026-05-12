"""
Unit tests for SourceRegistry — priority, failover, circuit-breaker.
"""


from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus
from apps.data_center.infrastructure.registries.source_registry import (
    _CIRCUIT_OPEN_THRESHOLD,
    SourceRegistry,
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSourceRegistryPriority:
    def test_register_and_get(self):
        reg = SourceRegistry()
        p = _StubProvider("p1", [DataCapability.MACRO])
        reg.register(p, priority=10)
        assert reg.get_provider(DataCapability.MACRO) is p

    def test_higher_priority_returned_first(self):
        reg = SourceRegistry()
        p_low = _StubProvider("p_low", [DataCapability.MACRO])
        p_high = _StubProvider("p_high", [DataCapability.MACRO])
        reg.register(p_low, priority=50)
        reg.register(p_high, priority=10)
        assert reg.get_provider(DataCapability.MACRO) is p_high

    def test_get_providers_returns_all(self):
        reg = SourceRegistry()
        p1 = _StubProvider("p1", [DataCapability.CAPITAL_FLOW])
        p2 = _StubProvider("p2", [DataCapability.CAPITAL_FLOW])
        reg.register(p1, priority=20)
        reg.register(p2, priority=10)
        providers = reg.get_providers(DataCapability.CAPITAL_FLOW)
        assert providers[0] is p2
        assert providers[1] is p1

    def test_unknown_capability_returns_none(self):
        reg = SourceRegistry()
        assert reg.get_provider(DataCapability.NEWS) is None
        assert reg.get_providers(DataCapability.NEWS) == []


class TestSourceRegistryFailover:
    def test_failover_skips_failed_provider(self):
        reg = SourceRegistry()
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
        reg = SourceRegistry()
        p = _StubProvider("p", [DataCapability.HISTORICAL_PRICE])
        reg.register(p, priority=10)

        result = reg.call_with_failover(
            DataCapability.HISTORICAL_PRICE, lambda _: None
        )
        assert result is None

    def test_empty_list_result_treated_as_failure(self):
        reg = SourceRegistry()
        p1 = _StubProvider("empty", [DataCapability.MACRO])
        p2 = _StubProvider("full", [DataCapability.MACRO])
        reg.register(p1, priority=10)
        reg.register(p2, priority=20)

        result = reg.call_with_failover(
            DataCapability.MACRO,
            lambda prov: [] if prov.provider_name() == "empty" else ["row"],
        )
        assert result == ["row"]


class TestSourceRegistryCircuitBreaker:
    def test_circuit_opens_after_threshold(self):
        reg = SourceRegistry()
        p = _StubProvider("flaky", [DataCapability.FUND_NAV])
        reg.register(p, priority=10)

        # Fail threshold times
        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            reg.record_failure("flaky", DataCapability.FUND_NAV)

        # Provider is now circuit-open → not available
        assert reg.get_provider(DataCapability.FUND_NAV) is None

    def test_healthy_provider_not_circuit_open(self):
        reg = SourceRegistry()
        p = _StubProvider("healthy", [DataCapability.NEWS])
        reg.register(p, priority=10)
        assert reg.get_provider(DataCapability.NEWS) is p

    def test_success_resets_failure_count(self):
        reg = SourceRegistry()
        p = _StubProvider("recoverable", [DataCapability.VALUATION])
        reg.register(p, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD - 1):
            reg.record_failure("recoverable", DataCapability.VALUATION)

        reg.record_success("recoverable", DataCapability.VALUATION, 10.0)
        # Should still be available after a success resets failures
        assert reg.get_provider(DataCapability.VALUATION) is p


class TestSourceRegistryHealthSnapshots:
    def test_get_all_statuses_empty(self):
        reg = SourceRegistry()
        assert reg.get_all_statuses() == []

    def test_get_all_statuses_returns_snapshots(self):
        reg = SourceRegistry()
        p = _StubProvider("p", [DataCapability.MACRO, DataCapability.NEWS])
        reg.register(p, priority=10)
        statuses = reg.get_all_statuses()
        capabilities = {s.capability for s in statuses}
        assert DataCapability.MACRO in capabilities
        assert DataCapability.NEWS in capabilities

    def test_snapshot_healthy_by_default(self):
        reg = SourceRegistry()
        p = _StubProvider("fresh", [DataCapability.SECTOR_MEMBERSHIP])
        reg.register(p, priority=10)
        snaps = reg.get_all_statuses()
        assert all(s.status == ProviderHealthStatus.HEALTHY for s in snaps)
