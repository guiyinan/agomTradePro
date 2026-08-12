"""ID-only orchestration for the R2 explanatory trial and Phase-A monitoring.

Callers select a preregistered policy by exact identity only.  Every canonical
Publication, cycle PIT artifact, Audit outcome, and monitoring fact is reread
from its owner and its content seal is recomputed before Domain evaluation.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2_AUDIT_OUTCOME_VERSION,
    R2_MONITORING_FACT_VERSION,
    R2AuditExplanatoryOutcome,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExplanatoryTrialAssessment,
    R2MarketStructureTrialPolicy,
    R2MonitoringAssessment,
    R2MonitoringRawFact,
    R2PublicationKind,
    R2PublicationProjectionSeal,
    R2PublicationRef,
    R2TrialBlockerCode,
    R2TrialStatus,
    derive_r2_audit_outcome_id,
    derive_r2_monitoring_fact_id,
    evaluate_r2_explanatory_trial,
    evaluate_r2_monitoring,
    r2_audit_outcome_hash,
    r2_cycle_pit_evidence_hash,
    r2_monitoring_fact_hash,
    r2_publication_evidence_hash,
    r2_trial_policy_hash,
)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_token(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


class R2TrialMonitoringClock(Protocol):
    """Authoritative server clock used to reject future PIT cutoffs."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact storage snapshot identity used by owner reads."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class R2TrialMonitoringUnitOfWork(Protocol):
    """Shared transaction boundary for every authoritative R2 owner read."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one atomic owner-read transaction."""


class _R2UnitOfWorkParticipant(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""


class ExactR2TrialPolicyProvider(Protocol):
    """Research owner port for one exact preregistered policy body."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R2MarketStructureTrialPolicy | None:
        """Reread one policy by ID, version, hash, and PIT cutoff."""


class ExactR2CanonicalPublicationProvider(Protocol):
    """Canonical taxonomy/calendar owner port."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        kind: R2PublicationKind,
        reference: R2PublicationRef,
        expected_projection_hash: str,
        expected_available_at: datetime,
        expected_recorded_at: datetime,
        as_of: datetime,
    ) -> R2CanonicalPublicationEvidence | None:
        """Reread one exact owner Publication at the PIT cutoff."""


class ExactR2CyclePITEvidenceProvider(Protocol):
    """Owner port for exact complete-cycle PIT artifacts."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        evidence_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        as_of: datetime,
    ) -> R2CyclePITEvidence | None:
        """Reread one exact cycle artifact with both Publication bindings."""


class ExactR2AuditOutcomeProvider(Protocol):
    """Audit owner port for derived explanatory metrics and outcome."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def get_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        audit_plan_ref: R2EvidenceRef,
        cycle_evidence_refs: tuple[R2EvidenceRef, ...],
        expected_outcome_id: str,
        expected_outcome_version: str,
        as_of: datetime,
    ) -> R2AuditExplanatoryOutcome | None:
        """Reread the authoritative Audit outcome for the exact evidence graph."""


class ExactR2MonitoringRawFactProvider(Protocol):
    """Monitoring owner port returning raw facts, never an assessment."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database/snapshot identity."""

    def list_exact(
        self,
        *,
        policy_ref: R2EvidenceRef,
        taxonomy_publication_ref: R2PublicationRef,
        calendar_publication_ref: R2PublicationRef,
        expected_fact_identities: tuple[tuple[str, str], ...],
        as_of: datetime,
    ) -> tuple[R2MonitoringRawFact, ...]:
        """Reread the bounded raw-fact history known at the PIT cutoff."""


@dataclass(frozen=True)
class EvaluateR2MarketStructureTrialCommand:
    """Caller-safe selector containing no metric, evidence, or outcome payload."""

    policy_id: str
    policy_version: str
    expected_policy_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.policy_id, "R2 trial command policy_id")
        _require_token(self.policy_version, "R2 trial command policy_version")
        _require_hash(self.expected_policy_hash, "R2 trial command expected_policy_hash")
        _require_aware(self.as_of, "R2 trial command as_of")


@dataclass(frozen=True)
class _R2EvidenceGraph:
    policy: R2MarketStructureTrialPolicy
    taxonomy_publication: R2CanonicalPublicationEvidence
    calendar_publication: R2CanonicalPublicationEvidence
    cycles: tuple[R2CyclePITEvidence, ...]
    audit_outcome: R2AuditExplanatoryOutcome


@dataclass(frozen=True)
class _R2GraphLoad:
    graph: _R2EvidenceGraph | None
    policy_ref: R2EvidenceRef | None
    blockers: tuple[R2TrialBlockerCode, ...]


class R2TrialMonitoringUnavailable(RuntimeError):
    """A complete authoritative R2 owner graph is unavailable."""


@dataclass(frozen=True)
class R2ExplanatoryTrialEvaluationEvidence:
    """Complete double-read owner graph and locally derived trial result."""

    policy: R2MarketStructureTrialPolicy
    taxonomy_publication: R2CanonicalPublicationEvidence
    calendar_publication: R2CanonicalPublicationEvidence
    cycles: tuple[R2CyclePITEvidence, ...]
    audit_outcome: R2AuditExplanatoryOutcome
    assessment: R2ExplanatoryTrialAssessment

    def validated_copy(self) -> R2ExplanatoryTrialEvaluationEvidence:
        """Deep-copy and replay the full trial evidence graph."""

        rebuilt = deepcopy(self)
        if rebuilt.assessment != _evaluate_trial_graph(
            _R2EvidenceGraph(
                policy=rebuilt.policy,
                taxonomy_publication=rebuilt.taxonomy_publication,
                calendar_publication=rebuilt.calendar_publication,
                cycles=rebuilt.cycles,
                audit_outcome=rebuilt.audit_outcome,
            ),
            rebuilt.assessment.assessed_at,
        ):
            raise ValueError("R2 trial evidence assessment cannot be replayed")
        return rebuilt


@dataclass(frozen=True)
class R2MonitoringEvaluationEvidence:
    """Complete double-read trial graph, raw facts, and monitoring result."""

    trial: R2ExplanatoryTrialEvaluationEvidence
    facts: tuple[R2MonitoringRawFact, ...]
    assessment: R2MonitoringAssessment

    def validated_copy(self) -> R2MonitoringEvaluationEvidence:
        """Deep-copy and replay the complete monitoring evidence graph."""

        rebuilt = deepcopy(self)
        trial = rebuilt.trial.validated_copy()
        expected = evaluate_r2_monitoring(
            policy=trial.policy,
            taxonomy_publication=trial.taxonomy_publication,
            calendar_publication=trial.calendar_publication,
            trial_assessment=trial.assessment,
            facts=rebuilt.facts,
            assessed_at=rebuilt.assessment.assessed_at,
        )
        if rebuilt.assessment != expected:
            raise ValueError("R2 monitoring evidence assessment cannot be replayed")
        return rebuilt


def _exact_unit_of_work_key(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 192:
        raise ValueError("R2 trial monitoring unit_of_work_key is invalid")
    return value


class _R2SharedUnitOfWork:
    """Validate a stable shared UoW identity before and during execution."""

    def __init__(
        self,
        *,
        unit_of_work: R2TrialMonitoringUnitOfWork,
        participants: tuple[_R2UnitOfWorkParticipant, ...],
    ) -> None:
        self._unit_of_work = unit_of_work
        self._participants = participants
        self._expected_key = self.validate()

    @property
    def unit_of_work_key(self) -> str:
        """Return the construction baseline after live participant validation."""

        self.validate()
        return self._expected_key

    def validate(self) -> str:
        key = _exact_unit_of_work_key(self._unit_of_work.unit_of_work_key)
        participant_keys = tuple(
            _exact_unit_of_work_key(item.unit_of_work_key) for item in self._participants
        )
        if any(item != key for item in participant_keys):
            raise ValueError("R2 trial monitoring owners must share one unit of work")
        if hasattr(self, "_expected_key") and key != self._expected_key:
            raise ValueError("R2 trial monitoring unit of work identity changed")
        return key

    def atomic(self) -> AbstractContextManager[None]:
        self.validate()
        return self._unit_of_work.atomic()


class _R2EvidenceGraphLoader:
    def __init__(
        self,
        *,
        policy_provider: ExactR2TrialPolicyProvider,
        publication_provider: ExactR2CanonicalPublicationProvider,
        cycle_provider: ExactR2CyclePITEvidenceProvider,
        audit_provider: ExactR2AuditOutcomeProvider,
        clock: R2TrialMonitoringClock,
    ) -> None:
        self._policy_provider = policy_provider
        self._publication_provider = publication_provider
        self._cycle_provider = cycle_provider
        self._audit_provider = audit_provider
        self._clock = clock

    def load(self, command: EvaluateR2MarketStructureTrialCommand) -> _R2GraphLoad:
        """Dynamically reread and reseal the complete owner evidence graph."""

        try:
            server_now = self._clock.now()
            _require_aware(server_now, "R2 trial monitoring server clock")
        except Exception:  # noqa: BLE001 - authoritative clock boundary
            return _R2GraphLoad(
                graph=None,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.AUTHORITATIVE_CLOCK_UNAVAILABLE,),
            )
        if command.as_of > server_now:
            return _R2GraphLoad(
                graph=None,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.POLICY_FROM_FUTURE,),
            )

        try:
            policy = self._policy_provider.get_exact(
                policy_id=command.policy_id,
                policy_version=command.policy_version,
                expected_content_hash=command.expected_policy_hash,
                as_of=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner boundary must fail closed
            policy = None
        if policy is None:
            return _R2GraphLoad(
                graph=None,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.POLICY_MISSING,),
            )
        policy_ref = policy.reference
        if policy.policy_id != command.policy_id or policy.policy_version != (
            command.policy_version
        ):
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.POLICY_IDENTITY_MISMATCH,),
            )
        if policy.content_hash != command.expected_policy_hash or policy.content_hash != (
            r2_trial_policy_hash(policy)
        ):
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.POLICY_HASH_MISMATCH,),
            )

        taxonomy = self._load_publication(
            kind=R2PublicationKind.TAXONOMY,
            projection_seal=policy.taxonomy_projection_seal,
            as_of=command.as_of,
        )
        if taxonomy is None:
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.TAXONOMY_PUBLICATION_MISSING,),
            )
        if (
            taxonomy.reference != policy.taxonomy_publication_ref
            or taxonomy.kind is not R2PublicationKind.TAXONOMY
            or taxonomy.content_hash != policy.taxonomy_projection_seal.projection_hash
            or taxonomy.available_at != policy.taxonomy_projection_seal.available_at
            or taxonomy.recorded_at != policy.taxonomy_projection_seal.recorded_at
            or taxonomy.content_hash != r2_publication_evidence_hash(taxonomy)
        ):
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.PUBLICATION_REPLACED,),
            )

        calendar = self._load_publication(
            kind=R2PublicationKind.EXPECTED_PERIOD_CALENDAR,
            projection_seal=policy.calendar_projection_seal,
            as_of=command.as_of,
        )
        if calendar is None:
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.CALENDAR_PUBLICATION_MISSING,),
            )
        if (
            calendar.reference != policy.calendar_publication_ref
            or calendar.kind is not R2PublicationKind.EXPECTED_PERIOD_CALENDAR
            or calendar.content_hash != policy.calendar_projection_seal.projection_hash
            or calendar.available_at != policy.calendar_projection_seal.available_at
            or calendar.recorded_at != policy.calendar_projection_seal.recorded_at
            or calendar.content_hash != r2_publication_evidence_hash(calendar)
        ):
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.PUBLICATION_REPLACED,),
            )

        cycles: list[R2CyclePITEvidence] = []
        for cycle_definition in policy.cycles:
            try:
                evidence = self._cycle_provider.get_exact(
                    evidence_ref=cycle_definition.evidence_ref,
                    taxonomy_publication_ref=policy.taxonomy_publication_ref,
                    calendar_publication_ref=policy.calendar_publication_ref,
                    as_of=command.as_of,
                )
            except Exception:  # noqa: BLE001 - owner boundary must fail closed
                evidence = None
            if evidence is None:
                return _R2GraphLoad(
                    graph=None,
                    policy_ref=policy_ref,
                    blockers=(R2TrialBlockerCode.CYCLE_EVIDENCE_MISSING,),
                )
            if (
                evidence.reference != cycle_definition.evidence_ref
                or evidence.content_hash != r2_cycle_pit_evidence_hash(evidence)
            ):
                return _R2GraphLoad(
                    graph=None,
                    policy_ref=policy_ref,
                    blockers=(R2TrialBlockerCode.CYCLE_EVIDENCE_REPLACED,),
                )
            cycles.append(evidence)

        cycle_refs = tuple(item.reference for item in cycles)
        expected_outcome_id = derive_r2_audit_outcome_id(
            policy_ref=policy_ref,
            audit_plan_ref=policy.audit_plan_ref,
            cycle_evidence_refs=cycle_refs,
        )
        try:
            audit_outcome = self._audit_provider.get_exact(
                policy_ref=policy_ref,
                audit_plan_ref=policy.audit_plan_ref,
                cycle_evidence_refs=cycle_refs,
                expected_outcome_id=expected_outcome_id,
                expected_outcome_version=R2_AUDIT_OUTCOME_VERSION,
                as_of=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner boundary must fail closed
            audit_outcome = None
        if audit_outcome is None:
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.AUDIT_OUTCOME_MISSING,),
            )
        if (
            audit_outcome.outcome_id != expected_outcome_id
            or audit_outcome.outcome_version != R2_AUDIT_OUTCOME_VERSION
            or audit_outcome.content_hash != r2_audit_outcome_hash(audit_outcome)
        ):
            return _R2GraphLoad(
                graph=None,
                policy_ref=policy_ref,
                blockers=(R2TrialBlockerCode.AUDIT_OUTCOME_REPLACED,),
            )
        return _R2GraphLoad(
            graph=_R2EvidenceGraph(
                policy=policy,
                taxonomy_publication=taxonomy,
                calendar_publication=calendar,
                cycles=tuple(cycles),
                audit_outcome=audit_outcome,
            ),
            policy_ref=policy_ref,
            blockers=(),
        )

    def _load_publication(
        self,
        *,
        kind: R2PublicationKind,
        projection_seal: R2PublicationProjectionSeal,
        as_of: datetime,
    ) -> R2CanonicalPublicationEvidence | None:
        try:
            return self._publication_provider.get_exact(
                kind=kind,
                reference=projection_seal.reference,
                expected_projection_hash=projection_seal.projection_hash,
                expected_available_at=projection_seal.available_at,
                expected_recorded_at=projection_seal.recorded_at,
                as_of=as_of,
            )
        except Exception:  # noqa: BLE001 - owner boundary must fail closed
            return None


class EvaluateR2MarketStructureExplanatoryTrial:
    """Evaluate the preregistered two-cycle explanatory trial only."""

    def __init__(
        self,
        *,
        policy_provider: ExactR2TrialPolicyProvider,
        publication_provider: ExactR2CanonicalPublicationProvider,
        cycle_provider: ExactR2CyclePITEvidenceProvider,
        audit_provider: ExactR2AuditOutcomeProvider,
        clock: R2TrialMonitoringClock,
        unit_of_work: R2TrialMonitoringUnitOfWork,
    ) -> None:
        self._loader = _R2EvidenceGraphLoader(
            policy_provider=policy_provider,
            publication_provider=publication_provider,
            cycle_provider=cycle_provider,
            audit_provider=audit_provider,
            clock=clock,
        )
        self._shared_uow = _R2SharedUnitOfWork(
            unit_of_work=unit_of_work,
            participants=(
                policy_provider,
                publication_provider,
                cycle_provider,
                audit_provider,
                clock,
            ),
        )

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared UoW baseline after a live drift check."""

        return self._shared_uow.unit_of_work_key

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialAssessment:
        """Reread owner evidence and derive a research-only trial assessment."""

        result = self._execute(command)
        return (
            result.assessment
            if isinstance(result, R2ExplanatoryTrialEvaluationEvidence)
            else result
        )

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence:
        """Return a complete double-read graph or raise stable unavailability."""

        result = self._execute(command)
        if not isinstance(result, R2ExplanatoryTrialEvaluationEvidence):
            raise R2TrialMonitoringUnavailable(
                "complete R2 explanatory trial evidence is unavailable"
            )
        return result

    def _execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialEvaluationEvidence | R2ExplanatoryTrialAssessment:

        try:
            command.__post_init__()
            self._shared_uow.validate()
            with self._shared_uow.atomic():
                self._shared_uow.validate()
                first = self._loader.load(command)
                if first.graph is None:
                    return R2ExplanatoryTrialAssessment.blocked(
                        assessed_at=command.as_of,
                        policy_ref=first.policy_ref,
                        blockers=first.blockers,
                    )
                baseline = deepcopy(first.graph)
                first_assessment = _evaluate_trial_graph(baseline, command.as_of)
                second = self._loader.load(command)
                if second.graph is None:
                    return R2ExplanatoryTrialAssessment.blocked(
                        assessed_at=command.as_of,
                        policy_ref=second.policy_ref,
                        blockers=second.blockers,
                    )
                reread = deepcopy(second.graph)
                second_assessment = _evaluate_trial_graph(reread, command.as_of)
                self._shared_uow.validate()
                if baseline != reread or first_assessment != second_assessment:
                    raise ValueError("R2 trial owner graph changed during evaluation")
                return R2ExplanatoryTrialEvaluationEvidence(
                    policy=reread.policy,
                    taxonomy_publication=reread.taxonomy_publication,
                    calendar_publication=reread.calendar_publication,
                    cycles=reread.cycles,
                    audit_outcome=reread.audit_outcome,
                    assessment=second_assessment,
                ).validated_copy()
        except Exception:  # noqa: BLE001 - malformed owner/UoW content must block
            return R2ExplanatoryTrialAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )


def _evaluate_trial_graph(
    graph: _R2EvidenceGraph,
    assessed_at: datetime,
) -> R2ExplanatoryTrialAssessment:
    return evaluate_r2_explanatory_trial(
        policy=graph.policy,
        taxonomy_publication=graph.taxonomy_publication,
        calendar_publication=graph.calendar_publication,
        cycle_evidence=graph.cycles,
        audit_outcome=graph.audit_outcome,
        assessed_at=assessed_at,
    )


class EvaluateR2MarketStructureMonitoring:
    """Evaluate Phase-A monitoring after rereading the complete trial graph."""

    def __init__(
        self,
        *,
        policy_provider: ExactR2TrialPolicyProvider,
        publication_provider: ExactR2CanonicalPublicationProvider,
        cycle_provider: ExactR2CyclePITEvidenceProvider,
        audit_provider: ExactR2AuditOutcomeProvider,
        monitoring_fact_provider: ExactR2MonitoringRawFactProvider,
        clock: R2TrialMonitoringClock,
        unit_of_work: R2TrialMonitoringUnitOfWork,
    ) -> None:
        self._loader = _R2EvidenceGraphLoader(
            policy_provider=policy_provider,
            publication_provider=publication_provider,
            cycle_provider=cycle_provider,
            audit_provider=audit_provider,
            clock=clock,
        )
        self._monitoring_fact_provider = monitoring_fact_provider
        self._shared_uow = _R2SharedUnitOfWork(
            unit_of_work=unit_of_work,
            participants=(
                policy_provider,
                publication_provider,
                cycle_provider,
                audit_provider,
                monitoring_fact_provider,
                clock,
            ),
        )

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact shared UoW baseline after a live drift check."""

        return self._shared_uow.unit_of_work_key

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringAssessment:
        """Reread raw monitoring facts and derive a manual-review-only assessment."""

        result = self._execute(command)
        return result.assessment if isinstance(result, R2MonitoringEvaluationEvidence) else result

    def execute_evidence(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringEvaluationEvidence:
        """Return complete double-read monitoring evidence or stable unavailability."""

        result = self._execute(command)
        if not isinstance(result, R2MonitoringEvaluationEvidence):
            raise R2TrialMonitoringUnavailable("complete R2 monitoring evidence is unavailable")
        return result

    def _execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringEvaluationEvidence | R2MonitoringAssessment:

        try:
            command.__post_init__()
            self._shared_uow.validate()
            with self._shared_uow.atomic():
                self._shared_uow.validate()
                first = self._evaluate_once(command)
                if isinstance(first, R2MonitoringAssessment):
                    return first
                baseline = deepcopy(first)
                second = self._evaluate_once(command)
                if isinstance(second, R2MonitoringAssessment):
                    return second
                reread = deepcopy(second)
                self._shared_uow.validate()
                if baseline != reread:
                    raise ValueError("R2 monitoring owner graph changed during evaluation")
                graph = reread.graph
                return R2MonitoringEvaluationEvidence(
                    trial=R2ExplanatoryTrialEvaluationEvidence(
                        policy=graph.policy,
                        taxonomy_publication=graph.taxonomy_publication,
                        calendar_publication=graph.calendar_publication,
                        cycles=graph.cycles,
                        audit_outcome=graph.audit_outcome,
                        assessment=reread.trial_assessment,
                    ),
                    facts=reread.facts,
                    assessment=reread.assessment,
                ).validated_copy()
        except Exception:  # noqa: BLE001 - malformed owner/UoW content must block
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )

    def _evaluate_once(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> _R2MonitoringRun | R2MonitoringAssessment:
        loaded = self._loader.load(command)
        if loaded.graph is None:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=loaded.policy_ref,
                blockers=loaded.blockers,
            )
        graph = loaded.graph
        trial_assessment = _evaluate_trial_graph(graph, command.as_of)
        if trial_assessment.status is not R2TrialStatus.PASSED:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(
                    trial_assessment.blockers
                    if trial_assessment.blockers
                    else (R2TrialBlockerCode.AUDIT_OUTCOME_INVALID,)
                ),
            )
        try:
            completed_period_ids = tuple(
                item.period_id
                for item in graph.policy.expected_periods
                if item.period_start >= graph.policy.selection_as_of
                and item.period_end <= command.as_of
            )
            expected_fact_identities = tuple(
                (
                    derive_r2_monitoring_fact_id(
                        policy_ref=graph.policy.reference,
                        period_id=period_id,
                    ),
                    R2_MONITORING_FACT_VERSION,
                )
                for period_id in completed_period_ids
            )
            facts = self._monitoring_fact_provider.list_exact(
                policy_ref=graph.policy.reference,
                taxonomy_publication_ref=graph.policy.taxonomy_publication_ref,
                calendar_publication_ref=graph.policy.calendar_publication_ref,
                expected_fact_identities=expected_fact_identities,
                as_of=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner boundary must fail closed
            facts = ()
        if not facts:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.MONITORING_FACTS_MISSING,),
            )
        try:
            facts_replaced = any(
                fact.content_hash != r2_monitoring_fact_hash(fact) for fact in facts
            )
        except Exception:  # noqa: BLE001 - malformed owner fact must block
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )
        if facts_replaced:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.MONITORING_FACT_REPLACED,),
            )
        actual_fact_identities = tuple(
            (item.fact_id, item.fact_version)
            for item in sorted(facts, key=lambda value: value.period_start)
        )
        if actual_fact_identities != expected_fact_identities:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.MONITORING_FACT_REPLACED,),
            )
        assessment = evaluate_r2_monitoring(
            policy=graph.policy,
            taxonomy_publication=graph.taxonomy_publication,
            calendar_publication=graph.calendar_publication,
            trial_assessment=trial_assessment,
            facts=facts,
            assessed_at=command.as_of,
        )
        return _R2MonitoringRun(
            graph=graph,
            trial_assessment=trial_assessment,
            facts=facts,
            assessment=assessment,
        )


@dataclass(frozen=True)
class _R2MonitoringRun:
    graph: _R2EvidenceGraph
    trial_assessment: R2ExplanatoryTrialAssessment
    facts: tuple[R2MonitoringRawFact, ...]
    assessment: R2MonitoringAssessment


__all__ = [
    "EvaluateR2MarketStructureExplanatoryTrial",
    "EvaluateR2MarketStructureMonitoring",
    "EvaluateR2MarketStructureTrialCommand",
    "ExactR2AuditOutcomeProvider",
    "ExactR2CanonicalPublicationProvider",
    "ExactR2CyclePITEvidenceProvider",
    "ExactR2MonitoringRawFactProvider",
    "ExactR2TrialPolicyProvider",
    "R2TrialMonitoringClock",
    "R2ExplanatoryTrialEvaluationEvidence",
    "R2MonitoringEvaluationEvidence",
    "R2TrialMonitoringUnavailable",
    "R2TrialMonitoringUnitOfWork",
]
