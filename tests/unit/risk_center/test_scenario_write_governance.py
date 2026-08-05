"""Pure and Application-level contracts for scenario write governance."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.risk_center.application.scenario_dtos import (
    CreateScenarioRevisionCommandDTO,
)
from apps.risk_center.application.scenario_governance import (
    ActivateScenarioGovernanceUseCase,
    ApproveScenarioGovernanceProposalUseCase,
    CommitScenarioGovernanceCommand,
    PreviewScenarioGovernanceCommand,
    PreviewScenarioGovernanceUseCase,
    ReviewScenarioGovernanceProposalCommand,
    ScenarioGovernanceRequest,
    ScenarioGovernanceTarget,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActor,
    ScenarioGovernanceActorKind,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
    ScenarioGovernanceOutcome,
    ScenarioGovernanceStatus,
    scenario_governance_fingerprint,
    stable_governance_hash,
)
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ScenarioRevisionStatus,
    ScenarioSourceType,
    ScenarioType,
)


def _actor(
    actor_id: str = "user:7",
    *,
    kind: ScenarioGovernanceActorKind = ScenarioGovernanceActorKind.HUMAN,
    is_staff: bool = True,
    user_id: int | None = 7,
) -> ScenarioGovernanceActor:
    return ScenarioGovernanceActor(
        actor_id=actor_id,
        kind=kind,
        is_staff=is_staff,
        user_id=user_id,
    )


def _revision_command(*, based_on_version: int | None = None) -> CreateScenarioRevisionCommandDTO:
    return CreateScenarioRevisionCommandDTO(
        scenario_key="historical.test.tail",
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=HistoricalWindowParameters(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 2, 1),
            source="published.test",
            event_description="test tail event",
        ),
        assumptions=("Published historical observations are complete.",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="transport-ignored",
        change_reason="refresh historical evidence",
        status=ScenarioRevisionStatus.DRAFT,
        based_on_version=based_on_version,
        source_evidence=({"publication_id": "evidence-1"},),
    )


def _request(
    *,
    actor: ScenarioGovernanceActor | None = None,
    operation: ScenarioGovernanceOperation = ScenarioGovernanceOperation.PROPOSE,
) -> ScenarioGovernanceRequest:
    if operation is ScenarioGovernanceOperation.PROPOSE:
        target = ScenarioGovernanceTarget(scenario_key="historical.test.tail")
        revision = _revision_command()
    else:
        target = ScenarioGovernanceTarget(
            scenario_set_revision_id="6d97e003-22ac-4fba-93d7-c79af1e5940e",
            environment="shadow",
            purpose="portfolio_stress",
        )
        revision = None
    return ScenarioGovernanceRequest(
        actor=actor or _actor(),
        capability_key=f"risk_center.stress_scenario.{operation.value}_revision",
        operation=operation,
        payload={"scenario_key": "historical.test.tail", "name": "Tail event"},
        target=target,
        change_reason="reviewed evidence change",
        correlation_id="correlation-1",
        expected_base_version=None,
        expected_base_hash=None,
        revision_command=revision,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_preview(
        self, command: PreviewScenarioGovernanceCommand
    ) -> ScenarioGovernanceOutcome:
        self.calls.append("preview")
        return ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.CONFIRMATION_REQUIRED,
            operation=command.request.operation,
            correlation_id=command.request.correlation_id,
            preview_id="preview-1",
        )

    def activate(self, command: CommitScenarioGovernanceCommand) -> ScenarioGovernanceOutcome:
        self.calls.append("activate")
        return ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.ACTIVATED,
            operation=command.request.operation,
            correlation_id=command.request.correlation_id,
        )

    def approve_proposal(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        self.calls.append("approve")
        return ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.APPROVED,
            operation=ScenarioGovernanceOperation.ACTIVATE,
            correlation_id=command.correlation_id,
            proposal_id=command.proposal_id,
        )


def test_fingerprint_binds_exact_payload_capability_and_base() -> None:
    base_hash = stable_governance_hash({"version": 1})
    original = scenario_governance_fingerprint(
        operation=ScenarioGovernanceOperation.PROPOSE,
        capability_key="risk_center.stress_scenario.propose_revision",
        payload={"scenario_key": "tail", "probability": "0.25"},
        base_version=1,
        base_hash=base_hash,
    )

    assert original == scenario_governance_fingerprint(
        operation=ScenarioGovernanceOperation.PROPOSE,
        capability_key="risk_center.stress_scenario.propose_revision",
        payload={"probability": "0.25", "scenario_key": "tail"},
        base_version=1,
        base_hash=base_hash,
    )
    assert original != scenario_governance_fingerprint(
        operation=ScenarioGovernanceOperation.PROPOSE,
        capability_key="risk_center.stress_scenario.propose_revision",
        payload={"scenario_key": "tail", "probability": "0.30"},
        base_version=1,
        base_hash=base_hash,
    )
    assert original != scenario_governance_fingerprint(
        operation=ScenarioGovernanceOperation.PROPOSE,
        capability_key="risk_center.stress_scenario.propose_revision",
        payload={"scenario_key": "tail", "probability": "0.25"},
        base_version=2,
        base_hash=base_hash,
    )


def test_error_envelope_exposes_stable_blocked_contract() -> None:
    error = ScenarioGovernanceError(
        ScenarioGovernanceErrorCode.PREVIEW_EXPIRED,
        "preview expired",
        conflict=True,
    )

    assert error.as_dict(correlation_id="corr") == {
        "status": "rejected",
        "error": {
            "code": "scenario_governance_preview_expired",
            "message": "preview expired",
            "conflict": True,
        },
        "blocked_reason": "scenario_governance_preview_expired",
        "must_not_use_for_decision": True,
        "correlation_id": "corr",
    }


def test_preview_use_case_returns_repository_result() -> None:
    repository = _Repository()
    command = PreviewScenarioGovernanceCommand(
        request=_request(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    result = PreviewScenarioGovernanceUseCase(repository).execute(command)  # type: ignore[arg-type]

    assert result.status is ScenarioGovernanceStatus.CONFIRMATION_REQUIRED
    assert repository.calls == ["preview"]


def test_ai_and_service_principals_cannot_approve_or_activate() -> None:
    repository = _Repository()
    ai_actor = _actor(
        "service:scenario-agent",
        kind=ScenarioGovernanceActorKind.AI,
        is_staff=True,
        user_id=None,
    )
    review = ReviewScenarioGovernanceProposalCommand(
        actor=ai_actor,
        proposal_id=9,
        reason="AI cannot approve",
        correlation_id="corr-ai-review",
    )
    activate_request = _request(
        actor=ai_actor,
        operation=ScenarioGovernanceOperation.ACTIVATE,
    )
    activate = CommitScenarioGovernanceCommand(
        request=activate_request,
        preview_id="preview-ai",
        idempotency_key="activate-ai",
        proposal_id=9,
    )

    with pytest.raises(ScenarioGovernanceError) as approval_error:
        ApproveScenarioGovernanceProposalUseCase(repository).execute(review)  # type: ignore[arg-type]
    with pytest.raises(ScenarioGovernanceError) as activation_error:
        ActivateScenarioGovernanceUseCase(repository).execute(activate)  # type: ignore[arg-type]

    assert approval_error.value.code is ScenarioGovernanceErrorCode.PERMISSION_DENIED
    assert activation_error.value.code is ScenarioGovernanceErrorCode.PERMISSION_DENIED
    assert repository.calls == []


def test_human_staff_can_reach_approval_and_activation_repository_ports() -> None:
    repository = _Repository()
    review = ReviewScenarioGovernanceProposalCommand(
        actor=_actor(),
        proposal_id=9,
        reason="approved after review",
        correlation_id="corr-review",
    )
    activate = CommitScenarioGovernanceCommand(
        request=_request(operation=ScenarioGovernanceOperation.ACTIVATE),
        preview_id="preview-human",
        idempotency_key="activate-human",
        proposal_id=9,
    )

    ApproveScenarioGovernanceProposalUseCase(repository).execute(review)  # type: ignore[arg-type]
    ActivateScenarioGovernanceUseCase(repository).execute(activate)  # type: ignore[arg-type]

    assert repository.calls == ["approve", "activate"]
