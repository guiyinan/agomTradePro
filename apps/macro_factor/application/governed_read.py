"""Fail-closed exact R3 monitoring and governed read orchestration."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity used by ledger reads."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity used by this reader."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity used by this reader."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity used by this reader."""

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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity used by this reader."""

    def get_monitoring(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3MonitoringEvidence | None:
        """Return exact metric facts; callers cannot submit a claimed health gate."""


class R3GovernedReadUnitOfWork(Protocol):
    """One atomic snapshot shared by the ledger and all four owner readers."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity opened by ``atomic``."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the single read transaction used by one governed read."""


class R3GovernedReadClock(Protocol):
    """Trusted server clock that bounds caller-supplied PIT cutoffs."""

    def now(self) -> datetime:
        """Return a timezone-aware trusted server time."""


class _R3UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str: ...


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
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdefABCDEF" for character in value)
            ):
                raise ValueError(f"{name} must be a sha256 digest")
        if (
            type(self.as_of) is not datetime
            or self.as_of.tzinfo is None
            or self.as_of.utcoffset() is None
        ):
            raise ValueError("as_of must be timezone-aware")


class R3GovernedReadStatus(str, Enum):  # noqa: UP042 -- preserve string enum compatibility
    """Outcome of the read-only evidence projection."""

    EVIDENCE_COMPLETE = "evidence_complete"
    BLOCKED = "blocked"


class R3GovernedReadBlockerCode(str, Enum):  # noqa: UP042 -- preserve string enum compatibility
    """Stable fail-closed reasons for exact R3 reads."""

    READ_INPUT_INVALID = "read_input_invalid"
    OWNER_EVIDENCE_UNAVAILABLE = "owner_evidence_unavailable"
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


@dataclass(frozen=True)
class _R3GovernedReadOwnerGraph:
    """One fully validated snapshot of all governed-read owner evidence."""

    artifact: ReproducibleMacroFactorRunArtifact
    outputs: tuple[DatedMacroFactorOutput, ...]
    events: tuple[MacroFactorLifecycleEvent, ...]
    regime_report: R3RegimeSegmentReport
    trial: R3ExperimentTrialEvidence
    decision: R3PromotionDecisionEvidence
    monitoring: R3MonitoringEvidence


def _exact_unit_of_work_key(value: object) -> str:
    if type(value) is not str or value != value.strip() or not value or len(value) > 200:
        raise ValueError("R3 governed-read unit_of_work_key is invalid")
    return value


def _validate_trusted_now(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("R3 governed-read trusted clock is invalid")
    return value


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
        unit_of_work: R3GovernedReadUnitOfWork,
        clock: R3GovernedReadClock,
    ) -> None:
        self._ledger = ledger
        self._regime_provider = regime_provider
        self._trial_provider = trial_provider
        self._promotion_provider = promotion_provider
        self._monitoring_provider = monitoring_provider
        self._unit_of_work = unit_of_work
        self._clock = clock

    def execute(self, command: ReadGovernedR3OutputCommand) -> R3GovernedReadAssessment:
        """Read an exact output, failing closed on every absent or changed owner record."""

        try:
            if type(command) is not ReadGovernedR3OutputCommand:
                raise TypeError("R3 governed-read command type differs")
            ReadGovernedR3OutputCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError):
            return _blocked(R3GovernedReadBlockerCode.READ_INPUT_INVALID)

        try:
            self._validate_shared_unit_of_work()
            with self._unit_of_work.atomic():
                self._validate_shared_unit_of_work()
                trusted_now = _validate_trusted_now(self._clock.now())
                if command.as_of > trusted_now:
                    return _blocked(R3GovernedReadBlockerCode.READ_INPUT_INVALID)

                first = self._read_owner_graph(command)
                if isinstance(first, R3GovernedReadAssessment):
                    return first
                baseline = deepcopy(first)
                self._validate_shared_unit_of_work()

                second = self._read_owner_graph(command)
                if isinstance(second, R3GovernedReadAssessment):
                    return _blocked(R3GovernedReadBlockerCode.OWNER_EVIDENCE_UNAVAILABLE)
                reread = deepcopy(second)
                self._validate_shared_unit_of_work()
                if baseline != reread:
                    return _blocked(R3GovernedReadBlockerCode.OWNER_EVIDENCE_UNAVAILABLE)

                projection = self._build_projection(reread, command)
                self._validate_shared_unit_of_work()
                return R3GovernedReadAssessment(
                    status=R3GovernedReadStatus.EVIDENCE_COMPLETE,
                    blocker_codes=(),
                    projection=projection,
                )
        except Exception:  # noqa: BLE001 - every owner boundary must fail closed
            return _blocked(R3GovernedReadBlockerCode.OWNER_EVIDENCE_UNAVAILABLE)

    def _validate_shared_unit_of_work(self) -> None:
        expected = _exact_unit_of_work_key(self._unit_of_work.unit_of_work_key)
        readers: tuple[_R3UnitOfWorkBound, ...] = (
            self._ledger,
            self._regime_provider,
            self._trial_provider,
            self._promotion_provider,
            self._monitoring_provider,
        )
        if any(_exact_unit_of_work_key(reader.unit_of_work_key) != expected for reader in readers):
            raise ValueError("R3 governed-read readers do not share one unit of work")

    def _read_owner_graph(
        self,
        command: ReadGovernedR3OutputCommand,
    ) -> _R3GovernedReadOwnerGraph | R3GovernedReadAssessment:
        artifact = self._ledger.get_artifact(command.artifact_id)
        if artifact is None:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_MISSING)
        if type(artifact) is not ReproducibleMacroFactorRunArtifact:
            raise TypeError("R3 artifact type differs")
        ReproducibleMacroFactorRunArtifact.__post_init__(artifact)
        if artifact.content_hash != command.expected_artifact_hash:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_MISMATCH)
        if artifact.produced_at > command.as_of:
            return _blocked(R3GovernedReadBlockerCode.ARTIFACT_FUTURE)

        outputs = self._ledger.list_outputs(artifact.artifact_id)
        if type(outputs) is not tuple or any(
            type(output_item) is not DatedMacroFactorOutput for output_item in outputs
        ):
            raise TypeError("R3 output collection type differs")
        for output_item in outputs:
            DatedMacroFactorOutput.__post_init__(output_item)
        output = next(
            (output_item for output_item in outputs if output_item.output_id == command.output_id),
            None,
        )
        if output is None:
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_MISSING)
        if (
            output.content_hash != command.expected_output_hash
            or output.artifact_id != artifact.artifact_id
            or output.artifact_hash != artifact.content_hash
        ):
            return _blocked(R3GovernedReadBlockerCode.OUTPUT_MISMATCH)

        events = self._ledger.list_lifecycle_events(artifact.artifact_id)
        if type(events) is not tuple or any(
            type(event) is not MacroFactorLifecycleEvent for event in events
        ):
            raise TypeError("R3 lifecycle collection type differs")
        for event in events:
            MacroFactorLifecycleEvent.__post_init__(event)
        try:
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
        if type(regime_report) is not R3RegimeSegmentReport:
            raise TypeError("R3 Regime report type differs")
        try:
            R3RegimeSegmentReport.__post_init__(regime_report)
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
        if type(trial) is not R3ExperimentTrialEvidence:
            raise TypeError("R3 trial type differs")
        try:
            R3ExperimentTrialEvidence.__post_init__(trial)
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
        if type(decision) is not R3PromotionDecisionEvidence:
            raise TypeError("R3 PromotionDecision type differs")
        try:
            R3PromotionDecisionEvidence.__post_init__(decision)
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
        if type(monitoring) is not R3MonitoringEvidence:
            raise TypeError("R3 monitoring evidence type differs")
        try:
            R3MonitoringEvidence.__post_init__(monitoring)
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

        return _R3GovernedReadOwnerGraph(
            artifact=artifact,
            outputs=outputs,
            events=events,
            regime_report=regime_report,
            trial=trial,
            decision=decision,
            monitoring=monitoring,
        )

    @staticmethod
    def _build_projection(
        graph: _R3GovernedReadOwnerGraph,
        command: ReadGovernedR3OutputCommand,
    ) -> R3GovernedReadProjection:
        artifact = graph.artifact
        output = next(item for item in graph.outputs if item.output_id == command.output_id)
        trial = graph.trial
        decision = graph.decision
        regime_report = graph.regime_report
        monitoring_assessment = assess_monitoring(
            graph.monitoring,
            assessed_at=command.as_of,
        )
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
        return projection


__all__ = [
    "R3GovernedReadAssessment",
    "R3GovernedReadBlockerCode",
    "R3GovernedReadClock",
    "R3GovernedReadLedger",
    "R3GovernedReadStatus",
    "R3GovernedReadUnitOfWork",
    "R3MonitoringEvidenceProvider",
    "R3PromotionDecisionProvider",
    "R3RegimeReportProvider",
    "R3TrialEvidenceProvider",
    "ReadGovernedR3Output",
    "ReadGovernedR3OutputCommand",
]
