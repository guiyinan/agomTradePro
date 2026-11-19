"""Typed extensions of the existing Research registry for final OOS control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class EventStudyControlError(ValueError):
    """Reject a binding or consumed holdout with a stable reason."""


@dataclass(frozen=True, slots=True)
class EventStudyBindingRequest:
    """Expected immutable identities supplied before any final OOS evaluation."""

    study_key: str
    trial_id: str
    spec_id: str
    spec_sha256: str
    manifest_sha256: str
    parameter_sha256: str
    code_commit: str
    dependency_sha256: str


@dataclass(frozen=True, slots=True)
class EventStudyBinding:
    """Exact existing experiment/family/trial snapshot and verified PIT identity."""

    study_key: str
    trial_id: str
    experiment_id: str
    family_id: str
    spec_sha256: str
    manifest_id: str
    manifest_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class FinalOOSClaim:
    """Committed use receipt; failure after this receipt never reopens OOS."""

    claim_id: int
    binding: EventStudyBinding
    claimed_at: datetime
    actor_user_id: int
    cumulative_family_trials: int


class EventStudyRegistry(Protocol):
    """Only persistence capability needed in addition to the existing registry."""

    def register_spec(self, document: str, expected_sha256: str, *, actor_user_id: int) -> str:
        """Initialize or replay one immutable, operator-authorized specification."""
        ...

    def bind(self, request: EventStudyBindingRequest, *, actor_user_id: int) -> EventStudyBinding:
        """Bind a preregistered draft trial to exact immutable inputs."""
        ...

    def claim(self, study_key: str, *, actor_user_id: int) -> FinalOOSClaim:
        """Commit the experiment's sole final OOS use before returning."""
        ...


class FinalOOSEvaluator(Protocol):
    """Execution must use receipt-bound inputs and retain the frozen data gates."""

    def evaluate(self, claim: FinalOOSClaim) -> None:
        """Evaluate once; insufficient support is not a completed real study."""
        ...
