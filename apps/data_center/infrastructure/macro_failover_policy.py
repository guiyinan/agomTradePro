"""Config Center-backed macro failover policy provider."""

from __future__ import annotations

from apps.data_center.application.sync_use_cases import MacroFailoverPolicy
from apps.data_center.infrastructure.macro_sources.failover_adapter import (
    _resolve_failover_enabled,
    _resolve_failover_tolerance,
)


class ConfigCenterMacroFailoverPolicyProvider:
    """Load failover permission and tolerance from one runtime environment."""

    def __init__(self, *, environment: str) -> None:
        if not isinstance(environment, str) or not environment.strip():
            raise ValueError("environment must be a non-empty string")
        self._environment = environment

    def get_policy(self) -> MacroFailoverPolicy:
        """Return one validated policy without code or environment defaults."""

        return MacroFailoverPolicy(
            enabled=_resolve_failover_enabled(environment=self._environment),
            tolerance=_resolve_failover_tolerance(environment=self._environment),
        )


__all__ = ["ConfigCenterMacroFailoverPolicyProvider"]
