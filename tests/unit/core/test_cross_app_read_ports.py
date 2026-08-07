"""Contracts for app-neutral Config/Data Center composition bridges."""

from __future__ import annotations

from core.integration import config_center_runtime, data_center_readiness


class _ConfigCenterRuntimeProvider:
    def get_active_runtime_value(
        self,
        *,
        environment: str,
        definition_key: str,
    ) -> object | None:
        return {
            ("production", "data_center.provider.enable_failover"): True,
        }.get((environment, definition_key))

    def evaluate_storage_pressure(
        self,
        *,
        used_bytes: int,
        actual_capacity_bytes: int | None = None,
    ) -> dict[str, object]:
        return {
            "state": "healthy",
            "used_bytes": used_bytes,
            "effective_capacity_bytes": actual_capacity_bytes,
        }

    def collect_storage_capacity_profile(
        self,
        *,
        environment: str,
        source: str,
    ) -> dict[str, object]:
        return {
            "observation_id": "capacity-1",
            "environment": environment,
            "source": source,
            "filesystem_total_bytes": 100,
            "filesystem_used_bytes": 20,
            "database_size_bytes": 5,
        }


class _DataCenterReadProvider:
    def get_macro_runtime_metadata(self) -> dict[str, dict[str, object]]:
        return {"CN_PMI": {"unit": "指数"}}

    def get_active_stock_fact_coverage_payload(self) -> dict[str, object]:
        return {"status": "ok"}

    def get_decision_provider_capability_health_payload(self) -> dict[str, object]:
        return {"status": "ok"}

    def get_decision_data_readiness_payload(self) -> dict[str, object]:
        return {"status": "ok"}


def test_config_center_runtime_bridge_delegates_to_registered_owner(monkeypatch) -> None:
    monkeypatch.setattr(config_center_runtime, "_provider", None)
    config_center_runtime.configure_config_center_runtime_port(_ConfigCenterRuntimeProvider())

    assert (
        config_center_runtime.get_active_runtime_value(
            environment="production",
            definition_key="data_center.provider.enable_failover",
        )
        is True
    )
    assert config_center_runtime.evaluate_storage_pressure(
        used_bytes=10,
        actual_capacity_bytes=100,
    ) == {
        "state": "healthy",
        "used_bytes": 10,
        "effective_capacity_bytes": 100,
    }
    assert config_center_runtime.collect_storage_capacity_profile(
        environment="production",
        source="backup-preflight",
    ) == {
        "observation_id": "capacity-1",
        "environment": "production",
        "source": "backup-preflight",
        "filesystem_total_bytes": 100,
        "filesystem_used_bytes": 20,
        "database_size_bytes": 5,
    }


def test_config_center_runtime_bridge_fails_closed_without_owner(monkeypatch) -> None:
    monkeypatch.setattr(config_center_runtime, "_provider", None)

    assert (
        config_center_runtime.get_active_runtime_value(
            environment="production",
            definition_key="data_center.provider.enable_failover",
        )
        is None
    )
    pressure = config_center_runtime.evaluate_storage_pressure(used_bytes=10)
    assert pressure["state"] == "blocked"
    assert pressure["reason"] == "config_center_runtime_port_unconfigured"
    try:
        config_center_runtime.collect_storage_capacity_profile(
            environment="production",
            source="backup-preflight",
        )
    except RuntimeError as exc:
        assert str(exc) == "config_center_runtime_port_unconfigured"
    else:
        raise AssertionError("capacity collection must fail closed without its owner")


def test_data_center_readiness_bridge_delegates_to_registered_owner(monkeypatch) -> None:
    monkeypatch.setattr(data_center_readiness, "_provider", None)
    data_center_readiness.configure_data_center_read_port(_DataCenterReadProvider())

    assert data_center_readiness.get_macro_runtime_metadata() == {"CN_PMI": {"unit": "指数"}}
    assert data_center_readiness.get_active_stock_fact_coverage_payload() == {"status": "ok"}
    assert data_center_readiness.get_decision_provider_capability_health_payload() == {
        "status": "ok"
    }
    assert data_center_readiness.get_decision_data_readiness_payload() == {"status": "ok"}


def test_data_center_readiness_bridge_blocks_without_owner(monkeypatch) -> None:
    monkeypatch.setattr(data_center_readiness, "_provider", None)

    assert data_center_readiness.get_macro_runtime_metadata() == {}
    payload = data_center_readiness.get_decision_data_readiness_payload()
    assert payload["status"] == "error"
    assert payload["must_not_use_for_decision"] is True
    assert payload["block_reason_code"] == "data_center_read_port_unconfigured"
