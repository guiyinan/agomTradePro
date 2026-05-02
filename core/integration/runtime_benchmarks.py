"""Bridge helpers for runtime benchmark configuration."""

from __future__ import annotations


def get_account_config_summary_service():
    """Return the account-owned benchmark configuration service."""

    from apps.account.application.config_summary_service import (
        get_account_config_summary_service as load_account_config_summary_service,
    )

    return load_account_config_summary_service()


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return a runtime benchmark code by key."""

    return get_account_config_summary_service().get_runtime_benchmark_code(key, default)
