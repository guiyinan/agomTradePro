"""Short-lived proof of an exact, locked simulation risk revalidation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class PortfolioRiskExecutionQualification:
    """Bind a risk pass to its owner, session, sources and real check clock."""

    account_id: int
    owner_user_id: int
    execution_session: date
    checked_at: datetime
    valid_until: datetime
    policy_version: str
    policy_content_sha256: str
    runtime_config_sha256: str
    baseline_source_sha256: str
    native_limits_sha256: str
    resource_snapshot_hash: str

    def __post_init__(self) -> None:
        """Reject incomplete proofs rather than extending their source deadline."""

        if any(
            type(value) is not int or value <= 0 for value in (self.account_id, self.owner_user_id)
        ):
            raise ValueError("qualification requires positive account and owner IDs")
        if type(self.execution_session) is not date:
            raise ValueError("qualification requires an exact execution session")
        for value in (self.checked_at, self.valid_until):
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("qualification clocks must be timezone-aware")
        if self.checked_at >= self.valid_until:
            raise ValueError("risk proof has no valid execution interval")
        if not self.policy_version or self.policy_version.strip() != self.policy_version:
            raise ValueError("qualification requires a canonical policy version")
        for digest in (
            self.policy_content_sha256,
            self.runtime_config_sha256,
            self.baseline_source_sha256,
            self.native_limits_sha256,
        ):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("qualification requires exact policy source hashes")
        if re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", self.resource_snapshot_hash) is None:
            raise ValueError("qualification requires the exact resource/source hash")
