"""ID-only orchestration for the R2 explanatory trial and Phase-A monitoring.

Callers select a preregistered policy by exact identity only.  Every canonical
Publication, cycle PIT artifact, Audit outcome, and monitoring fact is reread
from its owner and its content seal is recomputed before Domain evaluation.
"""

from __future__ import annotations

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

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class ExactR2TrialPolicyProvider(Protocol):
    """Research owner port for one exact preregistered policy body."""

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
    ) -> None:
        self._loader = _R2EvidenceGraphLoader(
            policy_provider=policy_provider,
            publication_provider=publication_provider,
            cycle_provider=cycle_provider,
            audit_provider=audit_provider,
            clock=clock,
        )

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2ExplanatoryTrialAssessment:
        """Reread owner evidence and derive a research-only trial assessment."""

        try:
            loaded = self._loader.load(command)
        except Exception:  # noqa: BLE001 - malformed owner content must block
            return R2ExplanatoryTrialAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )
        if loaded.graph is None:
            return R2ExplanatoryTrialAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=loaded.policy_ref,
                blockers=loaded.blockers,
            )
        graph = loaded.graph
        try:
            return evaluate_r2_explanatory_trial(
                policy=graph.policy,
                taxonomy_publication=graph.taxonomy_publication,
                calendar_publication=graph.calendar_publication,
                cycle_evidence=graph.cycles,
                audit_outcome=graph.audit_outcome,
                assessed_at=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner graph must not escape as an error
            return R2ExplanatoryTrialAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
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
    ) -> None:
        self._loader = _R2EvidenceGraphLoader(
            policy_provider=policy_provider,
            publication_provider=publication_provider,
            cycle_provider=cycle_provider,
            audit_provider=audit_provider,
            clock=clock,
        )
        self._monitoring_fact_provider = monitoring_fact_provider

    def execute(
        self,
        command: EvaluateR2MarketStructureTrialCommand,
    ) -> R2MonitoringAssessment:
        """Reread raw monitoring facts and derive a manual-review-only assessment."""

        try:
            loaded = self._loader.load(command)
        except Exception:  # noqa: BLE001 - malformed owner content must block
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=None,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )
        if loaded.graph is None:
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=loaded.policy_ref,
                blockers=loaded.blockers,
            )
        graph = loaded.graph
        try:
            trial_assessment = evaluate_r2_explanatory_trial(
                policy=graph.policy,
                taxonomy_publication=graph.taxonomy_publication,
                calendar_publication=graph.calendar_publication,
                cycle_evidence=graph.cycles,
                audit_outcome=graph.audit_outcome,
                assessed_at=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner graph must not escape as an error
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )
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
        try:
            return evaluate_r2_monitoring(
                policy=graph.policy,
                taxonomy_publication=graph.taxonomy_publication,
                calendar_publication=graph.calendar_publication,
                trial_assessment=trial_assessment,
                facts=facts,
                assessed_at=command.as_of,
            )
        except Exception:  # noqa: BLE001 - owner facts must not escape as an error
            return R2MonitoringAssessment.blocked(
                assessed_at=command.as_of,
                policy_ref=graph.policy.reference,
                blockers=(R2TrialBlockerCode.OWNER_EVIDENCE_UNAVAILABLE,),
            )


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
]
