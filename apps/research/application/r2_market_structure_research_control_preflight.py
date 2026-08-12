"""Read-only R2 research-control preflight over exact owner evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast

from apps.research.application.r2_market_structure_trial_monitoring import (
    ExactR2AuditOutcomeProvider,
    ExactR2CanonicalPublicationProvider,
    ExactR2CyclePITEvidenceProvider,
    ExactR2MonitoringRawFactProvider,
    ExactR2TrialPolicyProvider,
)
from apps.research.application.r2_market_structure_trial_monitoring_persistence import (
    R2MonitoringAssessmentRef,
    R2PersistedMonitoringAssessment,
    R2PersistedTrialAssessment,
    R2TrialAssessmentRef,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2_AUDIT_OUTCOME_VERSION,
    R2AuditExplanatoryOutcome,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2MarketStructureTrialPolicy,
    R2MonitoringRawFact,
    R2MonitoringStatus,
    R2PublicationKind,
    R2TrialStatus,
    derive_r2_audit_outcome_id,
)
from apps.research.domain.r2_market_structure_trial_policy_registry import (
    validated_r2_trial_policy,
)


class R2ResearchControlUnavailable(RuntimeError):
    """The command, trusted clock, or shared read boundary is invalid."""


class R2ResearchControlPreflightStatus(StrEnum):
    """Non-authoritative R2 research-control states."""

    EVIDENCE_GRAPH_COMPLETE = "evidence_graph_complete"
    BLOCKED = "blocked"


class R2ResearchControlBlockerCode(StrEnum):
    """Stable fail-closed reasons that grant no downstream authority."""

    AUDIT_MONITORING_FACTS_UNAVAILABLE = "audit_monitoring_facts_unavailable"
    AUDIT_OUTCOME_UNAVAILABLE = "audit_outcome_unavailable"
    CALENDAR_PUBLICATION_UNAVAILABLE = "calendar_publication_unavailable"
    CYCLE_EVIDENCE_UNAVAILABLE = "cycle_evidence_unavailable"
    LATEST_COMPLETE_TRIAL_MONITORING_UNAVAILABLE = "latest_complete_trial_monitoring_unavailable"
    LATEST_MONITORING_BREACHED = "latest_monitoring_breached"
    LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW = "latest_monitoring_requires_retirement_review"
    OWNER_GRAPH_CHANGED_DURING_PREFLIGHT = "owner_graph_changed_during_preflight"
    OWNER_GRAPH_SUBSTITUTED = "owner_graph_substituted"
    OWNER_PROVIDER_UNAVAILABLE = "owner_provider_unavailable"
    POLICY_UNAVAILABLE = "policy_unavailable"
    TAXONOMY_PUBLICATION_UNAVAILABLE = "taxonomy_publication_unavailable"
    UNIT_OF_WORK_CHANGED = "unit_of_work_changed"


@dataclass(frozen=True)
class EvaluateR2ResearchControlPreflightCommand:
    """Exact policy selector with no assessment, outcome, or health selector."""

    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R2 research-control policy_id")
        _require_token(self.policy_version, "R2 research-control policy_version")
        _require_hash(
            self.expected_policy_hash,
            "R2 research-control expected_policy_hash",
        )
        _require_aware(self.as_of, "R2 research-control as_of")

    @property
    def policy_ref(self) -> R2EvidenceRef:
        """Return the exact content-addressed policy selector."""

        return R2EvidenceRef(
            self.policy_id,
            self.policy_version,
            self.expected_policy_hash,
        )


@dataclass(frozen=True)
class R2LatestCompleteTrialMonitoringEvidence:
    """Strict server-selected 0016 trial/monitoring pair for one policy."""

    trial: R2PersistedTrialAssessment
    monitoring: R2PersistedMonitoringAssessment
    research_only: bool = True
    must_not_use_as_predictive_signal: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        trial: R2PersistedTrialAssessment,
        monitoring: R2PersistedMonitoringAssessment,
    ) -> R2LatestCompleteTrialMonitoringEvidence:
        """Construct a safety-fixed projection from strict persisted reads."""

        return cls(trial=trial, monitoring=monitoring)

    def __post_init__(self) -> None:
        if type(self.trial) is not R2PersistedTrialAssessment:
            raise TypeError("R2 latest-complete trial type differs")
        if type(self.monitoring) is not R2PersistedMonitoringAssessment:
            raise TypeError("R2 latest-complete monitoring type differs")
        if type(self.trial.reference) is not R2TrialAssessmentRef:
            raise TypeError("R2 latest-complete trial reference type differs")
        if type(self.monitoring.reference) is not R2MonitoringAssessmentRef:
            raise TypeError("R2 latest-complete monitoring reference type differs")
        if type(self.monitoring.trial_reference) is not R2TrialAssessmentRef:
            raise TypeError("R2 latest-complete parent reference type differs")
        R2TrialAssessmentRef.__post_init__(self.trial.reference)
        R2MonitoringAssessmentRef.__post_init__(self.monitoring.reference)
        R2TrialAssessmentRef.__post_init__(self.monitoring.trial_reference)
        trial_evidence = self.trial.evidence.validated_copy()
        monitoring_evidence = self.monitoring.evidence.validated_copy()
        for label, value in (
            ("trial ledger_recorded_at", self.trial.ledger_recorded_at),
            ("monitoring ledger_recorded_at", self.monitoring.ledger_recorded_at),
        ):
            _require_aware(value, f"R2 latest-complete {label}")
        if (
            self.monitoring.trial_reference != self.trial.reference
            or trial_evidence != self.trial.evidence
            or monitoring_evidence != self.monitoring.evidence
            or monitoring_evidence.trial != trial_evidence
            or trial_evidence.assessment.status is not R2TrialStatus.PASSED
            or monitoring_evidence.assessment.status is R2MonitoringStatus.BLOCKED
            or not (
                trial_evidence.assessment.assessed_at
                <= self.trial.ledger_recorded_at
                <= self.monitoring.ledger_recorded_at
            )
            or monitoring_evidence.assessment.assessed_at > self.monitoring.ledger_recorded_at
        ):
            raise ValueError("R2 latest-complete trial/monitoring graph differs")
        if not (
            self.research_only
            and self.must_not_use_as_predictive_signal
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R2 latest-complete safety boundary differs")

    def validated_copy(self) -> R2LatestCompleteTrialMonitoringEvidence:
        """Deep-copy and replay the complete persisted pair."""

        trial = R2PersistedTrialAssessment(
            reference=R2TrialAssessmentRef(
                self.trial.reference.assessment_id,
                self.trial.reference.assessment_version,
                self.trial.reference.content_hash,
            ),
            evidence=deepcopy(self.trial.evidence).validated_copy(),
            ledger_recorded_at=self.trial.ledger_recorded_at,
        )
        monitoring = R2PersistedMonitoringAssessment(
            reference=R2MonitoringAssessmentRef(
                self.monitoring.reference.assessment_id,
                self.monitoring.reference.assessment_version,
                self.monitoring.reference.content_hash,
            ),
            trial_reference=R2TrialAssessmentRef(
                self.monitoring.trial_reference.assessment_id,
                self.monitoring.trial_reference.assessment_version,
                self.monitoring.trial_reference.content_hash,
            ),
            evidence=deepcopy(self.monitoring.evidence).validated_copy(),
            ledger_recorded_at=self.monitoring.ledger_recorded_at,
        )
        copied = R2LatestCompleteTrialMonitoringEvidence.create(
            trial=trial,
            monitoring=monitoring,
        )
        if copied != self:
            raise ValueError("R2 latest-complete evidence differs after replay")
        return copied


class R2LatestCompleteTrialMonitoringProvider(Protocol):
    """Server-selecting read port; callers cannot choose an assessment."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_latest_complete(
        self,
        *,
        policy_ref: R2EvidenceRef,
        as_of: datetime,
    ) -> R2LatestCompleteTrialMonitoringEvidence | None:
        """Return the unique latest complete pair at the PIT cutoff."""


class R2ResearchControlUnitOfWork(Protocol):
    """One shared read transaction with a trusted server clock."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared database/snapshot identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared read transaction."""

    def server_now(self) -> datetime:
        """Return a caller-independent server timestamp."""


class _UnitOfWorkBound(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared transaction identity."""


@dataclass(frozen=True)
class R2ResearchControlPreflightResult:
    """Read-only completeness result with no publication or decision authority."""

    policy_ref: R2EvidenceRef
    as_of: datetime
    checked_at: datetime
    status: R2ResearchControlPreflightStatus
    blocker_codes: tuple[R2ResearchControlBlockerCode, ...]
    trial_receipt_hash: str | None
    monitoring_receipt_hash: str | None
    audit_outcome_hash: str | None
    research_only: bool = True
    must_not_use_as_predictive_signal: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        if type(self.policy_ref) is not R2EvidenceRef:
            raise TypeError("R2 research-control result policy reference differs")
        R2EvidenceRef.__post_init__(self.policy_ref)
        _require_aware(self.as_of, "R2 research-control result as_of")
        _require_aware(self.checked_at, "R2 research-control result checked_at")
        if self.as_of > self.checked_at:
            raise ValueError("R2 research-control result uses a future cutoff")
        if type(self.status) is not R2ResearchControlPreflightStatus:
            raise TypeError("R2 research-control result status differs")
        if type(self.blocker_codes) is not tuple or self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R2 research-control blockers are not canonical")
        if any(type(item) is not R2ResearchControlBlockerCode for item in self.blocker_codes):
            raise TypeError("R2 research-control blocker type differs")
        if (self.status is R2ResearchControlPreflightStatus.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R2 research-control status and blockers differ")
        for label, value in (
            ("trial_receipt_hash", self.trial_receipt_hash),
            ("monitoring_receipt_hash", self.monitoring_receipt_hash),
            ("audit_outcome_hash", self.audit_outcome_hash),
        ):
            if value is not None:
                _require_hash(value, f"R2 research-control result {label}")
        if not (
            self.research_only
            and self.must_not_use_as_predictive_signal
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R2 research-control result safety boundary differs")


@dataclass(frozen=True)
class _OwnerGraph:
    policy: R2MarketStructureTrialPolicy | None
    latest: R2LatestCompleteTrialMonitoringEvidence | None
    taxonomy: R2CanonicalPublicationEvidence | None
    calendar: R2CanonicalPublicationEvidence | None
    cycles: tuple[R2CyclePITEvidence | None, ...]
    audit: R2AuditExplanatoryOutcome | None
    facts: tuple[R2MonitoringRawFact, ...]


class EvaluateR2ResearchControlPreflight:
    """Double-read all selectable R2 owners and emit no write-capable artifact."""

    def __init__(
        self,
        *,
        policy_provider: ExactR2TrialPolicyProvider,
        publication_provider: ExactR2CanonicalPublicationProvider,
        cycle_provider: ExactR2CyclePITEvidenceProvider,
        latest_complete_provider: R2LatestCompleteTrialMonitoringProvider,
        audit_provider: ExactR2AuditOutcomeProvider,
        monitoring_fact_provider: ExactR2MonitoringRawFactProvider,
        unit_of_work: R2ResearchControlUnitOfWork,
    ) -> None:
        self._policy_provider = policy_provider
        self._publication_provider = publication_provider
        self._cycle_provider = cycle_provider
        self._latest_complete_provider = latest_complete_provider
        self._audit_provider = audit_provider
        self._monitoring_fact_provider = monitoring_fact_provider
        self._unit_of_work = unit_of_work
        self._participant_seal = self._current_participants()
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R2ResearchControlUnavailable(
                "R2 research-control unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R2ResearchControlUnavailable(
                "R2 research-control owners require one shared unit of work"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateR2ResearchControlPreflightCommand,
    ) -> R2ResearchControlPreflightResult:
        """Evaluate owner completeness without mutation, current, or decision use."""

        self._require_command(command)
        checked_at: datetime | None = None
        try:
            self._require_live_uow()
        except _UnitOfWorkChanged:
            return self._blocked_after_early_participant_change(command)
        try:
            with self._unit_of_work.atomic():
                server_now = self._unit_of_work.server_now()
                _require_aware(server_now, "R2 research-control server_now")
                checked_at = server_now
                self._require_live_uow()
                if command.as_of > checked_at:
                    raise _FutureCutoff
                first = self._read_graph(command)
                self._require_live_uow()
                second = self._read_graph(command)
                self._require_live_uow()
        except _FutureCutoff as error:
            raise R2ResearchControlUnavailable(
                "R2 research-control PIT cutoff is in the future"
            ) from error
        except _UnitOfWorkChanged as error:
            if checked_at is None:
                raise R2ResearchControlUnavailable(
                    "R2 research-control unit of work changed before trusted clock"
                ) from error
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED,
            )
        except Exception as error:
            if checked_at is None:
                raise R2ResearchControlUnavailable(
                    "R2 research-control transaction or trusted clock is unavailable"
                ) from error
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
            )
        if checked_at is None:
            raise R2ResearchControlUnavailable("R2 research-control trusted clock was not captured")
        if first != second:
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
            )
        return self._evaluate_graph(command, checked_at, second)

    def _read_graph(
        self,
        command: EvaluateR2ResearchControlPreflightCommand,
    ) -> _OwnerGraph:
        self._require_live_uow()
        policy = _copy_policy(
            self._policy_provider.get_exact(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_content_hash=command.expected_policy_hash,
                as_of=command.as_of,
            )
        )
        self._require_live_uow()
        latest = _copy_latest(
            self._latest_complete_provider.get_latest_complete(
                policy_ref=command.policy_ref,
                as_of=command.as_of,
            )
        )
        self._require_live_uow()
        selector = policy
        if selector is None and latest is not None:
            selector = latest.trial.evidence.policy
        if selector is None:
            return _OwnerGraph(None, latest, None, None, (), None, ())
        taxonomy = self._read_publication(
            selector,
            kind=R2PublicationKind.TAXONOMY,
            as_of=command.as_of,
        )
        calendar = self._read_publication(
            selector,
            kind=R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
            as_of=command.as_of,
        )
        cycles: list[R2CyclePITEvidence | None] = []
        for definition in selector.cycles:
            self._require_live_uow()
            cycles.append(
                _copy_cycle(
                    self._cycle_provider.get_exact(
                        evidence_ref=definition.evidence_ref,
                        taxonomy_publication_ref=selector.taxonomy_publication_ref,
                        calendar_publication_ref=selector.calendar_publication_ref,
                        as_of=command.as_of,
                    )
                )
            )
        self._require_live_uow()
        audit = _copy_audit(
            self._audit_provider.get_exact(
                policy_ref=selector.reference,
                audit_plan_ref=selector.audit_plan_ref,
                cycle_evidence_refs=tuple(item.evidence_ref for item in selector.cycles),
                expected_outcome_id=derive_r2_audit_outcome_id(
                    policy_ref=selector.reference,
                    audit_plan_ref=selector.audit_plan_ref,
                    cycle_evidence_refs=tuple(item.evidence_ref for item in selector.cycles),
                ),
                expected_outcome_version=R2_AUDIT_OUTCOME_VERSION,
                as_of=command.as_of,
            )
        )
        expected_fact_identities = (
            ()
            if latest is None
            else tuple(
                (item.fact_id, item.fact_version) for item in latest.monitoring.evidence.facts
            )
        )
        self._require_live_uow()
        facts = _copy_facts(
            self._monitoring_fact_provider.list_exact(
                policy_ref=selector.reference,
                taxonomy_publication_ref=selector.taxonomy_publication_ref,
                calendar_publication_ref=selector.calendar_publication_ref,
                expected_fact_identities=expected_fact_identities,
                as_of=command.as_of,
            )
        )
        self._require_live_uow()
        return _OwnerGraph(
            policy=policy,
            latest=latest,
            taxonomy=taxonomy,
            calendar=calendar,
            cycles=tuple(cycles),
            audit=audit,
            facts=facts,
        )

    def _read_publication(
        self,
        policy: R2MarketStructureTrialPolicy,
        *,
        kind: R2PublicationKind,
        as_of: datetime,
    ) -> R2CanonicalPublicationEvidence | None:
        self._require_live_uow()
        seal = (
            policy.taxonomy_projection_seal
            if kind is R2PublicationKind.TAXONOMY
            else policy.calendar_projection_seal
        )
        value = self._publication_provider.get_exact(
            kind=kind,
            reference=seal.reference,
            expected_projection_hash=seal.projection_hash,
            expected_available_at=seal.available_at,
            expected_recorded_at=seal.recorded_at,
            as_of=as_of,
        )
        self._require_live_uow()
        return _copy_publication(value)

    def _evaluate_graph(
        self,
        command: EvaluateR2ResearchControlPreflightCommand,
        checked_at: datetime,
        graph: _OwnerGraph,
    ) -> R2ResearchControlPreflightResult:
        blockers: list[R2ResearchControlBlockerCode] = []
        if graph.policy is None:
            blockers.append(R2ResearchControlBlockerCode.POLICY_UNAVAILABLE)
        if graph.latest is None:
            blockers.append(
                R2ResearchControlBlockerCode.LATEST_COMPLETE_TRIAL_MONITORING_UNAVAILABLE
            )
        if graph.taxonomy is None:
            blockers.append(R2ResearchControlBlockerCode.TAXONOMY_PUBLICATION_UNAVAILABLE)
        if graph.calendar is None:
            blockers.append(R2ResearchControlBlockerCode.CALENDAR_PUBLICATION_UNAVAILABLE)
        if len(graph.cycles) != 2 or any(item is None for item in graph.cycles):
            blockers.append(R2ResearchControlBlockerCode.CYCLE_EVIDENCE_UNAVAILABLE)
        if graph.audit is None:
            blockers.append(R2ResearchControlBlockerCode.AUDIT_OUTCOME_UNAVAILABLE)
        if not graph.facts:
            blockers.append(R2ResearchControlBlockerCode.AUDIT_MONITORING_FACTS_UNAVAILABLE)
        if blockers:
            return self._blocked(command, checked_at, *blockers, graph=graph)
        if not _graph_is_exact(command, graph):
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.OWNER_GRAPH_SUBSTITUTED,
                graph=graph,
            )
        if graph.latest is None:
            raise R2ResearchControlUnavailable("R2 latest graph narrowing failed")
        status = graph.latest.monitoring.evidence.assessment.status
        if status is R2MonitoringStatus.BREACHED:
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.LATEST_MONITORING_BREACHED,
                graph=graph,
            )
        if status is R2MonitoringStatus.RETIREMENT_REVIEW_REQUIRED:
            return self._blocked(
                command,
                checked_at,
                R2ResearchControlBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
                graph=graph,
            )
        return _result(
            command=command,
            checked_at=checked_at,
            status=R2ResearchControlPreflightStatus.EVIDENCE_GRAPH_COMPLETE,
            blockers=(),
            graph=graph,
        )

    @staticmethod
    def _blocked(
        command: EvaluateR2ResearchControlPreflightCommand,
        checked_at: datetime,
        *blockers: R2ResearchControlBlockerCode,
        graph: _OwnerGraph | None = None,
    ) -> R2ResearchControlPreflightResult:
        return _result(
            command=command,
            checked_at=checked_at,
            status=R2ResearchControlPreflightStatus.BLOCKED,
            blockers=tuple(sorted(set(blockers), key=lambda item: item.value)),
            graph=graph,
        )

    @staticmethod
    def _require_command(command: object) -> None:
        try:
            if type(command) is not EvaluateR2ResearchControlPreflightCommand:
                raise TypeError("R2 research-control command type differs")
            EvaluateR2ResearchControlPreflightCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R2ResearchControlUnavailable(
                "R2 research-control command is malformed"
            ) from error

    def _current_uow_keys(self) -> tuple[str, ...]:
        return tuple(
            _exact_uow_key(participant.unit_of_work_key)
            for participant in self._current_participants()
        )

    def _current_participants(self) -> tuple[_UnitOfWorkBound, ...]:
        return (
            self._policy_provider,
            self._publication_provider,
            self._cycle_provider,
            self._latest_complete_provider,
            self._audit_provider,
            self._monitoring_fact_provider,
            self._unit_of_work,
        )

    def _require_live_uow(self) -> None:
        participants = self._current_participants()
        if len(participants) != len(self._participant_seal) or any(
            participant is not sealed
            for participant, sealed in zip(
                participants,
                self._participant_seal,
                strict=True,
            )
        ):
            raise _UnitOfWorkChanged
        try:
            keys = tuple(
                _exact_uow_key(participant.unit_of_work_key)
                for participant in participants
            )
        except Exception as error:
            raise _UnitOfWorkChanged from error
        if any(key != self._expected_uow_key for key in keys):
            raise _UnitOfWorkChanged

    def _blocked_after_early_participant_change(
        self,
        command: EvaluateR2ResearchControlPreflightCommand,
    ) -> R2ResearchControlPreflightResult:
        """Use only the sealed trusted clock to report a pre-read identity failure."""

        sealed_unit_of_work = cast(
            R2ResearchControlUnitOfWork,
            self._participant_seal[-1],
        )
        try:
            with sealed_unit_of_work.atomic():
                checked_at = sealed_unit_of_work.server_now()
                _require_aware(checked_at, "R2 research-control server_now")
                if command.as_of > checked_at:
                    raise _FutureCutoff
        except _FutureCutoff as error:
            raise R2ResearchControlUnavailable(
                "R2 research-control PIT cutoff is in the future"
            ) from error
        except Exception as error:
            raise R2ResearchControlUnavailable(
                "R2 research-control transaction or trusted clock is unavailable"
            ) from error
        return self._blocked(
            command,
            checked_at,
            R2ResearchControlBlockerCode.UNIT_OF_WORK_CHANGED,
        )


class _FutureCutoff(RuntimeError):
    pass


class _UnitOfWorkChanged(RuntimeError):
    pass


def _graph_is_exact(
    command: EvaluateR2ResearchControlPreflightCommand,
    graph: _OwnerGraph,
) -> bool:
    policy = graph.policy
    latest = graph.latest
    taxonomy = graph.taxonomy
    calendar = graph.calendar
    audit = graph.audit
    if (
        policy is None
        or latest is None
        or taxonomy is None
        or calendar is None
        or audit is None
        or any(item is None for item in graph.cycles)
    ):
        return False
    cycles = tuple(item for item in graph.cycles if item is not None)
    trial = latest.trial.evidence
    monitoring = latest.monitoring.evidence
    return (
        policy.reference == command.policy_ref
        and policy.is_active_at(command.as_of)
        and trial.policy == policy
        and trial.taxonomy_publication == taxonomy
        and trial.calendar_publication == calendar
        and trial.cycles == cycles
        and trial.audit_outcome == audit
        and monitoring.trial == trial
        and monitoring.facts == graph.facts
        and latest.trial.ledger_recorded_at <= command.as_of
        and latest.monitoring.ledger_recorded_at <= command.as_of
        and taxonomy.is_active_at(command.as_of)
        and calendar.is_active_at(command.as_of)
        and all(item.is_active_at(command.as_of) for item in cycles)
        and audit.is_active_at(command.as_of)
        and all(item.is_active_at(command.as_of) for item in graph.facts)
    )


def _result(
    *,
    command: EvaluateR2ResearchControlPreflightCommand,
    checked_at: datetime,
    status: R2ResearchControlPreflightStatus,
    blockers: tuple[R2ResearchControlBlockerCode, ...],
    graph: _OwnerGraph | None,
) -> R2ResearchControlPreflightResult:
    latest = None if graph is None else graph.latest
    audit = None if graph is None else graph.audit
    return R2ResearchControlPreflightResult(
        policy_ref=command.policy_ref,
        as_of=command.as_of,
        checked_at=checked_at,
        status=status,
        blocker_codes=blockers,
        trial_receipt_hash=(None if latest is None else latest.trial.reference.content_hash),
        monitoring_receipt_hash=(
            None if latest is None else latest.monitoring.reference.content_hash
        ),
        audit_outcome_hash=None if audit is None else audit.content_hash,
    )


def _copy_policy(value: object) -> R2MarketStructureTrialPolicy | None:
    if value is None:
        return None
    if type(value) is not R2MarketStructureTrialPolicy:
        raise TypeError("R2 research-control policy type differs")
    copied = validated_r2_trial_policy(value)
    if copied != value:
        raise ValueError("R2 research-control policy live seal differs")
    return copied


def _copy_latest(value: object) -> R2LatestCompleteTrialMonitoringEvidence | None:
    if value is None:
        return None
    if type(value) is not R2LatestCompleteTrialMonitoringEvidence:
        raise TypeError("R2 research-control latest-complete type differs")
    return value.validated_copy()


def _copy_publication(value: object) -> R2CanonicalPublicationEvidence | None:
    if value is None:
        return None
    if type(value) is not R2CanonicalPublicationEvidence:
        raise TypeError("R2 research-control Publication type differs")
    copied = deepcopy(value)
    R2CanonicalPublicationEvidence.__post_init__(copied)
    if copied != value:
        raise ValueError("R2 research-control Publication live seal differs")
    return copied


def _copy_cycle(value: object) -> R2CyclePITEvidence | None:
    if value is None:
        return None
    if type(value) is not R2CyclePITEvidence:
        raise TypeError("R2 research-control cycle type differs")
    copied = deepcopy(value)
    R2CyclePITEvidence.__post_init__(copied)
    if copied != value:
        raise ValueError("R2 research-control cycle live seal differs")
    return copied


def _copy_audit(value: object) -> R2AuditExplanatoryOutcome | None:
    if value is None:
        return None
    if type(value) is not R2AuditExplanatoryOutcome:
        raise TypeError("R2 research-control Audit outcome type differs")
    copied = deepcopy(value)
    R2AuditExplanatoryOutcome.__post_init__(copied)
    if copied != value:
        raise ValueError("R2 research-control Audit outcome live seal differs")
    return copied


def _copy_facts(value: object) -> tuple[R2MonitoringRawFact, ...]:
    if type(value) is not tuple:
        raise TypeError("R2 research-control monitoring facts must be an exact tuple")
    copied: list[R2MonitoringRawFact] = []
    for item in value:
        if type(item) is not R2MonitoringRawFact:
            raise TypeError("R2 research-control monitoring fact type differs")
        fact = deepcopy(item)
        R2MonitoringRawFact.__post_init__(fact)
        if fact != item:
            raise ValueError("R2 research-control monitoring fact live seal differs")
        copied.append(fact)
    return tuple(copied)


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise TypeError("R2 research-control unit_of_work_key must be exact")
    return value


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "EvaluateR2ResearchControlPreflight",
    "EvaluateR2ResearchControlPreflightCommand",
    "R2LatestCompleteTrialMonitoringEvidence",
    "R2LatestCompleteTrialMonitoringProvider",
    "R2ResearchControlBlockerCode",
    "R2ResearchControlPreflightResult",
    "R2ResearchControlPreflightStatus",
    "R2ResearchControlUnavailable",
    "R2ResearchControlUnitOfWork",
]
