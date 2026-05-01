"""Bridge helpers for runtime benchmark configuration."""

from __future__ import annotations

from core.integration.runtime_settings import (
    get_runtime_benchmark_code as load_runtime_benchmark_code,
)


def get_runtime_benchmark_code(key: str, default: str = "") -> str:
    """Return a runtime benchmark code by key."""

    return load_runtime_benchmark_code(key, default)
