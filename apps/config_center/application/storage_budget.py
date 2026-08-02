"""Storage budget query and pressure guard application ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from apps.config_center.domain.runtime_config import StorageBudgetPolicy


class StorageBudgetQueryPort(Protocol):
    """Stable read port consumed by readiness, task monitor and retention jobs."""

    def get_active(self) -> StorageBudgetPolicy | None: ...

    def require_active(self) -> StorageBudgetPolicy: ...


class StoragePressureState(str, Enum):
    """Fail-closed storage pressure states."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StoragePressureReport:
    """Observed storage pressure and effective capacity."""

    state: StoragePressureState
    used_bytes: int
    effective_capacity_bytes: int | None
    configured_capacity_bytes: int | None
    usage_ratio: float | None
    reason: str


class StoragePressureGuard:
    """Evaluate disk usage using only the active runtime policy."""

    def __init__(self, policy_port: StorageBudgetQueryPort) -> None:
        self._policy_port = policy_port

    def evaluate(self, *, used_bytes: int, actual_capacity_bytes: int | None = None) -> StoragePressureReport:
        """Return pressure state; missing policy blocks low-priority writes."""

        if used_bytes < 0:
            raise ValueError("used_bytes cannot be negative")
        policy = self._policy_port.get_active()
        if policy is None or not policy.active:
            return StoragePressureReport(
                state=StoragePressureState.BLOCKED,
                used_bytes=used_bytes,
                effective_capacity_bytes=None,
                configured_capacity_bytes=None,
                usage_ratio=None,
                reason="storage_budget_policy_missing_or_inactive",
            )
        if actual_capacity_bytes is not None and actual_capacity_bytes <= 0:
            raise ValueError("actual_capacity_bytes must be positive")
        effective_capacity = min(
            policy.configured_capacity_bytes,
            actual_capacity_bytes if actual_capacity_bytes is not None else policy.configured_capacity_bytes,
        )
        ratio = used_bytes / effective_capacity
        if ratio >= 1.0 - policy.emergency_reserve_ratio:
            state = StoragePressureState.EMERGENCY
            reason = "emergency_reserve_reached"
        elif ratio >= policy.critical_ratio:
            state = StoragePressureState.CRITICAL
            reason = "critical_watermark_reached"
        elif ratio >= policy.warning_ratio:
            state = StoragePressureState.WARNING
            reason = "warning_watermark_reached"
        else:
            state = StoragePressureState.HEALTHY
            reason = "within_active_policy"
        return StoragePressureReport(
            state=state,
            used_bytes=used_bytes,
            effective_capacity_bytes=effective_capacity,
            configured_capacity_bytes=policy.configured_capacity_bytes,
            usage_ratio=ratio,
            reason=reason,
        )


__all__ = [
    "StorageBudgetQueryPort",
    "StoragePressureGuard",
    "StoragePressureReport",
    "StoragePressureState",
]
