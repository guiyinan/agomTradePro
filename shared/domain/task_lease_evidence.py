"""Generic, read-only contracts for task-specific distributed lease probes."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class DomainTaskLeaseState(Enum):
    """State returned by a domain-owned task lease probe."""

    ABSENT = "absent"
    ACTIVE = "active"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DomainTaskLeaseEvidence:
    """Safe lease state and stable evidence identifier without owner values."""

    state: DomainTaskLeaseState
    evidence_code: str


class DomainTaskLeaseProbeProtocol(Protocol):
    """Read-only adapter for one or more task-specific domain leases."""

    def supports_task_name(self, task_name: str) -> bool:
        """Return whether this probe owns the named task's lease contract."""
        ...

    def get_lease_evidence(
        self,
        *,
        task_name: str,
        task_kwargs: Mapping[str, object],
    ) -> DomainTaskLeaseEvidence:
        """Return exact owner state without exposing the lease owner."""
        ...
