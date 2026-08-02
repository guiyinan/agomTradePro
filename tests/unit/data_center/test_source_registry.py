"""
Unit tests for ProviderRegistry — priority, failover, circuit-breaker.
"""

import logging

import pytest

from apps.data_center import provider_runtime
from apps.data_center.domain.contracts import (
    DatasetKey,
    FetchOutcome,
    FetchResult,
    QualityAssessment,
    SourceEvidence,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus
from apps.data_center.infrastructure.provider_registry import (
    _CIRCUIT_OPEN_THRESHOLD,
    ProviderRegistry,
)
from shared.domain.reliability import ReliabilityContract, ReliabilityStatus

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

        result = reg.call_with_failover(DataCapability.HISTORICAL_PRICE, lambda _: None)
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

    def test_validator_rejects_stale_result_and_tries_next_provider(self):
        reg = ProviderRegistry()
        stale = _StubProvider("stale", [DataCapability.MACRO])
        fresh = _StubProvider("fresh", [DataCapability.MACRO])
        reg.register(stale, priority=10)
        reg.register(fresh, priority=20)

        result = reg.call_with_failover(
            DataCapability.MACRO,
            lambda provider: {"provider": provider.provider_name()},
            validator=lambda payload: payload["provider"] == "fresh",
        )

        assert result == {"provider": "fresh"}

    def test_unpublishable_fetch_result_is_rejected_before_validator(self):
        reg = ProviderRegistry()
        blocked = _StubProvider("blocked", [DataCapability.MACRO])
        reg.register(blocked, priority=10)
        dataset = DatasetKey("macro.fact", "1", "1")
        evidence = SourceEvidence.from_payload(
            source="blocked", source_capability="macro", payload={"value": 1}
        )
        blocked_result = FetchResult(
            outcome=FetchOutcome.BLOCKED,
            values=(),
            provider="blocked",
            dataset=dataset,
            evidence=evidence,
            reliability=ReliabilityContract.blocked(
                status=ReliabilityStatus.FAILED,
                source="blocked",
                reason_code="provider_blocked",
                reason="provider returned no publishable result",
            ),
            quality=QualityAssessment(True, 0.0, True, True),
            error_code="provider_blocked",
            error_message="provider returned no publishable result",
        )

        assert reg.call_with_failover(DataCapability.MACRO, lambda _: blocked_result) is None

    def test_empty_list_opens_provider_circuit_after_repeated_zero_output(self):
        """Repeated zero-output responses are capability-health failures."""

        reg = ProviderRegistry()
        provider = _StubProvider("empty", [DataCapability.MACRO])
        reg.register(provider, priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            assert reg.call_with_failover(DataCapability.MACRO, lambda _: []) is None

        assert reg.get_provider(DataCapability.MACRO) is None
        snapshot = reg.get_all_statuses()[0]
        assert snapshot.status is ProviderHealthStatus.CIRCUIT_OPEN
        assert snapshot.consecutive_failures == _CIRCUIT_OPEN_THRESHOLD

    def test_none_result_opens_provider_circuit(self):
        """A None result violates the provider contract and remains a health failure."""

        reg = ProviderRegistry()
        reg.register(_StubProvider("invalid", [DataCapability.MACRO]), priority=10)

        for _ in range(_CIRCUIT_OPEN_THRESHOLD):
            assert reg.call_with_failover(DataCapability.MACRO, lambda _: None) is None

        assert reg.get_provider(DataCapability.MACRO) is None

    def test_provider_exception_log_does_not_disclose_error_text(self, caplog):
        """Provider failures retain exception type but suppress credential-bearing text."""

        reg = ProviderRegistry()
        reg.register(_StubProvider("bad", [DataCapability.MACRO]), priority=10)

        def fail(_provider):
            raise RuntimeError("api_key=should-not-appear")

        with caplog.at_level(logging.WARNING):
            assert reg.call_with_failover(DataCapability.MACRO, fail) is None

        assert "RuntimeError" in caplog.text
        assert "should-not-appear" not in caplog.text


class TestProviderRegistryRefresh:
    def test_failed_staged_refresh_preserves_existing_provider(self):
        """All adapter build failures leave the last viable runtime state intact."""

        existing = _StubProvider("existing", [DataCapability.MACRO])

        def fail_builder(_config):
            raise RuntimeError("build failed")

        reg = ProviderRegistry(builder=fail_builder)
        reg.register(existing, priority=10)
        config = ProviderConfig(
            id=8,
            name="replacement",
            source_type="tushare",
            is_active=True,
            priority=5,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )

        with pytest.raises(RuntimeError, match="No active Data Center provider"):
            reg.refresh_from_repository(_ProviderConfigRepository([config]))

        assert reg.get_provider(DataCapability.MACRO) is existing

    def test_global_refresh_failure_keeps_existing_registry_and_sanitizes_log(
        self,
        monkeypatch,
        caplog,
    ):
        """A repository outage cannot replace the process registry with an empty one."""

        existing_registry = ProviderRegistry()
        existing = _StubProvider("existing", [DataCapability.MACRO])
        existing_registry.register(existing, priority=10)
        monkeypatch.setattr(provider_runtime, "_global_registry", existing_registry)
        monkeypatch.setattr(
            provider_runtime,
            "get_provider_config_repository",
            lambda: object(),
        )

        def fail_refresh(_cls, _repository):
            raise RuntimeError("password=should-not-appear")

        monkeypatch.setattr(
            provider_runtime.ProviderRegistry,
            "from_repository",
            classmethod(fail_refresh),
        )

        with caplog.at_level(logging.WARNING):
            refreshed = provider_runtime.refresh_registry()

        assert refreshed is existing_registry
        assert refreshed.get_provider(DataCapability.MACRO) is existing
        assert "RuntimeError" in caplog.text
        assert "should-not-appear" not in caplog.text


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
