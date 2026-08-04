"""App-neutral registry for Data Center decision-read and catalog facades."""

from __future__ import annotations

from typing import Any, Protocol


class DataCenterReadPort(Protocol):
    """Owner facade consumed by Config Center readiness and summary screens."""

    def get_macro_runtime_metadata(self) -> dict[str, dict[str, Any]]:
        """Return canonical macro catalog metadata."""

    def get_active_stock_fact_coverage_payload(self) -> dict[str, Any]:
        """Return active-stock coverage readiness evidence."""

    def get_decision_provider_capability_health_payload(self) -> dict[str, Any]:
        """Return provider capability readiness evidence."""

    def get_decision_data_readiness_payload(self) -> dict[str, Any]:
        """Return quote and market-thermometer readiness evidence."""


_provider: DataCenterReadPort | None = None


def configure_data_center_read_port(provider: DataCenterReadPort) -> None:
    """Register the Data Center-owned read facade at the composition root."""

    global _provider
    _provider = provider


def get_macro_runtime_metadata() -> dict[str, dict[str, Any]]:
    """Return catalog metadata or an empty map before Data Center bootstrap."""

    if _provider is None:
        return {}
    try:
        return _provider.get_macro_runtime_metadata()
    except Exception:
        return {}


def _blocked_payload(reason: str) -> dict[str, Any]:
    return {
        "status": "error",
        "must_not_use_for_decision": True,
        "block_reason_code": reason,
    }


def get_active_stock_fact_coverage_payload() -> dict[str, Any]:
    """Return coverage evidence, failing closed before the owner is configured."""

    if _provider is None:
        return _blocked_payload("data_center_read_port_unconfigured")
    try:
        return _provider.get_active_stock_fact_coverage_payload()
    except Exception:
        return _blocked_payload("data_center_coverage_probe_failed")


def get_decision_provider_capability_health_payload() -> dict[str, Any]:
    """Return provider health evidence, failing closed on owner errors."""

    if _provider is None:
        return _blocked_payload("data_center_read_port_unconfigured")
    try:
        return _provider.get_decision_provider_capability_health_payload()
    except Exception:
        return _blocked_payload("data_center_provider_probe_failed")


def get_decision_data_readiness_payload() -> dict[str, Any]:
    """Return decision-data evidence, failing closed on owner errors."""

    if _provider is None:
        return _blocked_payload("data_center_read_port_unconfigured")
    try:
        return _provider.get_decision_data_readiness_payload()
    except Exception:
        return _blocked_payload("data_center_readiness_probe_failed")


__all__ = [
    "DataCenterReadPort",
    "configure_data_center_read_port",
    "get_active_stock_fact_coverage_payload",
    "get_decision_data_readiness_payload",
    "get_decision_provider_capability_health_payload",
    "get_macro_runtime_metadata",
]
