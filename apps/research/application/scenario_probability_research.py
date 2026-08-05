"""Application orchestration for fail-closed R7 scenario research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.scenario_probability_calibration import (
    evaluate_scenario_probability_calibration,
)
from apps.research.domain.scenario_probability_contracts import (
    ForecastLedgerOutcomeObservation,
    ScenarioCalibrationReport,
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_evidence import (
    HistoricalAnalogyAssessment,
    HistoricalAnalogyStudyEvidence,
    ScenarioPathAssessment,
    ScenarioPathStudyEvidence,
    assess_historical_analogy,
    assess_scenario_path_evidence,
)
from apps.research.domain.scenario_research_hashing import (
    hash_components,
    require_sha256,
    require_token,
)
from apps.research.domain.scenario_review_intent import (
    ReviewReminderIntent,
    build_review_reminder_intent,
)


class ScenarioProbabilityResearchPolicyProvider(Protocol):
    """Read the exact Research-owned policy active for a scenario scope."""

    def get_active(
        self,
        *,
        scope: ScenarioResearchScope,
        evaluated_at: datetime,
    ) -> ScenarioProbabilityResearchPolicy:
        """Return an immutable, versioned policy without fallback defaults."""


class ScenarioForecastOutcomeEvidenceProvider(Protocol):
    """Read immutable Signal ledger observations through an injected boundary."""

    def list_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        window_start: datetime,
        window_end: datetime,
        evaluated_at: datetime,
    ) -> tuple[ForecastLedgerOutcomeObservation, ...]:
        """Return exact revision-bound rows, including unresolved forecasts."""


class HistoricalAnalogyEvidenceProvider(Protocol):
    """Read a PIT-manifest-bound historical analogy study if one exists."""

    def get_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> HistoricalAnalogyStudyEvidence | None:
        """Return frozen evidence and never rebuild history from current values."""


class ScenarioPathEvidenceProvider(Protocol):
    """Read immutable research-only path and transition evidence."""

    def get_for_scope(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> ScenarioPathStudyEvidence | None:
        """Return path evidence without applying it to a decision or order."""


@dataclass(frozen=True)
class ScenarioProbabilityResearchPacket:
    """Safe R7 packet that remains usable when every optional evidence set is empty."""

    packet_version: str
    policy_version: str
    scope_hash: str
    evaluated_at: datetime
    calibration: ScenarioCalibrationReport
    historical_analogy: HistoricalAnalogyAssessment
    path_research: ScenarioPathAssessment
    review_reminder_intents: tuple[ReviewReminderIntent, ...]
    trains_probability_model: bool
    dispatches_reminders: bool
    research_only: bool
    must_not_use_for_decision: bool
    content_hash: str

    def __post_init__(self) -> None:
        """Reject packets that loosen the no-training and no-dispatch boundaries."""

        require_token(self.packet_version, "packet_version")
        require_token(self.policy_version, "policy_version")
        require_sha256(self.scope_hash, "scope_hash")
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("packet evaluated_at must be timezone-aware")
        if (
            self.calibration.policy_version != self.policy_version
            or self.historical_analogy.policy_version != self.policy_version
            or self.path_research.policy_version != self.policy_version
        ):
            raise ValueError("R7 packet evidence does not match its policy version")
        if (
            self.calibration.scope_hash != self.scope_hash
            or self.historical_analogy.scope_hash != self.scope_hash
            or self.path_research.scope_hash != self.scope_hash
        ):
            raise ValueError("R7 packet evidence does not match its scenario scope")
        if any(
            intent.policy_version != self.policy_version for intent in self.review_reminder_intents
        ):
            raise ValueError("R7 packet reminder intent policy mismatch")
        if self.trains_probability_model or self.dispatches_reminders:
            raise ValueError("R7 research packet cannot train models or dispatch reminders")
        if not self.research_only or not self.must_not_use_for_decision:
            raise ValueError("R7 research packet must remain research-only")
        expected = hash_components(
            self.packet_version,
            self.policy_version,
            self.scope_hash,
            self.evaluated_at.isoformat(),
            self.calibration.content_hash,
            self.historical_analogy.content_hash,
            self.path_research.content_hash,
            *(intent.content_hash for intent in self.review_reminder_intents),
            "False",
            "False",
            "True",
            "True",
        )
        require_sha256(self.content_hash, "packet content_hash")
        if self.content_hash != expected:
            raise ValueError("R7 research packet content_hash mismatch")


class BuildScenarioProbabilityResearchPacketUseCase:
    """Compose calibration, PIT analogy, path evidence, and review intents."""

    def __init__(
        self,
        *,
        policy_provider: ScenarioProbabilityResearchPolicyProvider,
        forecast_evidence_provider: ScenarioForecastOutcomeEvidenceProvider,
        historical_analogy_provider: HistoricalAnalogyEvidenceProvider,
        path_evidence_provider: ScenarioPathEvidenceProvider,
    ) -> None:
        self._policy_provider = policy_provider
        self._forecast_evidence_provider = forecast_evidence_provider
        self._historical_analogy_provider = historical_analogy_provider
        self._path_evidence_provider = path_evidence_provider

    def execute(
        self,
        *,
        scope: ScenarioResearchScope,
        evaluated_at: datetime,
    ) -> ScenarioProbabilityResearchPacket:
        """Build a no-side-effect packet from exact injected evidence versions."""

        policy = self._policy_provider.get_active(
            scope=scope,
            evaluated_at=evaluated_at,
        )
        observations = self._forecast_evidence_provider.list_for_scope(
            scope=scope,
            window_start=policy.sample_window_start,
            window_end=policy.sample_window_end,
            evaluated_at=evaluated_at,
        )
        analogy_evidence = self._historical_analogy_provider.get_for_scope(
            scope=scope,
            as_of=evaluated_at,
        )
        path_evidence = self._path_evidence_provider.get_for_scope(
            scope=scope,
            as_of=evaluated_at,
        )
        calibration = evaluate_scenario_probability_calibration(
            scope=scope,
            policy=policy,
            observations=observations,
            evaluated_at=evaluated_at,
        )
        historical_analogy = assess_historical_analogy(
            scope=scope,
            policy=policy,
            evidence=analogy_evidence,
            evaluated_at=evaluated_at,
        )
        path_research = assess_scenario_path_evidence(
            scope=scope,
            policy=policy,
            evidence=path_evidence,
            evaluated_at=evaluated_at,
        )
        review_intents = _review_intents(
            observations=observations,
            policy=policy,
            evaluated_at=evaluated_at,
        )
        packet_version = "scenario-probability-research-packet.v1"
        content_hash = hash_components(
            packet_version,
            policy.policy_version,
            scope.content_hash,
            evaluated_at.isoformat(),
            calibration.content_hash,
            historical_analogy.content_hash,
            path_research.content_hash,
            *(intent.content_hash for intent in review_intents),
            "False",
            "False",
            "True",
            "True",
        )
        return ScenarioProbabilityResearchPacket(
            packet_version=packet_version,
            policy_version=policy.policy_version,
            scope_hash=scope.content_hash,
            evaluated_at=evaluated_at,
            calibration=calibration,
            historical_analogy=historical_analogy,
            path_research=path_research,
            review_reminder_intents=review_intents,
            trains_probability_model=False,
            dispatches_reminders=False,
            research_only=True,
            must_not_use_for_decision=True,
            content_hash=content_hash,
        )


def _review_intents(
    *,
    observations: tuple[ForecastLedgerOutcomeObservation, ...],
    policy: ScenarioProbabilityResearchPolicy,
    evaluated_at: datetime,
) -> tuple[ReviewReminderIntent, ...]:
    unique = {
        observation.content_hash: observation
        for observation in observations
        if observation.invalidation is not None
    }
    return tuple(
        build_review_reminder_intent(
            observation=observation,
            policy=policy,
            evaluated_at=evaluated_at,
        )
        for _, observation in sorted(unique.items())
    )
