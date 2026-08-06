"""ID-only orchestration for the R5 relative-value Phase-A contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.fixed_income.domain.curve_relative_value import (
    BondMasterEvidence,
    CashFlowEvidence,
)
from apps.fixed_income.domain.evidence import (
    EvidenceLocator,
    ExactEvidence,
    exact_evidence_matches,
    require_aware,
    require_token,
)
from apps.fixed_income.domain.relative_value_assessment import (
    R5RelativeValueAssessment,
    R5RelativeValueBlocker,
    R5RelativeValueBlockerCode,
    R5RelativeValueInputSet,
    R5RelativeValuePolicySet,
    blocked_r5_relative_value_assessment,
    evaluate_r5_relative_value,
)


class PublicationEvidenceProvider(Protocol):
    """Reread one exact authoritative Publication identity/version."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> ExactEvidence | None:
        """Return the exact Publication or ``None`` without fallback/current fill."""


class BondMasterEvidenceProvider(Protocol):
    """Reread one exact authoritative BondMaster record."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> BondMasterEvidence | None:
        """Return the exact BondMaster record or ``None`` without synthesis."""


class CashFlowEvidenceProvider(Protocol):
    """Reread one exact authoritative CashFlow schedule/version."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> CashFlowEvidence | None:
        """Return the exact CashFlow evidence or ``None`` without fallback."""


class CalendarEvidenceProvider(Protocol):
    """Reread one exact authoritative Calendar content/version seal."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> ExactEvidence | None:
        """Return the exact Calendar seal or ``None`` without inferred periods."""


class ExactOwnerEvidenceProvider(Protocol):
    """Reread nested exact PIT/cohort/analytics/funding owner seals."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> ExactEvidence | None:
        """Return one exact nested owner seal or ``None`` without fallback."""


class ExactPITInputEvidenceProvider(Protocol):
    """Reread the fixed-income-owned exact PIT/current-target input set.

    Phase A does not claim an atomic snapshot or Unit-of-Work guarantee across
    the subsequent owner rereads.  Every call uses the same ``evaluated_at``;
    concrete atomic composition remains a Phase-B concern.
    """

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueInputSet | None:
        """Return the exact versioned input graph or ``None``."""


class R5RelativeValuePolicySetProvider(Protocol):
    """Reread one exact Research-governed four-component policy set."""

    def get_exact(
        self,
        locator: EvidenceLocator,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValuePolicySet | None:
        """Return the exact policy set or ``None`` without threshold defaults."""


@dataclass(frozen=True)
class RunR5RelativeValueResearchCommand:
    """ID/version-only request for one non-executable R5 assessment."""

    assessment_id: str
    input_set: EvidenceLocator
    policy_set: EvidenceLocator
    evaluated_at: datetime

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "RunR5RelativeValueResearchCommand.assessment_id")
        require_aware(self.evaluated_at, "RunR5RelativeValueResearchCommand.evaluated_at")


class RunR5RelativeValueResearch:
    """Authoritatively reread every exact owner record, then run pure Domain logic."""

    def __init__(
        self,
        *,
        input_provider: ExactPITInputEvidenceProvider,
        policy_provider: R5RelativeValuePolicySetProvider,
        publication_provider: PublicationEvidenceProvider,
        bond_master_provider: BondMasterEvidenceProvider,
        cash_flow_provider: CashFlowEvidenceProvider,
        calendar_provider: CalendarEvidenceProvider,
        exact_owner_provider: ExactOwnerEvidenceProvider,
    ) -> None:
        self._input_provider = input_provider
        self._policy_provider = policy_provider
        self._publication_provider = publication_provider
        self._bond_master_provider = bond_master_provider
        self._cash_flow_provider = cash_flow_provider
        self._calendar_provider = calendar_provider
        self._exact_owner_provider = exact_owner_provider

    def _blocked(
        self,
        command: RunR5RelativeValueResearchCommand,
        *,
        code: R5RelativeValueBlockerCode,
        detail: str,
        input_set_hash: str | None = None,
        policy_set_hash: str | None = None,
    ) -> R5RelativeValueAssessment:
        return blocked_r5_relative_value_assessment(
            assessment_id=command.assessment_id,
            input_set_id=command.input_set.evidence_id,
            input_set_version=command.input_set.version,
            policy_set_id=command.policy_set.evidence_id,
            policy_set_version=command.policy_set.version,
            evaluated_at=command.evaluated_at,
            input_set_hash=input_set_hash,
            policy_set_hash=policy_set_hash,
            blocker=R5RelativeValueBlocker(code=code, detail=detail),
        )

    def _reread_publications(
        self,
        input_set: R5RelativeValueInputSet,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueBlocker | None:
        for expected in input_set.publications:
            actual = self._publication_provider.get_exact(
                expected.locator,
                evaluated_at=evaluated_at,
            )
            if actual is None:
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING,
                    "Publication exact reread missing",
                )
            if not exact_evidence_matches(expected, actual):
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH,
                    "Publication exact reread mismatch",
                )
        return None

    def _reread_bond_masters(
        self,
        input_set: R5RelativeValueInputSet,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueBlocker | None:
        for expected in input_set.bond_masters:
            actual = self._bond_master_provider.get_exact(
                expected.evidence.locator,
                evaluated_at=evaluated_at,
            )
            if actual is None:
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING,
                    "BondMaster exact reread missing",
                )
            if (
                actual.evidence.locator != expected.evidence.locator
                or actual.master_hash != expected.master_hash
            ):
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH,
                    "BondMaster exact reread mismatch",
                )
        return None

    def _reread_cash_flows(
        self,
        input_set: R5RelativeValueInputSet,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueBlocker | None:
        for expected in input_set.cash_flows:
            actual = self._cash_flow_provider.get_exact(
                expected.evidence.locator,
                evaluated_at=evaluated_at,
            )
            if actual is None:
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING,
                    "CashFlow exact reread missing",
                )
            if (
                actual.evidence.locator != expected.evidence.locator
                or actual.schedule_hash != expected.schedule_hash
            ):
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH,
                    "CashFlow exact reread mismatch",
                )
        return None

    def _reread_calendars(
        self,
        input_set: R5RelativeValueInputSet,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueBlocker | None:
        for expected in input_set.calendars:
            actual = self._calendar_provider.get_exact(
                expected.locator,
                evaluated_at=evaluated_at,
            )
            if actual is None:
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING,
                    "Calendar exact reread missing",
                )
            if not exact_evidence_matches(expected, actual):
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH,
                    "Calendar exact reread mismatch",
                )
        return None

    def _reread_owner_exact_sources(
        self,
        input_set: R5RelativeValueInputSet,
        *,
        evaluated_at: datetime,
    ) -> R5RelativeValueBlocker | None:
        for expected in input_set.owner_exact_sources:
            actual = self._exact_owner_provider.get_exact(
                expected.locator,
                evaluated_at=evaluated_at,
            )
            if actual is None:
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISSING,
                    "nested exact owner reread missing",
                )
            if not exact_evidence_matches(expected, actual):
                return R5RelativeValueBlocker(
                    R5RelativeValueBlockerCode.EXACT_EVIDENCE_MISMATCH,
                    "nested exact owner reread mismatch",
                )
        return None

    def execute(
        self,
        command: RunR5RelativeValueResearchCommand,
    ) -> R5RelativeValueAssessment:
        """Reread exact IDs at one cutoff and return only research-safe output."""

        input_set = self._input_provider.get_exact(
            command.input_set,
            evaluated_at=command.evaluated_at,
        )
        if input_set is None:
            return self._blocked(
                command,
                code=R5RelativeValueBlockerCode.INPUT_SET_MISSING,
                detail="exact PIT input set missing",
            )
        if input_set.source.locator != command.input_set:
            return self._blocked(
                command,
                code=R5RelativeValueBlockerCode.LOCATOR_MISMATCH,
                detail="input set locator mismatch",
                input_set_hash=input_set.input_set_hash,
            )
        policy_set = self._policy_provider.get_exact(
            command.policy_set,
            evaluated_at=command.evaluated_at,
        )
        if policy_set is None:
            return self._blocked(
                command,
                code=R5RelativeValueBlockerCode.POLICY_SET_MISSING,
                detail="exact R5 policy set missing",
                input_set_hash=input_set.input_set_hash,
            )
        if policy_set.source.locator != command.policy_set:
            return self._blocked(
                command,
                code=R5RelativeValueBlockerCode.LOCATOR_MISMATCH,
                detail="policy set locator mismatch",
                input_set_hash=input_set.input_set_hash,
                policy_set_hash=policy_set.policy_set_hash,
            )
        for reread in (
            self._reread_publications,
            self._reread_bond_masters,
            self._reread_cash_flows,
            self._reread_calendars,
            self._reread_owner_exact_sources,
        ):
            blocker = reread(input_set, evaluated_at=command.evaluated_at)
            if blocker is not None:
                return self._blocked(
                    command,
                    code=blocker.code,
                    detail=blocker.detail,
                    input_set_hash=input_set.input_set_hash,
                    policy_set_hash=policy_set.policy_set_hash,
                )
        return evaluate_r5_relative_value(
            assessment_id=command.assessment_id,
            input_set=input_set,
            policy_set=policy_set,
            evaluated_at=command.evaluated_at,
        )


__all__ = [
    "BondMasterEvidenceProvider",
    "CalendarEvidenceProvider",
    "CashFlowEvidenceProvider",
    "ExactPITInputEvidenceProvider",
    "ExactOwnerEvidenceProvider",
    "PublicationEvidenceProvider",
    "R5RelativeValuePolicySetProvider",
    "RunR5RelativeValueResearch",
    "RunR5RelativeValueResearchCommand",
]
