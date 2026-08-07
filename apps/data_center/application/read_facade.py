"""Data Center-owned read facade for app-neutral composition bridges."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DataCenterReadFacade:
    """Expose only Data Center application read ports to other app owners."""

    macro_runtime_metadata_reader: Callable[[], dict[str, dict[str, Any]]]
    active_stock_fact_coverage_reader: Callable[[], dict[str, Any]]
    provider_capability_health_reader: Callable[[], dict[str, Any]]
    decision_data_readiness_reader: Callable[[], dict[str, Any]]

    def get_macro_runtime_metadata(self) -> dict[str, dict[str, Any]]:
        """Return canonical macro catalog metadata."""

        return self.macro_runtime_metadata_reader()

    def get_active_stock_fact_coverage_payload(self) -> dict[str, Any]:
        """Return active-stock coverage readiness evidence."""

        return self.active_stock_fact_coverage_reader()

    def get_decision_provider_capability_health_payload(self) -> dict[str, Any]:
        """Return provider capability readiness evidence."""

        return self.provider_capability_health_reader()

    def get_decision_data_readiness_payload(self) -> dict[str, Any]:
        """Return quote and market-thermometer readiness evidence."""

        return self.decision_data_readiness_reader()


def build_data_center_read_facade() -> DataCenterReadFacade:
    """Compose the Data Center-owned application readers without querying data."""

    from apps.data_center.application.public import (
        get_active_stock_fact_coverage_payload,
        get_decision_data_readiness_payload,
        get_decision_provider_capability_health_payload,
        get_macro_runtime_metadata,
    )

    return DataCenterReadFacade(
        macro_runtime_metadata_reader=get_macro_runtime_metadata,
        active_stock_fact_coverage_reader=get_active_stock_fact_coverage_payload,
        provider_capability_health_reader=get_decision_provider_capability_health_payload,
        decision_data_readiness_reader=get_decision_data_readiness_payload,
    )


__all__ = ["DataCenterReadFacade", "build_data_center_read_facade"]
