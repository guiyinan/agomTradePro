"""ID-only persistence contracts for the R5 relative-value audit ledger."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.fixed_income.application.relative_value import (
    R5AuthoritativeRelativeValueRun,
    RunR5RelativeValueResearchCommand,
)
from apps.fixed_income.domain.evidence import (
    EvidenceLocator,
    ExactEvidence,
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)
from apps.fixed_income.domain.relative_value_assessment import (
    R5RelativeValueAssessment,
    R5RelativeValueInputSet,
    R5RelativeValuePolicySet,
)

R5_INPUT_RECEIPT_VERSION = "fixed-income-r5-input-receipt.v1"
R5_RESULT_RECORD_VERSION = "fixed-income-r5-result-record.v1"


class R5RelativeValuePersistenceConflict(ValueError):
    """Raised for duplicate identities, missing evidence, or UoW conflicts."""


class R5RelativeValuePersistenceCorruption(ValueError):
    """Raised when persisted headers, payloads, or FK graphs disagree."""


def _stable_id(namespace: str, assessment_id: str) -> str:
    require_token(assessment_id, "assessment_id")
    return f"r5:{namespace}:{canonical_hash((namespace, assessment_id))}"


def stable_r5_input_receipt_id(assessment_id: str) -> str:
    """Return the deterministic receipt identity for one assessment command."""

    return _stable_id("input", assessment_id)


def stable_r5_result_record_id(assessment_id: str) -> str:
    """Return the deterministic result identity for one assessment command."""

    return _stable_id("result", assessment_id)


def r5_persistence_command_hash(
    *,
    assessment_id: str,
    input_set: EvidenceLocator,
    policy_set: EvidenceLocator,
    evaluated_at: datetime,
) -> str:
    """Hash the complete ID/version/cutoff persistence command boundary."""

    require_token(assessment_id, "assessment_id")
    require_aware(evaluated_at, "evaluated_at")
    return canonical_hash(
        {
            "assessment_id": assessment_id,
            "input_set": input_set,
            "policy_set": policy_set,
            "evaluated_at": evaluated_at,
        }
    )


def collect_r5_persistence_evidence(
    input_set: R5RelativeValueInputSet,
    policy_set: R5RelativeValuePolicySet,
) -> tuple[ExactEvidence, ...]:
    """Return the complete canonical owner/policy evidence clock graph."""

    items = (
        input_set.source,
        *input_set.publications,
        *(item.evidence for item in input_set.bond_masters),
        *(item.evidence for item in input_set.cash_flows),
        *input_set.calendars,
        *input_set.owner_exact_sources,
        policy_set.source,
        policy_set.spread_policy.evidence,
        policy_set.rating_policy.evidence,
        policy_set.liquidity_policy.evidence,
        policy_set.curve_policy.evidence,
    )
    by_locator: dict[tuple[str, str], ExactEvidence] = {}
    for item in items:
        key = (item.evidence_id, item.version)
        existing = by_locator.get(key)
        if existing is not None and existing.seal_hash != item.seal_hash:
            raise R5RelativeValuePersistenceCorruption(
                "one persistence evidence locator has conflicting seals"
            )
        by_locator[key] = item
    return tuple(
        sorted(
            by_locator.values(),
            key=lambda item: (item.evidence_id, item.version, item.seal_hash),
        )
    )


def r5_evidence_clock_graph_hash(
    input_set: R5RelativeValueInputSet,
    policy_set: R5RelativeValuePolicySet,
) -> str:
    """Seal every original owner clock without imposing a second freshness rule."""

    return canonical_hash(
        {
            "evidence_clocks": tuple(
                {
                    "evidence_id": item.evidence_id,
                    "version": item.version,
                    "role": item.role,
                    "owner": item.owner,
                    "observed_at": item.observed_at,
                    "available_at": item.available_at,
                    "valid_until": item.valid_until,
                    "seal_hash": item.seal_hash,
                }
                for item in collect_r5_persistence_evidence(
                    input_set,
                    policy_set,
                )
            )
        }
    )


@dataclass(frozen=True)
class R5RelativeValuePersistenceDraft:
    """Verified Phase-A graphs awaiting one server-clocked atomic append."""

    assessment_id: str
    input_set: R5RelativeValueInputSet
    policy_set: R5RelativeValuePolicySet
    assessment: R5RelativeValueAssessment

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "R5RelativeValuePersistenceDraft.assessment_id")
        if self.assessment.assessment_id != self.assessment_id:
            raise ValueError("R5 persistence draft assessment identity mismatch")
        if (
            self.assessment.input_set_id != self.input_set.input_set_id
            or self.assessment.input_set_version != self.input_set.input_set_version
            or self.assessment.input_set_hash != self.input_set.input_set_hash
        ):
            raise ValueError("R5 persistence draft input graph mismatch")
        if (
            self.assessment.policy_set_id != self.policy_set.policy_set_id
            or self.assessment.policy_set_version != self.policy_set.policy_set_version
            or self.assessment.policy_set_hash != self.policy_set.policy_set_hash
        ):
            raise ValueError("R5 persistence draft policy graph mismatch")
        if self.assessment.output_hash != self.assessment.calculated_output_hash:
            raise ValueError("R5 persistence draft assessment is not replayable")

    @classmethod
    def from_authoritative_run(
        cls,
        run: R5AuthoritativeRelativeValueRun,
    ) -> R5RelativeValuePersistenceDraft:
        """Narrow a fully reread Phase-A run into a persistence draft."""

        if not run.owner_graph_verified or run.input_set is None or run.policy_set is None:
            raise R5RelativeValuePersistenceConflict(
                "R5 persistence requires a fully verified owner graph"
            )
        return cls(
            assessment_id=run.assessment.assessment_id,
            input_set=run.input_set,
            policy_set=run.policy_set,
            assessment=run.assessment,
        )

    @property
    def evidence_clock_graph_hash(self) -> str:
        """Return the full original owner-clock audit seal."""

        return r5_evidence_clock_graph_hash(self.input_set, self.policy_set)

    @property
    def draft_hash(self) -> str:
        """Hash the complete exact graphs before the server clock is claimed."""

        return canonical_hash(
            {
                "assessment_id": self.assessment_id,
                "input_set": self.input_set,
                "policy_set": self.policy_set,
                "assessment": self.assessment,
                "evidence_clock_graph_hash": self.evidence_clock_graph_hash,
            }
        )

    @property
    def expected_command_hash(self) -> str:
        """Rebuild the only ID-only command that may authorize this draft."""

        return r5_persistence_command_hash(
            assessment_id=self.assessment_id,
            input_set=self.input_set.source.locator,
            policy_set=self.policy_set.source.locator,
            evaluated_at=self.assessment.evaluated_at,
        )


@dataclass(frozen=True)
class R5RelativeValueInputReceipt:
    """Server-clocked fixed-income receipt for exact Phase-A input graphs."""

    receipt_id: str
    receipt_version: str
    owner: str
    command_hash: str
    assessment_id: str
    evaluated_at: datetime
    recorded_at: datetime
    evidence_clock_graph_hash: str
    input_set: R5RelativeValueInputSet
    policy_set: R5RelativeValuePolicySet
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        for name in ("receipt_id", "receipt_version", "owner", "assessment_id"):
            require_token(
                str(getattr(self, name)),
                f"R5RelativeValueInputReceipt.{name}",
            )
        for name in ("evaluated_at", "recorded_at"):
            require_aware(
                getattr(self, name),
                f"R5RelativeValueInputReceipt.{name}",
            )
        if self.receipt_id != stable_r5_input_receipt_id(self.assessment_id):
            raise ValueError("R5 input receipt stable identity mismatch")
        if self.receipt_version != R5_INPUT_RECEIPT_VERSION:
            raise ValueError("R5 input receipt version mismatch")
        if self.owner != "fixed_income":
            raise ValueError("R5 input receipt owner must be fixed_income")
        require_sha256(self.command_hash, "R5RelativeValueInputReceipt.command_hash")
        if self.command_hash != r5_persistence_command_hash(
            assessment_id=self.assessment_id,
            input_set=self.input_set.source.locator,
            policy_set=self.policy_set.source.locator,
            evaluated_at=self.evaluated_at,
        ):
            raise ValueError("R5 input receipt command hash mismatch")
        if self.recorded_at < self.evaluated_at:
            raise ValueError("R5 input receipt server clock precedes evaluation")
        require_sha256(
            self.evidence_clock_graph_hash,
            "R5RelativeValueInputReceipt.evidence_clock_graph_hash",
        )
        if self.evidence_clock_graph_hash != r5_evidence_clock_graph_hash(
            self.input_set,
            self.policy_set,
        ):
            raise ValueError("R5 input receipt evidence-clock seal mismatch")
        if not (self.research_only and self.must_not_execute and self.must_not_use_for_decision):
            raise ValueError("R5 input receipt must remain research-only")

    @classmethod
    def from_draft(
        cls,
        draft: R5RelativeValuePersistenceDraft,
        *,
        recorded_at: datetime,
    ) -> R5RelativeValueInputReceipt:
        """Claim one receipt using only the repository server clock."""

        require_aware(recorded_at, "recorded_at")
        return cls(
            receipt_id=stable_r5_input_receipt_id(draft.assessment_id),
            receipt_version=R5_INPUT_RECEIPT_VERSION,
            owner="fixed_income",
            command_hash=draft.expected_command_hash,
            assessment_id=draft.assessment_id,
            evaluated_at=draft.assessment.evaluated_at,
            recorded_at=recorded_at,
            evidence_clock_graph_hash=draft.evidence_clock_graph_hash,
            input_set=draft.input_set,
            policy_set=draft.policy_set,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )

    @property
    def receipt_hash(self) -> str:
        """Hash every header, graph, clock and safety boundary."""

        return canonical_hash(self)


@dataclass(frozen=True)
class R5RelativeValueResultRecord:
    """Complete persisted composite linked to one exact input receipt."""

    result_id: str
    result_version: str
    owner: str
    command_hash: str
    receipt_id: str
    receipt_version: str
    receipt_hash: str
    recorded_at: datetime
    evidence_clock_graph_hash: str
    assessment: R5RelativeValueAssessment
    research_only: bool
    must_not_execute: bool
    must_not_use_for_decision: bool

    def __post_init__(self) -> None:
        for name in (
            "result_id",
            "result_version",
            "owner",
            "receipt_id",
            "receipt_version",
        ):
            require_token(
                str(getattr(self, name)),
                f"R5RelativeValueResultRecord.{name}",
            )
        require_sha256(self.receipt_hash, "R5RelativeValueResultRecord.receipt_hash")
        require_aware(self.recorded_at, "R5RelativeValueResultRecord.recorded_at")
        require_sha256(
            self.evidence_clock_graph_hash,
            "R5RelativeValueResultRecord.evidence_clock_graph_hash",
        )
        if self.result_id != stable_r5_result_record_id(self.assessment.assessment_id):
            raise ValueError("R5 result stable identity mismatch")
        if self.result_version != R5_RESULT_RECORD_VERSION:
            raise ValueError("R5 result version mismatch")
        if self.owner != "fixed_income":
            raise ValueError("R5 result owner must be fixed_income")
        require_sha256(self.command_hash, "R5RelativeValueResultRecord.command_hash")
        if (
            self.receipt_id != stable_r5_input_receipt_id(self.assessment.assessment_id)
            or self.receipt_version != R5_INPUT_RECEIPT_VERSION
        ):
            raise ValueError("R5 result receipt identity mismatch")
        if self.recorded_at < self.assessment.evaluated_at:
            raise ValueError("R5 result server clock precedes evaluation")
        if not (
            self.research_only
            and self.must_not_execute
            and self.must_not_use_for_decision
            and self.assessment.research_only
            and self.assessment.must_not_execute
            and self.assessment.must_not_use_for_decision
        ):
            raise ValueError("R5 result record must remain research-only")

    @classmethod
    def from_receipt(
        cls,
        receipt: R5RelativeValueInputReceipt,
        assessment: R5RelativeValueAssessment,
    ) -> R5RelativeValueResultRecord:
        """Bind the complete composite to its exact server receipt."""

        return cls(
            result_id=stable_r5_result_record_id(assessment.assessment_id),
            result_version=R5_RESULT_RECORD_VERSION,
            owner="fixed_income",
            command_hash=receipt.command_hash,
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            receipt_hash=receipt.receipt_hash,
            recorded_at=receipt.recorded_at,
            evidence_clock_graph_hash=receipt.evidence_clock_graph_hash,
            assessment=assessment,
            research_only=True,
            must_not_execute=True,
            must_not_use_for_decision=True,
        )

    @property
    def record_hash(self) -> str:
        """Hash the receipt link and complete composite output graph."""

        return canonical_hash(self)


@dataclass(frozen=True)
class R5PersistedRelativeValueBundle:
    """Atomic fixed-income input receipt and complete composite result."""

    receipt: R5RelativeValueInputReceipt
    result: R5RelativeValueResultRecord

    def __post_init__(self) -> None:
        if (
            self.result.receipt_id != self.receipt.receipt_id
            or self.result.command_hash != self.receipt.command_hash
            or self.result.receipt_version != self.receipt.receipt_version
            or self.result.receipt_hash != self.receipt.receipt_hash
            or self.result.recorded_at != self.receipt.recorded_at
            or self.result.evidence_clock_graph_hash != self.receipt.evidence_clock_graph_hash
            or self.result.assessment.assessment_id != self.receipt.assessment_id
            or self.result.assessment.evaluated_at != self.receipt.evaluated_at
            or self.result.assessment.input_set_hash != self.receipt.input_set.input_set_hash
            or self.result.assessment.input_set_id != self.receipt.input_set.input_set_id
            or self.result.assessment.input_set_version != self.receipt.input_set.input_set_version
            or self.result.assessment.policy_set_hash != self.receipt.policy_set.policy_set_hash
            or self.result.assessment.policy_set_id != self.receipt.policy_set.policy_set_id
            or self.result.assessment.policy_set_version
            != self.receipt.policy_set.policy_set_version
        ):
            raise ValueError("R5 persisted receipt/result graph mismatch")

    @classmethod
    def from_draft(
        cls,
        draft: R5RelativeValuePersistenceDraft,
        *,
        recorded_at: datetime,
    ) -> R5PersistedRelativeValueBundle:
        """Create the only exact bundle a repository may append."""

        receipt = R5RelativeValueInputReceipt.from_draft(
            draft,
            recorded_at=recorded_at,
        )
        return cls(
            receipt=receipt,
            result=R5RelativeValueResultRecord.from_receipt(
                receipt,
                draft.assessment,
            ),
        )


class R5RelativeValuePersistenceRepository(Protocol):
    """Exact audit-query port for the fixed-income-owned ledger."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction boundary key."""

    def get_exact(
        self,
        *,
        result_id: str,
        result_version: str,
        expected_record_hash: str,
        as_of: datetime,
    ) -> R5PersistedRelativeValueBundle | None:
        """Return one exact audit record known at ``as_of``."""


class R5CrossOwnerUnitOfWork(Protocol):
    """Atomic Application boundary shared by Data Center, Portfolio and Research."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared opaque transaction boundary key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Activate every owner Application UoW in one database transaction."""


class R5OwnerAtomicApplicationPort(Protocol):
    """One canonical owner's Application-level atomic boundary."""

    @property
    def owner(self) -> str:
        """Return the canonical owner name."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the owner's opaque transaction boundary key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Activate the owner's own transaction and ContextVar guard."""

    def require_active_unit_of_work(self) -> None:
        """Fail closed unless the owner Application UoW is active."""


@dataclass(frozen=True)
class PersistR5RelativeValueCommand:
    """ID/version/cutoff-only command; no caller payload, hash, or server clock."""

    assessment_id: str
    input_set: EvidenceLocator
    policy_set: EvidenceLocator
    evaluated_at: datetime

    def __post_init__(self) -> None:
        require_token(self.assessment_id, "PersistR5RelativeValueCommand.assessment_id")
        require_aware(self.evaluated_at, "PersistR5RelativeValueCommand.evaluated_at")

    @property
    def phase_a_command(self) -> RunR5RelativeValueResearchCommand:
        """Project the unchanged Phase-A ID-only request."""

        return RunR5RelativeValueResearchCommand(
            assessment_id=self.assessment_id,
            input_set=self.input_set,
            policy_set=self.policy_set,
            evaluated_at=self.evaluated_at,
        )

    @property
    def command_hash(self) -> str:
        """Hash only the ID/version/cutoff command boundary."""

        return r5_persistence_command_hash(
            assessment_id=self.assessment_id,
            input_set=self.input_set,
            policy_set=self.policy_set,
            evaluated_at=self.evaluated_at,
        )


class R5RelativeValuePersistenceWriter(Protocol):
    """Trusted ID-only writer implemented by the fixed-income composition root."""

    def persist(
        self,
        command: PersistR5RelativeValueCommand,
    ) -> R5PersistedRelativeValueBundle:
        """Authoritatively reread and atomically append one exact bundle."""


@dataclass(frozen=True)
class GetExactR5RelativeValueCommand:
    """Exact audit query without latest/current/list semantics."""

    result_id: str
    result_version: str
    expected_record_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        require_token(self.result_id, "GetExactR5RelativeValueCommand.result_id")
        require_token(
            self.result_version,
            "GetExactR5RelativeValueCommand.result_version",
        )
        require_sha256(
            self.expected_record_hash,
            "GetExactR5RelativeValueCommand.expected_record_hash",
        )
        require_aware(self.as_of, "GetExactR5RelativeValueCommand.as_of")


class PersistR5RelativeValue:
    """Reread every owner and append receipt/result inside one shared UoW."""

    def __init__(
        self,
        *,
        writer: R5RelativeValuePersistenceWriter,
    ) -> None:
        self._writer = writer

    def execute(
        self,
        command: PersistR5RelativeValueCommand,
    ) -> R5PersistedRelativeValueBundle:
        """Reread, evaluate, claim and append without a TOCTOU gap."""

        return self._writer.persist(command)


class GetExactPersistedR5RelativeValue:
    """Read one exact strictly restored historical audit record."""

    def __init__(
        self,
        repository: R5RelativeValuePersistenceRepository,
    ) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR5RelativeValueCommand,
    ) -> R5PersistedRelativeValueBundle | None:
        """Return a hash-bound record only after its server knowledge time."""

        return self._repository.get_exact(
            result_id=command.result_id,
            result_version=command.result_version,
            expected_record_hash=command.expected_record_hash,
            as_of=command.as_of,
        )


__all__ = [
    "GetExactPersistedR5RelativeValue",
    "GetExactR5RelativeValueCommand",
    "PersistR5RelativeValue",
    "PersistR5RelativeValueCommand",
    "R5CrossOwnerUnitOfWork",
    "R5OwnerAtomicApplicationPort",
    "R5PersistedRelativeValueBundle",
    "R5RelativeValueInputReceipt",
    "R5RelativeValuePersistenceConflict",
    "R5RelativeValuePersistenceCorruption",
    "R5RelativeValuePersistenceDraft",
    "R5RelativeValuePersistenceRepository",
    "R5RelativeValuePersistenceWriter",
    "R5RelativeValueResultRecord",
    "collect_r5_persistence_evidence",
    "r5_persistence_command_hash",
    "r5_evidence_clock_graph_hash",
    "stable_r5_input_receipt_id",
    "stable_r5_result_record_id",
]
