"""Bridge helpers for runtime settings lookups."""

from __future__ import annotations

from apps.account.application.config_summary_service import get_account_config_summary_service


def get_runtime_macro_index_metadata_map() -> dict[str, dict]:
    """Return runtime macro index metadata map from the account settings service."""

    return get_account_config_summary_service().get_runtime_macro_index_metadata_map()


def get_runtime_macro_index_codes() -> list[str]:
    """Return runtime macro index codes from the account settings service."""

    return get_account_config_summary_service().get_runtime_macro_index_codes()


def get_runtime_macro_publication_lags() -> dict[str, dict]:
    """Return runtime macro publication lag configuration."""

    return get_account_config_summary_service().get_runtime_macro_publication_lags()


def get_runtime_qlib_config() -> dict[str, object]:
    """Return runtime qlib configuration."""

    return get_account_config_summary_service().get_runtime_qlib_config()


def get_runtime_alpha_fixed_provider() -> str:
    """Return runtime fixed alpha provider selection."""

    return get_account_config_summary_service().get_runtime_alpha_fixed_provider()


def get_runtime_alpha_pool_mode(default_mode: str) -> str:
    """Return runtime alpha pool mode with caller-supplied fallback."""

    return get_account_config_summary_service().get_runtime_alpha_pool_mode(default_mode)
