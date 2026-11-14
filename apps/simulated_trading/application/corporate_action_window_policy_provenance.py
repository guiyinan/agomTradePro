"""Complete immutable configured-window identity without a local filesystem path."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.simulated_trading.application.corporate_action_current_official_window_contracts import (
    TransitionPlanDisclosureRuntimePolicy,
)


@dataclass(frozen=True, slots=True)
class CorporateActionWindowPolicyProvenance:
    """Pin the exact policy, profile, snapshot, activation and configured lease bounds."""

    source_id: str
    runtime_environment: str
    policy_version: str
    policy_content_sha256: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    known_at: datetime
    effective_at: datetime
    body_store_root_sha256: str
    lease_ttl_microseconds: int
    maximum_lease_microseconds: int

    def __post_init__(self) -> None:
        """Reject untyped identities, clocks, hashes or nonpositive lease declarations."""
        for value in (
            self.source_id,
            self.runtime_environment,
            self.policy_version,
            self.profile_id,
            self.profile_key,
            self.snapshot_id,
        ):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 256
                or any(
                    character.isspace() or ord(character) < 32 or ord(character) == 127
                    for character in value
                )
            ):
                raise ValueError("window configuration identity is invalid")
        for value in (
            self.policy_content_sha256,
            self.profile_content_sha256,
            self.snapshot_sha256,
            self.body_store_root_sha256,
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError("window configuration digest is invalid")
        for clock in (self.known_at, self.effective_at):
            if type(clock) is not datetime or clock.tzinfo is None or clock.utcoffset() is None:
                raise ValueError("window configuration clock is invalid")
        if (
            type(self.profile_version) is not int
            or self.profile_version <= 0
            or type(self.lease_ttl_microseconds) is not int
            or type(self.maximum_lease_microseconds) is not int
            or not 0 < self.lease_ttl_microseconds <= self.maximum_lease_microseconds
            or self.known_at > self.effective_at
        ):
            raise ValueError("window configuration version or lease bounds are invalid")

    @classmethod
    def from_policy(
        cls, policy: TransitionPlanDisclosureRuntimePolicy
    ) -> CorporateActionWindowPolicyProvenance:
        """Copy every stable selected-policy field and hash only its local storage locator."""
        if type(policy) is not TransitionPlanDisclosureRuntimePolicy:
            raise ValueError("exact current-window policy is required")
        return cls(
            source_id=policy.source_id,
            runtime_environment=policy.runtime_environment,
            policy_version=policy.policy_version,
            policy_content_sha256=policy.policy_content_hash,
            profile_id=policy.profile_id,
            profile_key=policy.profile_key,
            profile_version=policy.profile_version,
            profile_content_sha256=policy.profile_content_hash,
            snapshot_id=policy.snapshot_id,
            snapshot_sha256=policy.snapshot_content_hash,
            known_at=policy.known_at,
            effective_at=policy.effective_at,
            body_store_root_sha256=hashlib.sha256(str(policy.body_store_root).encode()).hexdigest(),
            lease_ttl_microseconds=_microseconds(policy.lease_policy.ttl),
            maximum_lease_microseconds=_microseconds(policy.lease_policy.maximum_ttl),
        )


def _microseconds(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
