"""Retired compatibility tombstone for the former shared SDK bridge.

Provider SDK ownership now lives in ``apps.data_center.infrastructure``.  The
shared layer deliberately keeps no third-party provider import so that business
apps cannot accidentally recreate a second provider boundary.
"""

from __future__ import annotations

from types import ModuleType


def get_akshare_module() -> ModuleType:
    """Fail closed for callers that have not migrated to Data Center yet."""

    raise RuntimeError(
        "AKShare transport moved to apps.data_center.infrastructure.legacy_sdk_bridge"
    )
