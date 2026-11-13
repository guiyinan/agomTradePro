"""Application-owned policy evidence contract for current disclosure windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Protocol

from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventCoverageLeasePolicy,
)


@dataclass(frozen=True, slots=True)
class TransitionPlanDisclosureRuntimePolicy:
    """Immutable configured-policy evidence copied through the composition boundary."""

    source_id: Literal["szse_official"]
    start_on: date
    end_on: date
    body_store_root: Path
    lease_policy: TransitionPlanEventCoverageLeasePolicy
    policy_version: str
    runtime_environment: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_hash: str
    snapshot_id: str
    snapshot_content_hash: str
    known_at: datetime
    effective_at: datetime
    read_at: datetime
    policy_content_hash: str


class OfficialWindowRuntimePolicyReader(Protocol):
    """Read exact active-policy evidence through a composition-provided adapter."""

    def read_policy(
        self,
        *,
        decision_on: date,
        earliest_required_on: date,
        as_of: datetime,
    ) -> TransitionPlanDisclosureRuntimePolicy | None:
        """Return configured evidence for this cutoff, or None when unavailable."""
        ...
