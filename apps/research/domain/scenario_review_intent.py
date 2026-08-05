"""Deterministic forecast-bound intent for internal R7 human review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioProbabilityResearchPolicy,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)


@dataclass(frozen=True)
class ReviewReminderIntent:
    """Internal intent for human review; it performs no delivery or task mutation."""

    intent_version: str
    intent_id: str
    forecast_entry_id: str
    forecast_group_id: str
    forecast_observation_hash: str
    policy_version: str
    policy_content_hash: str
    scenario_revision_id: UUID
    scenario_set_revision_id: UUID | None
    invalidation_evidence_hash: str
    created_at: datetime
    review_due_at: datetime
    reason_code: str
    delivery_scope: str
    must_not_execute: bool
    external_dispatch_requested: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Reject forged or side-effecting review reminder intents."""

        require_token(self.intent_version, "intent_version")
        require_token(self.forecast_entry_id, "forecast_entry_id", maximum=64)
        require_token(self.forecast_group_id, "forecast_group_id")
        require_sha256(self.forecast_observation_hash, "forecast_observation_hash")
        require_token(self.policy_version, "policy_version")
        require_sha256(self.policy_content_hash, "policy_content_hash")
        require_sha256(self.intent_id, "intent_id")
        require_sha256(
            self.invalidation_evidence_hash,
            "invalidation_evidence_hash",
        )
        _require_aware(self.created_at, "intent created_at")
        _require_aware(self.review_due_at, "intent review_due_at")
        if self.review_due_at < self.created_at:
            raise ValueError("review_due_at cannot precede created_at")
        require_token(self.reason_code, "reason_code")
        if self.delivery_scope != "internal_review":
            raise ValueError("review reminder intent delivery_scope must be internal_review")
        if not self.must_not_execute:
            raise ValueError("review reminder intent must prohibit execution")
        if self.external_dispatch_requested:
            raise ValueError("review reminder intent cannot request external dispatch")
        require_sha256(self.content_hash, "intent content_hash")
        expected_intent_id = hash_components(
            self.intent_version,
            self.forecast_entry_id,
            self.forecast_observation_hash,
            self.invalidation_evidence_hash,
            self.policy_content_hash,
        )
        if self.intent_id != expected_intent_id:
            raise ValueError("review reminder intent_id mismatch")
        expected = hash_components(
            self.intent_version,
            self.intent_id,
            self.forecast_entry_id,
            self.forecast_group_id,
            self.forecast_observation_hash,
            self.policy_version,
            self.policy_content_hash,
            str(self.scenario_revision_id),
            str(self.scenario_set_revision_id or ""),
            self.invalidation_evidence_hash,
            _utc_iso(self.created_at),
            _utc_iso(self.review_due_at),
            self.reason_code,
            "internal_review",
            "True",
            "False",
        )
        if self.content_hash != expected:
            raise ValueError("review reminder intent content_hash mismatch")

    @property
    def dispatch_requested(self) -> bool:
        """Compatibility view: no external dispatch is ever requested."""

        return self.external_dispatch_requested


def build_review_reminder_intent(
    *,
    observation: ForecastLedgerOutcomeObservation,
    policy: ScenarioProbabilityResearchPolicy,
    evaluated_at: datetime,
) -> ReviewReminderIntent:
    """Create one deterministic forecast-bound intent without dispatching it."""

    _require_aware(evaluated_at, "evaluated_at")
    invalidation = observation.invalidation
    if invalidation is None:
        raise ValueError("review reminder intent requires invalidation evidence")
    if invalidation.invalidated_at > evaluated_at:
        raise ValueError("invalidation cannot be future-dated")
    intent_version = "scenario-review-reminder-intent.v1"
    created_at = invalidation.invalidated_at
    review_due_at = invalidation.invalidated_at + policy.invalidation_review_delay
    identity_hash = hash_components(
        intent_version,
        observation.entry_id,
        observation.content_hash,
        invalidation.content_hash,
        policy.content_hash,
    )
    content_hash = hash_components(
        intent_version,
        identity_hash,
        observation.entry_id,
        observation.forecast_group_id,
        observation.content_hash,
        policy.policy_version,
        policy.content_hash,
        str(invalidation.scenario_revision_id),
        str(invalidation.scenario_set_revision_id or ""),
        invalidation.content_hash,
        _utc_iso(created_at),
        _utc_iso(review_due_at),
        "scenario_invalidation.requires_human_review",
        "internal_review",
        "True",
        "False",
    )
    return ReviewReminderIntent(
        intent_version=intent_version,
        intent_id=identity_hash,
        forecast_entry_id=observation.entry_id,
        forecast_group_id=observation.forecast_group_id,
        forecast_observation_hash=observation.content_hash,
        policy_version=policy.policy_version,
        policy_content_hash=policy.content_hash,
        scenario_revision_id=invalidation.scenario_revision_id,
        scenario_set_revision_id=invalidation.scenario_set_revision_id,
        invalidation_evidence_hash=invalidation.content_hash,
        created_at=created_at,
        review_due_at=review_due_at,
        reason_code="scenario_invalidation.requires_human_review",
        delivery_scope="internal_review",
        must_not_execute=True,
        external_dispatch_requested=False,
        content_hash=content_hash,
    )


def _utc_iso(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = ["ReviewReminderIntent", "build_review_reminder_intent"]
