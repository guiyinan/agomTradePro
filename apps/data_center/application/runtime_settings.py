"""Data Center runtime setting ports backed by Config Center."""

from __future__ import annotations

from typing import Any, Protocol, cast


class RuntimeSettingsPort(Protocol):
    """Minimal Config Center read model required by Data Center providers."""

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict[str, Any]]: ...

    def get_runtime_macro_index_codes(self) -> list[str]: ...

    def get_runtime_macro_publication_lags(self) -> dict[str, dict[str, Any]]: ...


def _service() -> RuntimeSettingsPort:
    from apps.config_center.application.config_summary_service import (
        get_config_center_summary_service,
    )

    return cast(RuntimeSettingsPort, get_config_center_summary_service())


def get_runtime_macro_index_metadata_map() -> dict[str, dict[str, Any]]:
    """Read macro index metadata from Config Center."""

    return _service().get_runtime_macro_index_metadata_map()


def get_runtime_macro_index_codes() -> list[str]:
    """Read macro index codes from Config Center."""

    return _service().get_runtime_macro_index_codes()


def get_runtime_macro_publication_lags() -> dict[str, dict[str, Any]]:
    """Read macro publication lag policies from Config Center."""

    return _service().get_runtime_macro_publication_lags()


__all__ = [
    "get_runtime_macro_index_codes",
    "get_runtime_macro_index_metadata_map",
    "get_runtime_macro_publication_lags",
]
