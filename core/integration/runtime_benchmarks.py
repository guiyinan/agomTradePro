"""Bridge helpers for runtime benchmark configuration."""

from __future__ import annotations

from apps.account.application.config_summary_service import get_account_config_summary_service


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return a runtime benchmark code by key."""

    return get_account_config_summary_service().get_runtime_benchmark_code(key, default)
