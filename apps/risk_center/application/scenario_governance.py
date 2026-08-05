"""Application ports and use cases for governed stress-scenario writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from apps.risk_center.application.scenario_dtos import (
    CreateScenarioRevisionCommandDTO,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActor,
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
    ScenarioGovernanceOutcome,
    governance_json_value,
    require_human_staff,
)
from apps.risk_center.domain.scenarios import scenario_parameters_to_dict


@dataclass(frozen=True)
class ScenarioGovernanceTarget:
    """Typed target selectors shared by preview and commit requests."""

    scenario_key: str | None = None
    scenario_set_revision_id: str | None = None
    environment: str | None = None
    purpose: str | None = None
    target_version: int | None = None

    def validate_for(self, operation: ScenarioGovernanceOperation) -> None:
        """Reject incomplete or ambiguous operation targets."""

        if operation in {
            ScenarioGovernanceOperation.PROPOSE,
            ScenarioGovernanceOperation.RETIRE,
        }:
            if self.scenario_key is None or not self.scenario_key.strip():
                raise ValueError(f"{operation.value} requires scenario_key")
        if operation is ScenarioGovernanceOperation.ACTIVATE:
            self._require_scope()
            if self.scenario_set_revision_id is None or not self.scenario_set_revision_id.strip():
                raise ValueError("activate requires scenario_set_revision_id")
        if operation is ScenarioGovernanceOperation.ROLLBACK:
            self._require_scope()
            if self.target_version is None or self.target_version < 1:
                raise ValueError("rollback requires a positive target_version")
            if self.scenario_key is None or not self.scenario_key.strip():
                raise ValueError("rollback requires the scenario set key in scenario_key")

    def as_dict(self) -> dict[str, object]:
        """Return exact target selectors for request fingerprinting."""

        return {
            "scenario_key": self.scenario_key,
            "scenario_set_revision_id": self.scenario_set_revision_id,
            "environment": self.environment,
            "purpose": self.purpose,
            "target_version": self.target_version,
        }

    def _require_scope(self) -> None:
        for field_name, value in (
            ("environment", self.environment),
            ("purpose", self.purpose),
        ):
            if value is None or not value.strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class ScenarioGovernanceRequest:
    """Exact business request reused for preview, proposal, and commit."""

    actor: ScenarioGovernanceActor
    capability_key: str
    operation: ScenarioGovernanceOperation
    payload: Mapping[str, object]
    target: ScenarioGovernanceTarget
    change_reason: str
    correlation_id: str
    expected_base_version: int | None
    expected_base_hash: str | None
    revision_command: CreateScenarioRevisionCommandDTO | None = None

    def __post_init__(self) -> None:
        """Normalize metadata and enforce operation-specific request shapes."""

        capability_key = self.capability_key.strip()
        change_reason = self.change_reason.strip()
        correlation_id = self.correlation_id.strip()
        for field_name, value, maximum in (
            ("capability_key", capability_key, 160),
            ("change_reason", change_reason, 2_000),
            ("correlation_id", correlation_id, 120),
        ):
            if not value or len(value) > maximum:
                raise ValueError(f"{field_name} must contain at most {maximum} characters")
        if self.expected_base_version is not None and self.expected_base_version < 1:
            raise ValueError("expected_base_version must be positive")
        if self.expected_base_hash is not None and not _is_sha256(self.expected_base_hash):
            raise ValueError("expected_base_hash must be a lower-case SHA-256 digest")
        if any(not isinstance(key, str) for key in self.payload):
            raise ValueError("scenario governance payload keys must be strings")
        safe_payload = governance_json_value(self.payload)
        if not isinstance(safe_payload, Mapping):
            raise ValueError("scenario governance payload must be an object")
        self.target.validate_for(self.operation)
        if self.operation is ScenarioGovernanceOperation.PROPOSE:
            if self.revision_command is None:
                raise ValueError("propose requires a typed revision_command")
            if self.revision_command.scenario_key != self.target.scenario_key:
                raise ValueError("revision command scenario_key does not match target")
            if self.revision_command.based_on_version != self.expected_base_version:
                raise ValueError("revision based_on_version does not match expected base")
        elif self.revision_command is not None:
            raise ValueError("revision_command is only valid for propose")
        object.__setattr__(self, "capability_key", capability_key)
        object.__setattr__(self, "change_reason", change_reason)
        object.__setattr__(self, "correlation_id", correlation_id)
        object.__setattr__(self, "payload", cast(Mapping[str, object], safe_payload))

    def exact_payload(self) -> dict[str, object]:
        """Return every business field that a persisted preview must bind."""

        return {
            "payload": self.payload,
            "target": self.target.as_dict(),
            "change_reason": self.change_reason,
            "correlation_id": self.correlation_id,
            "revision_command": (
                _revision_command_payload(self.revision_command)
                if self.revision_command is not None
                else None
            ),
        }


@dataclass(frozen=True)
class PreviewScenarioGovernanceCommand:
    """Persist a bounded preview for one exact request."""

    request: ScenarioGovernanceRequest
    expires_at: datetime

    def __post_init__(self) -> None:
        """Require an explicit timezone-aware expiry supplied by composition config."""

        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")


@dataclass(frozen=True)
class CommitScenarioGovernanceCommand:
    """Consume one preview under a persistent idempotency scope."""

    request: ScenarioGovernanceRequest
    preview_id: str
    idempotency_key: str
    proposal_id: int | None = None

    def __post_init__(self) -> None:
        """Normalize confirmation identifiers."""

        preview_id = self.preview_id.strip()
        idempotency_key = self.idempotency_key.strip()
        if not preview_id or len(preview_id) > 160:
            raise ValueError("preview_id is required and must not exceed 160 characters")
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("idempotency_key is required and must not exceed 255 characters")
        if self.proposal_id is not None and (
            isinstance(self.proposal_id, bool) or self.proposal_id <= 0
        ):
            raise ValueError("proposal_id must be positive")
        object.__setattr__(self, "preview_id", preview_id)
        object.__setattr__(self, "idempotency_key", idempotency_key)


@dataclass(frozen=True)
class ReviewScenarioGovernanceProposalCommand:
    """Human staff approval or rejection of one persistent AgentProposal."""

    actor: ScenarioGovernanceActor
    proposal_id: int
    reason: str
    correlation_id: str

    def __post_init__(self) -> None:
        """Normalize review metadata before repository access."""

        if isinstance(self.proposal_id, bool) or self.proposal_id <= 0:
            raise ValueError("proposal_id must be positive")
        reason = self.reason.strip()
        correlation_id = self.correlation_id.strip()
        if not reason or len(reason) > 2_000:
            raise ValueError("reason must contain at most 2000 characters")
        if not correlation_id or len(correlation_id) > 120:
            raise ValueError("correlation_id must contain at most 120 characters")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "correlation_id", correlation_id)


@dataclass(frozen=True)
class AgentProposalSnapshot:
    """Infrastructure-neutral projection of the frozen AgentProposal contract."""

    proposal_id: int
    request_id: str
    proposal_type: str
    status: str
    approval_status: str
    created_by_user_id: int | None
    payload: Mapping[str, object]


class AgentProposalGatewayProtocol(Protocol):
    """Adapter for the existing AgentProposal table and lifecycle."""

    def create_submitted(
        self,
        *,
        created_by_user_id: int | None,
        payload: Mapping[str, object],
    ) -> AgentProposalSnapshot:
        """Create a persistent, approval-required high-risk proposal."""

    def get_for_update(self, proposal_id: int) -> AgentProposalSnapshot | None:
        """Lock and return one proposal inside the caller's transaction."""

    def approve(self, proposal_id: int, *, reason: str) -> AgentProposalSnapshot:
        """Persist approval after Risk Center has authorized the reviewer."""

    def reject(self, proposal_id: int, *, reason: str) -> AgentProposalSnapshot:
        """Persist rejection after Risk Center has authorized the reviewer."""

    def mark_executed(self, proposal_id: int) -> AgentProposalSnapshot:
        """Mark the approved proposal executed in the business transaction."""


class ScenarioGovernanceAuditWriterProtocol(Protocol):
    """Canonical audit adapter that must share the caller's database transaction."""

    def append(self, record: ScenarioGovernanceAuditRecord) -> str:
        """Append one immutable domain audit and return its identifier."""


class ScenarioGovernanceRepositoryProtocol(Protocol):
    """Transactional persistence port for the complete write-governance workflow."""

    def create_preview(
        self,
        command: PreviewScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Resolve authoritative base state and persist an actor-bound preview."""

    def propose_revision(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Atomically append a revision, AgentProposal, idempotency result, and audit."""

    def propose_action(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Create an approval-required AgentProposal for activate/rollback/retire."""

    def approve_proposal(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Persist a human staff approval with separation of duties."""

    def reject_proposal(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Persist a human staff rejection with separation of duties."""

    def activate(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Execute an approved activation under locks and optimistic checks."""

    def rollback(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Copy a prior set revision to a new version and atomically activate it."""

    def retire(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Retire a definition without mutating immutable revision history."""


class PreviewScenarioGovernanceUseCase:
    """Persist exact preview evidence without changing production state."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: PreviewScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Return a persistent confirmation requirement."""

        return self._repository.create_preview(command)


class ProposeScenarioRevisionUseCase:
    """Append an immutable proposed revision and persistent AgentProposal."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Create a proposal without changing active production state."""

        _require_operation(command, ScenarioGovernanceOperation.PROPOSE)
        return self._repository.propose_revision(command)


class ProposeScenarioActionUseCase:
    """Create an AgentProposal for a later human activation, rollback, or retirement."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Persist the proposal and consume only the creator's preview."""

        if command.request.operation is ScenarioGovernanceOperation.PROPOSE:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "propose revision must use ProposeScenarioRevisionUseCase",
            )
        return self._repository.propose_action(command)


class ApproveScenarioGovernanceProposalUseCase:
    """Enforce human-staff, non-self approval before persistence."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Approve one proposal through the transactional repository."""

        require_human_staff(command.actor, action="scenario proposal approval")
        return self._repository.approve_proposal(command)


class RejectScenarioGovernanceProposalUseCase:
    """Enforce human-staff, non-self rejection before persistence."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Reject one proposal through the transactional repository."""

        require_human_staff(command.actor, action="scenario proposal rejection")
        return self._repository.reject_proposal(command)


class ActivateScenarioGovernanceUseCase:
    """Execute a human-approved active-pointer change."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Require a human staff actor and delegate the atomic activation."""

        _require_operation(command, ScenarioGovernanceOperation.ACTIVATE)
        require_human_staff(command.request.actor, action="scenario activation")
        return self._repository.activate(command)


class RollbackScenarioGovernanceUseCase:
    """Copy and activate an earlier scenario-set revision."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Require a human staff actor and delegate the atomic rollback."""

        _require_operation(command, ScenarioGovernanceOperation.ROLLBACK)
        require_human_staff(command.request.actor, action="scenario rollback")
        return self._repository.rollback(command)


class RetireScenarioGovernanceUseCase:
    """Retire a scenario identity while preserving immutable revisions."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Require a human staff actor and delegate the atomic retirement."""

        _require_operation(command, ScenarioGovernanceOperation.RETIRE)
        require_human_staff(command.request.actor, action="scenario retirement")
        return self._repository.retire(command)


class ScenarioGovernanceFacade:
    """Application-only facade for Interface, SDK-backed APIs, and composition roots."""

    def __init__(self, repository: ScenarioGovernanceRepositoryProtocol) -> None:
        self._repository = repository

    def preview(
        self,
        command: PreviewScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Persist one actor-bound preview."""

        return PreviewScenarioGovernanceUseCase(self._repository).execute(command)

    def propose_revision(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Append an immutable revision proposal."""

        return ProposeScenarioRevisionUseCase(self._repository).execute(command)

    def propose_action(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Create an action proposal awaiting another human's approval."""

        return ProposeScenarioActionUseCase(self._repository).execute(command)

    def approve(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Approve one proposal with separation of duties."""

        return ApproveScenarioGovernanceProposalUseCase(self._repository).execute(command)

    def reject(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Reject one proposal with separation of duties."""

        return RejectScenarioGovernanceProposalUseCase(self._repository).execute(command)

    def activate(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Activate an approved set revision."""

        return ActivateScenarioGovernanceUseCase(self._repository).execute(command)

    def rollback(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Create and activate a rollback copy."""

        return RollbackScenarioGovernanceUseCase(self._repository).execute(command)

    def retire(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Retire a scenario definition."""

        return RetireScenarioGovernanceUseCase(self._repository).execute(command)


_repository: ScenarioGovernanceRepositoryProtocol | None = None


def configure_scenario_governance_repository(
    repository: ScenarioGovernanceRepositoryProtocol,
) -> None:
    """Configure the composition-root-owned persistence adapter."""

    global _repository
    _repository = repository


def get_scenario_governance_facade() -> ScenarioGovernanceFacade:
    """Return the configured Application facade without importing Infrastructure."""

    if _repository is None:
        raise RuntimeError("scenario governance repository is not configured")
    return ScenarioGovernanceFacade(_repository)


def _require_operation(
    command: CommitScenarioGovernanceCommand,
    operation: ScenarioGovernanceOperation,
) -> None:
    if command.request.operation is not operation:
        raise ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.INVALID_REQUEST,
            f"expected {operation.value} governance operation",
        )


def _revision_command_payload(
    command: CreateScenarioRevisionCommandDTO,
) -> dict[str, object]:
    return {
        "scenario_key": command.scenario_key,
        "scenario_type": command.scenario_type.value,
        "parameters": scenario_parameters_to_dict(command.parameters),
        "assumptions": list(command.assumptions),
        "source_type": command.source_type.value,
        "created_by": command.created_by,
        "change_reason": command.change_reason,
        "status": command.status.value,
        "based_on_version": command.based_on_version,
        "source_evidence": list(command.source_evidence),
    }


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ActivateScenarioGovernanceUseCase",
    "AgentProposalGatewayProtocol",
    "AgentProposalSnapshot",
    "ApproveScenarioGovernanceProposalUseCase",
    "CommitScenarioGovernanceCommand",
    "PreviewScenarioGovernanceCommand",
    "PreviewScenarioGovernanceUseCase",
    "ProposeScenarioActionUseCase",
    "ProposeScenarioRevisionUseCase",
    "RejectScenarioGovernanceProposalUseCase",
    "RetireScenarioGovernanceUseCase",
    "ReviewScenarioGovernanceProposalCommand",
    "RollbackScenarioGovernanceUseCase",
    "ScenarioGovernanceAuditWriterProtocol",
    "ScenarioGovernanceFacade",
    "ScenarioGovernanceRepositoryProtocol",
    "ScenarioGovernanceRequest",
    "ScenarioGovernanceTarget",
    "configure_scenario_governance_repository",
    "get_scenario_governance_facade",
]
