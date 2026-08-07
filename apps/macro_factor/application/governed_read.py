"""Fail-closed exact R3 monitoring and governed read orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from apps.macro_factor.domain.dated_outputs import DatedMacroFactorOutput
from apps.macro_factor.domain.governed_read import (
    R3ExperimentTrialEvidence,
    R3GovernedReadProjection,
    R3MonitoringEvidence,
    R3MonitoringStatus,
    R3PromotionDecisionEvidence,
    R3PromotionOutcome,
    R3RegimeSegmentReport,
    assess_monitoring,
    build_regime_segment_report,
    validate_promotion_binding,
    validate_trial_binding,
)
from apps.macro_factor.domain.lifecycle import (
    MacroFactorLifecycleEvent,
    MacroFactorOutputResearchStatus,
    assess_output_research_status,
)
from apps.macro_factor.domain.run_artifacts import ReproducibleMacroFactorRunArtifact


class R3GovernedReadLedger(Protocol):
    """Read-only boundary over the immutable R3 run ledger."""

    def get_artifact(
        self,
        artifact_id: str,
    ) -> ReproducibleMacroFactorRunArtifact | None:
        """Return one exact immutable run artifact."""

    def list_outputs(self, artifact_id: str) -> tuple[DatedMacroFactorOutput, ...]:
        """Return exact immutable outputs in deterministic order."""

    def list_lifecycle_events(
        self,
        artifact_id: str,
    ) -> tuple[MacroFactorLifecycleEvent, ...]:
        """Return and verify the complete lifecycle chain."""


class R3RegimeReportProvider(Protocol):
    """Read the Regime-owner exact OOS segmentation evidence."""

    def get_report(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3RegimeSegmentReport | None:
        """Return one immutable report or ``None`` without inventing assignments."""


class R3TrialEvidenceProvider(Protocol):
    """Read Research-owner preregistered trial evidence."""

    def get_trial(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3ExperimentTrialEvidence | None:
        """Return the exact trial selected by the owner at the cutoff."""


class R3PromotionDecisionProvider(Protocol):
    """Read one Research-owner exact PromotionDecision."""

    def get_decision(
        self,
        *,
        trial_id: str,
        expected_trial_hash: str,
        as_of: datetime,
    ) -> R3PromotionDecisionEvidence | None:
        """Return the exact owner decision, including rejected outcomes."""


class R3MonitoringEvidenceProvider(Protocol):
    """Read raw retirement-policy-owner monitoring evidence."""

    def get_monitoring(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3MonitoringEvidence | None:
        """Return exact metric facts; callers cannot submit a claimed health gate."""


@dataclass(frozen=True)
class ReadGovernedR3OutputCommand:
    """ID-only exact output read at a PIT cutoff; never a latest/current query."""

    artifact_id: str
    expected_artifact_hash: str
    output_id: str
    expected_output_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.expected_artifact_hash, "expected_artifact_hash"),
            (self.output_id, "output_id"),
            (self.expected_output_hash, "expected_output_hash"),
        ):
            if len(value) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in value
            ):
                raise ValueError(f"{name} must be a sha256 digest")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


class R3GovernedReadStatus(str, Enum):
    """Outcome of the read-only evidence projection."""

    EVIDENCE_COMPLETE = "evidence_complete"
    BLOCKED = "blocked"


class R3GovernedReadBlockerCode(str, Enum):
    """Stable fail-closed reasons for exact R3 reads."""

    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    ARTIFACT_FUTURE = "artifact_future"
    OUTPUT_MISSING = "output_missing"
    OUTPUT_MISMATCH = "output_mismatch"
    OUTPUT_INACTIVE = "output_inactive"
    LIFECYCLE_INVALID = "lifecycle_invalid"
    REGIME_REPORT_MISSING = "regime_report_missing"
    REGIME_REPORT_INVALID = "regime_report_invalid"
    TRIAL_MISSING = "trial_missing"
    TRIAL_INVALID = "trial_invalid"
    PROMOTION_MISSING = "promotion_missing"
    PROMOTION_INVALID = "promotion_invalid"
    PROMOTION_NOT_APPROVED = "promotion_not_approved"
    PROMOTION_INACTIVE = "promotion_inactive"
    MONITORING_MISSING = "monitoring_missing"
    MONITORING_INVALID = "monitoring_invalid"
    MONITORING_INCOMPLETE = "monitoring_incomplete"
    RETIREMENT_REVIEW_REQUIRED = "retirement_review_required"


@dataclass(frozen=True)
class R3GovernedReadAssessment:
    """Fail-closed result; even complete evidence remains non-decision research."""

    status: R3GovernedReadStatus
    blocker_codes: tuple[R3GovernedReadBlockerCode, ...]
    projection: R3GovernedReadProjection | None
    research_only: bool = True
    publishes_current: bool = False
    decision_authorized: bool = False
    execution_authorized: bool = False
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if self.status is R3GovernedReadStatus.BLOCKED:
            if not self.blocker_codes or self.projection is not None:
                raise ValueError("blocked R3 read requires only stable blockers")
        elif self.blocker_codes or self.projection is None:
            raise ValueError("complete R3 read requires one projection and no blockers")
        if not (
            self.research_only
            and not self.publishes_current
            and not self.decision_authorized
            and not self.execution_authorized
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R3 read assessment cannot authorize production behavior")


def _blocked(code: R3GovernedReadBlockerCode) -> R3GovernedReadAssessment:
    return R3GovernedReadAssessment(
        status=R3GovernedReadStatus.BLOCKED,
        blocker_codes=(code,),
        projection=None,
    )


class ReadGovernedR3Output:
    """Dynamically replay exact owner evidence before returning one read projection."""

    def __init__(
        self,
        *,
        ledger: R3GovernedReadLedger,
        regime_provider: R3RegimeReportProvider,
        trial_provider: R3TrialEvidenceProvider,
        promotion_provider: R3PromotionDecisionProvider,
        monitoring_provider: R3MonitoringEvidenceProvider,
    ) -> None:
        self._ledger = ledger
        self._regime_provider = regime_provider
        self._trial_provider = trial_provider
        self._promotion_provider = promotion_provider
        self._monitoring_provider = monitoring_provider

    def execute(self, command: ReadGovernedR3OutputCommand) -> R3GovernedReadAssessment:
        """Read an exact output, failing closed on every absent or changed owner record."""

        artifact = self._ledger.get_artifact(command.artifact_id)
        if artifact is None:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_MISSING)
        if artifact.content_hash != command.expected_artifact_hash:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_MISMATCH)
        if artifact.produced_at > command.as_of:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_FUTURE)

        try:
            outputs = self._ledger.list_outputs(artifact.artifact_id)
        except ValueError:
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_MISMATCH)
        output = next((item for item in outputs if item.output_id == command.output_id), None)
        if output is None:
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_MISSING)
        if (
            output.content_hash != command.expected_output_hash
            or output.artifact_id != artifact.artifact_id
            or output.artifact_hash != artifact.content_hash
        ):
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_MISMATCH)

        try:
            events = self._ledger.list_lifecycle_events(artifact.artifact_id)
            output_status = assess_output_research_status(
                output,
                events,
                assessed_at=command.as_of,
            )
        except ValueError:
            return _blocked(R3GovernedReadBlockerCode.LIFECYCLE_INVALID)
        if output_status is not MacroFactorOutputResearchStatus.AVAILABLE_FOR_RESEARCH:
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_INACTIVE)

        regime_report = self._regime_provider.get_report(
            artifact_id=artifact.artifact_id,
            expected_artifact_hash=artifact.content_hash,
            as_of=command.as_of,
        )
        if regime_report is None:
            return _blocked(R3GovernedReadBlockerCode.REGIME_REPORT_MISSING)
        try:
            recalculated_regime_report = build_regime_segment_report(
                artifact,
                regime_report.observations,
                evaluated_at=regime_report.evaluated_at,
            )
            if (
                recalculated_regime_report != regime_report
                or regime_report.evaluated_at > command.as_of
            ):
                raise ValueError("R3 Regime report differs from recalculation or is future")
        except ValueError:
            return _blocked(R3GovernedReadBlockerCode.REGIME_REPORT_INVALID)

        trial = self._trial_provider.get_trial(
            artifact_id=artifact.artifact_id,
            expected_artifact_hash=artifact.content_hash,
            as_of=command.as_of,
        )
        if trial is None:
            return _blocked(R3GovernedReadBlockerCode.TRIAL_MISSING)
        try:
            validate_trial_binding(trial, artifact, regime_report)
            if not trial.is_active_at(command.as_of):
                raise ValueError("R3 trial is inactive")
        except ValueError:
            return _blocked(R3GovernedReadBlockerCode.TRIAL_INVALID)

        decision = self._promotion_provider.get_decision(
            trial_id=trial.trial_id,
            expected_trial_hash=trial.content_hash,
            as_of=command.as_of,
        )
        if decision is None:
            return _blocked(R3GovernedReadBlockerCode.PROMOTION_MISSING)
        try:
            validate_promotion_binding(decision, trial, regime_report)
        except ValueError:
            return _blocked(R3GovernedReadBlockerCode.PROMOTION_INVALID)
        if decision.outcome is not R3PromotionOutcome.APPROVED:
            return _blocked(R3GovernedReadBlockerCode.PROMOTION_NOT_APPROVED)
        if not decision.is_active_at(command.as_of):
            return _blocked(R3GovernedReadBlockerCode.PROMOTION_INACTIVE)

        monitoring = self._monitoring_provider.get_monitoring(
            artifact_id=artifact.artifact_id,
            expected_artifact_hash=artifact.content_hash,
            as_of=command.as_of,
        )
        if monitoring is None:
            return _blocked(R3GovernedReadBlockerCode.MONITORING_MISSING)
        try:
            root = events[0]
            if (
                monitoring.artifact_id != artifact.artifact_id
                or monitoring.artifact_hash != artifact.content_hash
                or monitoring.source_result_hash != artifact.source_result_hash
                or monitoring.policy.policy_version != root.policy_version
                or monitoring.policy_hash != root.policy_hash
            ):
                raise ValueError("R3 monitoring evidence differs from artifact lifecycle policy")
            monitoring_assessment = assess_monitoring(monitoring, assessed_at=command.as_of)
        except (IndexError, ValueError):
            return _blocked(R3GovernedReadBlockerCode.MONITORING_INVALID)
        if monitoring_assessment.status is R3MonitoringStatus.INCOMPLETE:
            return _blocked(R3GovernedReadBlockerCode.MONITORING_INCOMPLETE)
        if monitoring_assessment.status is R3MonitoringStatus.RETIREMENT_REVIEW_REQUIRED:
            return _blocked(R3GovernedReadBlockerCode.RETIREMENT_REVIEW_REQUIRED)

        decision_boundary = (
            decision.valid_until
            if decision.retired_at is None
            else min(decision.valid_until, decision.retired_at)
        )
        projection = R3GovernedReadProjection(
            artifact_id=artifact.artifact_id,
            artifact_hash=artifact.content_hash,
            output=output,
            regime_report_hash=regime_report.content_hash,
            trial_id=trial.trial_id,
            trial_hash=trial.content_hash,
            decision_id=decision.decision_id,
            decision_hash=decision.content_hash,
            monitoring_assessment_hash=monitoring_assessment.content_hash,
            read_as_of=command.as_of,
            valid_until=min(
                output.valid_until,
                trial.valid_until,
                decision_boundary,
                monitoring_assessment.valid_until,
            ),
        )
        return R3GovernedReadAssessment(
            status=R3GovernedReadStatus.EVIDENCE_COMPLETE,
            blocker_codes=(),
            projection=projection,
        )


__all__ = [
    "R3GovernedReadAssessment",
    "R3GovernedReadBlockerCode",
    "R3GovernedReadLedger",
    "R3GovernedReadStatus",
    "R3MonitoringEvidenceProvider",
    "R3PromotionDecisionProvider",
    "R3RegimeReportProvider",
    "R3TrialEvidenceProvider",
    "ReadGovernedR3Output",
    "ReadGovernedR3OutputCommand",
]
