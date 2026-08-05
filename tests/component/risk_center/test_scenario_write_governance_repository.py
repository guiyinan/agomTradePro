"""Database contracts for persistent scenario write governance."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.agent_runtime.infrastructure.models import AgentProposalModel
from apps.risk_center.application.scenario_dtos import (
    CreateScenarioRevisionCommandDTO,
)
from apps.risk_center.application.scenario_governance import (
    CommitScenarioGovernanceCommand,
    PreviewScenarioGovernanceCommand,
    ReviewScenarioGovernanceProposalCommand,
    ScenarioGovernanceRequest,
    ScenarioGovernanceTarget,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActor,
    ScenarioGovernanceActorKind,
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
    ScenarioGovernanceStatus,
)
from apps.risk_center.domain.scenarios import (
    HistoricalWindowParameters,
    ProbabilitySource,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    scenario_parameters_to_dict,
)
from apps.risk_center.infrastructure.models import (
    ScenarioActivationModel,
    ScenarioSetMemberModel,
    ScenarioSetModel,
    ScenarioSetRevisionModel,
    StressScenarioDefinitionModel,
    StressScenarioRevisionModel,
)
from apps.risk_center.infrastructure.scenario_governance_models import (
    ScenarioGovernanceAuditModel,
    ScenarioGovernanceIdempotencyModel,
    ScenarioGovernancePreviewModel,
    ScenarioGovernanceProposalLinkModel,
)
from apps.risk_center.infrastructure.scenario_governance_repository import (
    DjangoScenarioGovernanceRepository,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def actors() -> tuple[ScenarioGovernanceActor, ScenarioGovernanceActor]:
    user_model = get_user_model()
    creator = user_model.objects.create_user(username="scenario-ai-principal")
    approver = user_model.objects.create_user(
        username="scenario-human-approver",
        is_staff=True,
    )
    return (
        ScenarioGovernanceActor(
            actor_id="service:scenario-agent",
            kind=ScenarioGovernanceActorKind.AI,
            is_staff=False,
            user_id=int(creator.pk),
            roles=("ai_service",),
        ),
        ScenarioGovernanceActor(
            actor_id=f"user:{approver.pk}",
            kind=ScenarioGovernanceActorKind.HUMAN,
            is_staff=True,
            user_id=int(approver.pk),
            roles=("staff",),
        ),
    )


def _parameters(*, description: str = "published tail event") -> HistoricalWindowParameters:
    return HistoricalWindowParameters(
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 1),
        source="published.test",
        event_description=description,
    )


def _revision_command(
    scenario_key: str,
    *,
    based_on_version: int | None,
    description: str = "published tail event",
) -> CreateScenarioRevisionCommandDTO:
    return CreateScenarioRevisionCommandDTO(
        scenario_key=scenario_key,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=_parameters(description=description),
        assumptions=("Published historical observations are complete.",),
        source_type=ScenarioSourceType.AI_MCP,
        created_by="transport-ignored",
        change_reason="refresh historical evidence",
        status=ScenarioRevisionStatus.DRAFT,
        based_on_version=based_on_version,
        source_evidence=({"publication_id": "evidence-1"},),
    )


def _propose_request(
    actor: ScenarioGovernanceActor,
    *,
    scenario_key: str = "historical.test.tail",
    based_on_version: int | None = None,
    base_hash: str | None = None,
    description: str = "published tail event",
) -> ScenarioGovernanceRequest:
    return ScenarioGovernanceRequest(
        actor=actor,
        capability_key="risk_center.stress_scenario.propose_revision",
        operation=ScenarioGovernanceOperation.PROPOSE,
        payload={
            "scenario_key": scenario_key,
            "name": "Test tail event",
            "category": "historical_stress",
            "owner": "risk_center",
            "description": "Component-test governed scenario.",
        },
        target=ScenarioGovernanceTarget(scenario_key=scenario_key),
        change_reason="refresh historical evidence",
        correlation_id="correlation-propose",
        expected_base_version=based_on_version,
        expected_base_hash=base_hash,
        revision_command=_revision_command(
            scenario_key,
            based_on_version=based_on_version,
            description=description,
        ),
    )


def _action_request(
    actor: ScenarioGovernanceActor,
    *,
    operation: ScenarioGovernanceOperation,
    scenario_key: str | None,
    scenario_set_revision_id: str | None,
    target_version: int | None,
    base_version: int,
    base_hash: str,
) -> ScenarioGovernanceRequest:
    return ScenarioGovernanceRequest(
        actor=actor,
        capability_key=f"risk_center.stress_scenario.{operation.value}_revision",
        operation=operation,
        payload={
            "scenario_key": scenario_key,
            "scenario_set_revision_id": scenario_set_revision_id,
            "target_version": target_version,
            "environment": "shadow",
            "purpose": "portfolio_stress",
        },
        target=ScenarioGovernanceTarget(
            scenario_key=scenario_key,
            scenario_set_revision_id=scenario_set_revision_id,
            environment=(None if operation is ScenarioGovernanceOperation.RETIRE else "shadow"),
            purpose=(
                None if operation is ScenarioGovernanceOperation.RETIRE else "portfolio_stress"
            ),
            target_version=target_version,
        ),
        change_reason=f"reviewed {operation.value} operation",
        correlation_id=f"correlation-{operation.value}",
        expected_base_version=base_version,
        expected_base_hash=base_hash,
    )


def _preview(
    repository: DjangoScenarioGovernanceRepository,
    request: ScenarioGovernanceRequest,
) -> str:
    result = repository.create_preview(
        PreviewScenarioGovernanceCommand(
            request=request,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    assert result.status is ScenarioGovernanceStatus.CONFIRMATION_REQUIRED
    assert result.preview_id is not None
    return result.preview_id


def _persist_revision(
    scenario_key: str,
    *,
    version: int,
) -> StressScenarioRevisionModel:
    definition, _ = StressScenarioDefinitionModel._default_manager.get_or_create(
        scenario_key=scenario_key,
        defaults={
            "name": scenario_key,
            "category": "test",
            "owner": "risk_center",
            "status": "active",
        },
    )
    revision = ScenarioRevision(
        revision_id=str(uuid4()),
        scenario_key=scenario_key,
        version=version,
        based_on_version=(version - 1 if version > 1 else None),
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.HISTORICAL_WINDOW,
        parameters=_parameters(description=f"event-v{version}"),
        assumptions=("test assumption",),
        source_type=ScenarioSourceType.HUMAN,
        created_by="test:seed",
        change_reason="test fixture",
        created_at=timezone.now(),
    )
    model = StressScenarioRevisionModel(
        revision_id=revision.revision_id,
        definition=definition,
        version=revision.version,
        based_on_version=revision.based_on_version,
        status=revision.status.value,
        scenario_type=revision.scenario_type.value,
        parameters=scenario_parameters_to_dict(revision.parameters),
        assumptions=list(revision.assumptions),
        source_evidence=[],
        source_type=revision.source_type.value,
        content_hash=revision.content_hash,
        created_by=revision.created_by,
        change_reason=revision.change_reason,
        created_at=revision.created_at,
    )
    model.save(force_insert=True)
    return model


def _persist_set_revision(
    scenario_set: ScenarioSetModel,
    scenario_revision: StressScenarioRevisionModel,
    *,
    version: int,
    axis: str,
) -> ScenarioSetRevisionModel:
    domain = ScenarioSetRevision(
        revision_id=str(uuid4()),
        set_key=scenario_set.set_key,
        version=version,
        status=ScenarioRevisionStatus.APPROVED,
        members=(
            ScenarioSetMember(
                scenario_revision_id=str(scenario_revision.revision_id),
                probability=Decimal("1"),
                probability_source=ProbabilitySource.SUBJECTIVE,
                sort_order=0,
            ),
        ),
        driver_axes=(axis,),
        created_by="test:seed",
        change_reason="test fixture",
        created_at=timezone.now(),
    )
    model = ScenarioSetRevisionModel(
        revision_id=domain.revision_id,
        scenario_set=scenario_set,
        version=domain.version,
        status=domain.status.value,
        driver_axes=list(domain.driver_axes),
        content_hash=domain.content_hash,
        created_by=domain.created_by,
        change_reason=domain.change_reason,
        created_at=domain.created_at,
    )
    model.save(force_insert=True)
    member = ScenarioSetMemberModel(
        scenario_set_revision=model,
        scenario_revision=scenario_revision,
        probability=Decimal("1"),
        probability_source="subjective",
        sort_order=0,
        created_at=timezone.now(),
    )
    member.save(force_insert=True)
    return model


@pytest.fixture
def active_set() -> tuple[ScenarioSetRevisionModel, ScenarioSetRevisionModel]:
    scenario_revision = _persist_revision("historical.test.member", version=1)
    scenario_set = ScenarioSetModel._default_manager.create(
        set_key="portfolio.test.set",
        name="Portfolio test set",
        purpose="portfolio_stress",
        owner="risk_center",
        status="active",
    )
    previous = _persist_set_revision(
        scenario_set,
        scenario_revision,
        version=1,
        axis="previous",
    )
    current = _persist_set_revision(
        scenario_set,
        scenario_revision,
        version=2,
        axis="current",
    )
    ScenarioActivationModel._default_manager.create(
        environment="shadow",
        purpose="portfolio_stress",
        scenario_set_revision=current,
        activated_by="test:seed",
        reason="test fixture",
        activated_at=timezone.now(),
        is_active=True,
    )
    return previous, current


def _approved_action(
    repository: DjangoScenarioGovernanceRepository,
    *,
    creator_request: ScenarioGovernanceRequest,
    human_request: ScenarioGovernanceRequest,
    approver: ScenarioGovernanceActor,
) -> tuple[int, str]:
    creator_preview = _preview(repository, creator_request)
    target_key = (
        creator_request.target.scenario_key
        or creator_request.target.scenario_set_revision_id
        or str(creator_request.target.target_version)
    )
    proposed = repository.propose_action(
        CommitScenarioGovernanceCommand(
            request=creator_request,
            preview_id=creator_preview,
            idempotency_key=f"proposal-{creator_request.operation.value}-{target_key}",
        )
    )
    assert proposed.proposal_id is not None
    repository.approve_proposal(
        ReviewScenarioGovernanceProposalCommand(
            actor=approver,
            proposal_id=proposed.proposal_id,
            reason="approved after independent review",
            correlation_id=f"approval-{creator_request.operation.value}",
        )
    )
    return proposed.proposal_id, _preview(repository, human_request)


def test_propose_persists_revision_agent_proposal_and_idempotent_result(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
) -> None:
    creator, other_actor = actors
    repository = DjangoScenarioGovernanceRepository()
    request = _propose_request(creator)
    preview_id = _preview(repository, request)
    command = CommitScenarioGovernanceCommand(
        request=request,
        preview_id=preview_id,
        idempotency_key="propose-tail-v1",
    )

    created = repository.propose_revision(command)
    replayed = repository.propose_revision(command)

    assert created.status is ScenarioGovernanceStatus.CREATED
    assert created.revision_id is not None
    assert created.proposal_id is not None
    assert replayed.as_dict() | {"replayed": False} == created.as_dict()
    assert replayed.replayed is True
    assert (
        StressScenarioRevisionModel._default_manager.filter(
            revision_id=created.revision_id,
            status="proposed",
            source_type="ai_mcp",
        ).count()
        == 1
    )
    assert (
        AgentProposalModel._default_manager.filter(
            pk=created.proposal_id,
            status="submitted",
            approval_status="pending",
        ).count()
        == 1
    )
    assert (
        ScenarioGovernanceProposalLinkModel._default_manager.filter(
            proposal_id=created.proposal_id,
            request_fingerprint=ScenarioGovernancePreviewModel._default_manager.get(
                preview_id=preview_id
            ).request_fingerprint,
        ).count()
        == 1
    )
    assert ScenarioGovernanceIdempotencyModel._default_manager.count() == 1
    assert (
        ScenarioGovernanceAuditModel._default_manager.filter(operation="proposal_created").count()
        == 1
    )

    with pytest.raises(ScenarioGovernanceError) as cross_actor:
        repository.propose_revision(
            CommitScenarioGovernanceCommand(
                request=_propose_request(other_actor),
                preview_id=preview_id,
                idempotency_key="other-actor",
            )
        )
    assert cross_actor.value.code is ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH

    changed_request = _propose_request(
        creator,
        based_on_version=created.version,
        base_hash=created.content_hash,
        description="different exact payload",
    )
    changed_preview = _preview(repository, changed_request)
    with pytest.raises(ScenarioGovernanceError) as conflict:
        repository.propose_revision(
            CommitScenarioGovernanceCommand(
                request=changed_request,
                preview_id=changed_preview,
                idempotency_key="propose-tail-v1",
            )
        )
    assert conflict.value.code is ScenarioGovernanceErrorCode.IDEMPOTENCY_CONFLICT
    assert (
        StressScenarioRevisionModel._default_manager.filter(
            definition__scenario_key="historical.test.tail"
        ).count()
        == 1
    )


def test_self_and_nonhuman_approval_are_rejected(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
) -> None:
    creator, approver = actors
    repository = DjangoScenarioGovernanceRepository()
    request = _propose_request(creator)
    preview_id = _preview(repository, request)
    proposed = repository.propose_revision(
        CommitScenarioGovernanceCommand(
            request=request,
            preview_id=preview_id,
            idempotency_key="proposal-approval-gates",
        )
    )
    assert proposed.proposal_id is not None

    with pytest.raises(ScenarioGovernanceError) as ai_error:
        repository.approve_proposal(
            ReviewScenarioGovernanceProposalCommand(
                actor=creator,
                proposal_id=proposed.proposal_id,
                reason="AI self approval",
                correlation_id="ai-approval",
            )
        )
    assert ai_error.value.code is ScenarioGovernanceErrorCode.PERMISSION_DENIED

    human_creator = ScenarioGovernanceActor(
        actor_id=approver.actor_id,
        kind=ScenarioGovernanceActorKind.HUMAN,
        is_staff=True,
        user_id=approver.user_id,
    )
    human_request = _propose_request(
        human_creator,
        scenario_key="historical.test.human-created",
    )
    human_preview = _preview(repository, human_request)
    human_proposal = repository.propose_revision(
        CommitScenarioGovernanceCommand(
            request=human_request,
            preview_id=human_preview,
            idempotency_key="human-created-proposal",
        )
    )
    assert human_proposal.proposal_id is not None
    with pytest.raises(ScenarioGovernanceError) as self_error:
        repository.approve_proposal(
            ReviewScenarioGovernanceProposalCommand(
                actor=human_creator,
                proposal_id=human_proposal.proposal_id,
                reason="self approval",
                correlation_id="self-approval",
            )
        )
    assert self_error.value.code is ScenarioGovernanceErrorCode.SELF_APPROVAL_FORBIDDEN


def test_approved_human_activation_is_atomic_and_idempotent(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
    active_set: tuple[ScenarioSetRevisionModel, ScenarioSetRevisionModel],
) -> None:
    creator, approver = actors
    previous, current = active_set
    repository = DjangoScenarioGovernanceRepository()
    creator_request = _action_request(
        creator,
        operation=ScenarioGovernanceOperation.ACTIVATE,
        scenario_key=None,
        scenario_set_revision_id=str(previous.revision_id),
        target_version=None,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    human_request = _action_request(
        approver,
        operation=ScenarioGovernanceOperation.ACTIVATE,
        scenario_key=None,
        scenario_set_revision_id=str(previous.revision_id),
        target_version=None,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    proposal_id, preview_id = _approved_action(
        repository,
        creator_request=creator_request,
        human_request=human_request,
        approver=approver,
    )
    command = CommitScenarioGovernanceCommand(
        request=human_request,
        preview_id=preview_id,
        idempotency_key="activate-approved-v1",
        proposal_id=proposal_id,
    )

    activated = repository.activate(command)
    replayed = repository.activate(command)

    assert activated.status is ScenarioGovernanceStatus.ACTIVATED
    assert replayed.replayed is True
    active = ScenarioActivationModel._default_manager.get(
        environment="shadow",
        purpose="portfolio_stress",
        is_active=True,
    )
    assert active.scenario_set_revision_id == previous.revision_id
    assert (
        ScenarioGovernanceProposalLinkModel._default_manager.get(proposal_id=proposal_id).status
        == "executed"
    )
    assert AgentProposalModel._default_manager.get(pk=proposal_id).status == "executed"


class _FailingAuditWriter:
    def append(self, record: ScenarioGovernanceAuditRecord) -> str:
        raise RuntimeError(f"audit unavailable: {record.operation}")


def test_canonical_audit_failure_rolls_back_activation_and_confirmation(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
    active_set: tuple[ScenarioSetRevisionModel, ScenarioSetRevisionModel],
) -> None:
    creator, approver = actors
    previous, current = active_set
    working_repository = DjangoScenarioGovernanceRepository()
    creator_request = _action_request(
        creator,
        operation=ScenarioGovernanceOperation.ACTIVATE,
        scenario_key=None,
        scenario_set_revision_id=str(previous.revision_id),
        target_version=None,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    human_request = _action_request(
        approver,
        operation=ScenarioGovernanceOperation.ACTIVATE,
        scenario_key=None,
        scenario_set_revision_id=str(previous.revision_id),
        target_version=None,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    proposal_id, preview_id = _approved_action(
        working_repository,
        creator_request=creator_request,
        human_request=human_request,
        approver=approver,
    )
    failing_repository = DjangoScenarioGovernanceRepository(audit_writer=_FailingAuditWriter())

    with pytest.raises(ScenarioGovernanceError) as audit_error:
        failing_repository.activate(
            CommitScenarioGovernanceCommand(
                request=human_request,
                preview_id=preview_id,
                idempotency_key="activation-audit-failure",
                proposal_id=proposal_id,
            )
        )

    assert audit_error.value.code is ScenarioGovernanceErrorCode.AUDIT_WRITE_FAILED
    active = ScenarioActivationModel._default_manager.get(
        environment="shadow",
        purpose="portfolio_stress",
        is_active=True,
    )
    assert active.scenario_set_revision_id == current.revision_id
    assert (
        ScenarioGovernancePreviewModel._default_manager.get(preview_id=preview_id).consumed_at
        is None
    )
    assert not ScenarioGovernanceIdempotencyModel._default_manager.filter(
        idempotency_key="activation-audit-failure"
    ).exists()
    assert (
        ScenarioGovernanceProposalLinkModel._default_manager.get(proposal_id=proposal_id).status
        == "approved"
    )
    assert AgentProposalModel._default_manager.get(pk=proposal_id).status == "approved"


def test_rollback_copies_prior_revision_to_new_version_and_activates_it(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
    active_set: tuple[ScenarioSetRevisionModel, ScenarioSetRevisionModel],
) -> None:
    creator, approver = actors
    previous, current = active_set
    repository = DjangoScenarioGovernanceRepository()
    creator_request = _action_request(
        creator,
        operation=ScenarioGovernanceOperation.ROLLBACK,
        scenario_key=previous.scenario_set.set_key,
        scenario_set_revision_id=None,
        target_version=previous.version,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    human_request = _action_request(
        approver,
        operation=ScenarioGovernanceOperation.ROLLBACK,
        scenario_key=previous.scenario_set.set_key,
        scenario_set_revision_id=None,
        target_version=previous.version,
        base_version=current.version,
        base_hash=current.content_hash,
    )
    proposal_id, preview_id = _approved_action(
        repository,
        creator_request=creator_request,
        human_request=human_request,
        approver=approver,
    )

    result = repository.rollback(
        CommitScenarioGovernanceCommand(
            request=human_request,
            preview_id=preview_id,
            idempotency_key="rollback-to-v1",
            proposal_id=proposal_id,
        )
    )

    assert result.status is ScenarioGovernanceStatus.ROLLED_BACK
    assert result.version == 3
    assert result.content_hash == previous.content_hash
    assert (
        ScenarioSetRevisionModel._default_manager.filter(scenario_set=previous.scenario_set).count()
        == 3
    )
    active = ScenarioActivationModel._default_manager.get(
        environment="shadow",
        purpose="portfolio_stress",
        is_active=True,
    )
    assert active.scenario_set_revision.version == 3
    assert active.scenario_set_revision.content_hash == previous.content_hash


def test_retire_preserves_revision_history_and_blocks_active_references(
    actors: tuple[ScenarioGovernanceActor, ScenarioGovernanceActor],
    active_set: tuple[ScenarioSetRevisionModel, ScenarioSetRevisionModel],
) -> None:
    creator, approver = actors
    _, current = active_set
    referenced = current.members.first().scenario_revision
    repository = DjangoScenarioGovernanceRepository()

    referenced_creator = _action_request(
        creator,
        operation=ScenarioGovernanceOperation.RETIRE,
        scenario_key=referenced.definition.scenario_key,
        scenario_set_revision_id=None,
        target_version=None,
        base_version=referenced.version,
        base_hash=referenced.content_hash,
    )
    referenced_human = _action_request(
        approver,
        operation=ScenarioGovernanceOperation.RETIRE,
        scenario_key=referenced.definition.scenario_key,
        scenario_set_revision_id=None,
        target_version=None,
        base_version=referenced.version,
        base_hash=referenced.content_hash,
    )
    referenced_proposal, referenced_preview = _approved_action(
        repository,
        creator_request=referenced_creator,
        human_request=referenced_human,
        approver=approver,
    )
    with pytest.raises(ScenarioGovernanceError) as in_use:
        repository.retire(
            CommitScenarioGovernanceCommand(
                request=referenced_human,
                preview_id=referenced_preview,
                idempotency_key="retire-active-member",
                proposal_id=referenced_proposal,
            )
        )
    assert in_use.value.code is ScenarioGovernanceErrorCode.TARGET_IN_USE

    standalone = _persist_revision("historical.test.standalone", version=1)
    standalone_creator = _action_request(
        creator,
        operation=ScenarioGovernanceOperation.RETIRE,
        scenario_key=standalone.definition.scenario_key,
        scenario_set_revision_id=None,
        target_version=None,
        base_version=standalone.version,
        base_hash=standalone.content_hash,
    )
    standalone_human = _action_request(
        approver,
        operation=ScenarioGovernanceOperation.RETIRE,
        scenario_key=standalone.definition.scenario_key,
        scenario_set_revision_id=None,
        target_version=None,
        base_version=standalone.version,
        base_hash=standalone.content_hash,
    )
    proposal_id, preview_id = _approved_action(
        repository,
        creator_request=standalone_creator,
        human_request=standalone_human,
        approver=approver,
    )
    revision_count = StressScenarioRevisionModel._default_manager.filter(
        definition=standalone.definition
    ).count()

    retired = repository.retire(
        CommitScenarioGovernanceCommand(
            request=standalone_human,
            preview_id=preview_id,
            idempotency_key="retire-standalone",
            proposal_id=proposal_id,
        )
    )

    standalone.definition.refresh_from_db()
    assert retired.status is ScenarioGovernanceStatus.RETIRED
    assert standalone.definition.status == "retired"
    assert (
        StressScenarioRevisionModel._default_manager.filter(
            definition=standalone.definition
        ).count()
        == revision_count
    )
