"""Data Center runtime setting ports backed by Config Center."""

from __future__ import annotations

from typing import Any

from core.integration import runtime_settings as runtime_settings_bridge


def get_runtime_macro_index_metadata_map() -> dict[str, dict[str, Any]]:
    """Read macro index metadata from Config Center."""

    return runtime_settings_bridge.get_runtime_macro_index_metadata_map()


def get_runtime_macro_index_codes() -> list[str]:
    """Read macro index codes from Config Center."""

    return runtime_settings_bridge.get_runtime_macro_index_codes()


def get_runtime_macro_publication_lags() -> dict[str, dict[str, Any]]:
    """Read macro publication lag policies from Config Center."""

    return runtime_settings_bridge.get_runtime_macro_publication_lags()


__all__ = [
    "get_runtime_macro_index_codes",
    "get_runtime_macro_index_metadata_map",
    "get_runtime_macro_publication_lags",
]
