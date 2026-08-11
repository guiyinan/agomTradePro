"""Research-owned persistence seal for an R2 explanatory-trial policy."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2MarketStructureTrialPolicy,
    r2_trial_policy_hash,
)


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _record_hash(policy: R2MarketStructureTrialPolicy, ledger_recorded_at: datetime) -> str:
    payload = {
        "schema": "research-r2-trial-policy-record.v1",
        "policy": [policy.policy_id, policy.policy_version, policy.content_hash.lower()],
        "ledger_recorded_at": _utc_text(ledger_recorded_at),
        "safety": [True, True, True, True],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validated_r2_trial_policy(
    policy: R2MarketStructureTrialPolicy,
) -> R2MarketStructureTrialPolicy:
    """Deep-copy and replay the existing Phase-A policy factory seal."""

    if type(policy) is not R2MarketStructureTrialPolicy:
        raise TypeError("policy must be an exact R2MarketStructureTrialPolicy")
    original_hash = policy.content_hash
    rebuilt = deepcopy(policy)
    R2MarketStructureTrialPolicy.__post_init__(rebuilt)
    if original_hash != rebuilt.content_hash or original_hash != r2_trial_policy_hash(rebuilt):
        raise ValueError("R2 trial policy live seal differs")
    return rebuilt


@dataclass(frozen=True)
class PersistedR2MarketStructureTrialPolicy:
    """One server-ledger-stamped, selection-preregistered R2 policy."""

    policy: R2MarketStructureTrialPolicy
    ledger_recorded_at: datetime
    record_hash: str
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy: R2MarketStructureTrialPolicy,
        ledger_recorded_at: datetime,
    ) -> PersistedR2MarketStructureTrialPolicy:
        """Build a receipt without accepting caller-authored hashes or safety flags."""

        validated = validated_r2_trial_policy(policy)
        _require_aware(ledger_recorded_at, "ledger_recorded_at")
        return cls(
            policy=validated,
            ledger_recorded_at=ledger_recorded_at,
            record_hash=_record_hash(validated, ledger_recorded_at),
        )

    def __post_init__(self) -> None:
        validated = validated_r2_trial_policy(self.policy)
        _require_aware(self.ledger_recorded_at, "ledger_recorded_at")
        if not (validated.registered_at <= self.ledger_recorded_at < validated.selection_as_of):
            raise ValueError("R2 policy ledger clock must precede selection")
        if (
            self.research_only is not True
            or self.must_not_publish_current is not True
            or self.must_not_use_for_decision is not True
            or self.must_not_execute is not True
        ):
            raise ValueError("R2 policy safety flags must remain true")
        if self.record_hash != _record_hash(validated, self.ledger_recorded_at):
            raise ValueError("R2 policy record hash mismatch")

    def validated_copy(self) -> PersistedR2MarketStructureTrialPolicy:
        """Return an independent, fully replayed copy."""

        return PersistedR2MarketStructureTrialPolicy.create(
            policy=self.policy,
            ledger_recorded_at=self.ledger_recorded_at,
        )


__all__ = [
    "PersistedR2MarketStructureTrialPolicy",
    "validated_r2_trial_policy",
]
