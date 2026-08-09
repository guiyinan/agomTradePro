"""Transactional Django adapter for stress-scenario write governance."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.risk_center.application.scenario_governance import (
    AgentProposalGatewayProtocol,
    AgentProposalSnapshot,
    CommitScenarioGovernanceCommand,
    PreviewScenarioGovernanceCommand,
    ReviewScenarioGovernanceProposalCommand,
    ScenarioGovernanceAuditWriterProtocol,
    ScenarioGovernanceRequest,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceActorKind,
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
    ScenarioGovernanceOutcome,
    ScenarioGovernanceStatus,
    require_human_staff,
    stable_governance_hash,
)
from apps.risk_center.domain.scenarios import (
    ProbabilitySource,
    ScenarioDefinitionStatus,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioSetMember,
    ScenarioSetRevision,
    ScenarioSourceType,
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
    ScenarioGovernancePreviewModel,
)
from apps.risk_center.infrastructure.scenario_governance_repository_operations import (
    ScenarioGovernanceRepositoryOperationsMixin,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    ResolvedScenarioGovernanceState as _ResolvedState,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    ScenarioGovernanceCommitContext as _CommitContext,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    ScenarioGovernanceCommitProduct as _CommitProduct,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    json_array as _json_array,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    json_object as _json_object,
)


def _agent_proposal_model() -> Any:
    """Resolve the frozen proposal model without a static app dependency.

    Risk Center owns the scenario-governance transaction, while Agent Runtime
    owns the proposal table.  Looking up the model through Django's registry
    keeps the infrastructure adapter behind its injected gateway contract and
    removes the static ``risk_center -> agent_runtime`` app edge that otherwise
    creates a module cycle through Agent Runtime context snapshots.
    """

    model = django_apps.get_model("agent_runtime", "AgentProposalModel")
    if model is None:
        raise RuntimeError("agent_runtime.AgentProposalModel is not registered")
    return model


class DjangoAgentProposalGateway(AgentProposalGatewayProtocol):
    """Narrow adapter over the frozen AgentProposal ORM lifecycle."""

    def create_submitted(
        self,
        *,
        created_by_user_id: int | None,
        payload: Mapping[str, object],
    ) -> AgentProposalSnapshot:
        """Create a high-risk submitted proposal inside the caller's transaction."""

        model = _agent_proposal_model()._default_manager.create(
            request_id=f"sgp_{uuid4().hex}",
            schema_version="v1",
            task_id=None,
            proposal_type="scenario_governance",
            status="submitted",
            risk_level="high",
            approval_required=True,
            approval_status="pending",
            proposal_payload=_json_object(payload),
            approval_reason=None,
            created_by_id=created_by_user_id,
        )
        return self._snapshot(model)

    def get_for_update(self, proposal_id: int) -> AgentProposalSnapshot | None:
        """Lock one proposal row inside the surrounding transaction."""

        model = (
            _agent_proposal_model()
            ._default_manager.select_for_update()
            .filter(pk=proposal_id)
            .first()
        )
        return self._snapshot(model) if model is not None else None

    def approve(self, proposal_id: int, *, reason: str) -> AgentProposalSnapshot:
        """Transition a locked submitted proposal to approved."""

        model = _agent_proposal_model()._default_manager.select_for_update().get(pk=proposal_id)
        if model.status != "submitted" or model.approval_status != "pending":
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "proposal is not awaiting approval",
                conflict=True,
            )
        model.status = "approved"
        model.approval_status = "approved"
        model.approval_reason = reason
        model.save(update_fields=["status", "approval_status", "approval_reason", "updated_at"])
        return self._snapshot(model)

    def reject(self, proposal_id: int, *, reason: str) -> AgentProposalSnapshot:
        """Transition a locked submitted proposal to rejected."""

        model = _agent_proposal_model()._default_manager.select_for_update().get(pk=proposal_id)
        if model.status != "submitted" or model.approval_status != "pending":
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "proposal is not awaiting review",
                conflict=True,
            )
        model.status = "rejected"
        model.approval_status = "rejected"
        model.approval_reason = reason
        model.save(update_fields=["status", "approval_status", "approval_reason", "updated_at"])
        return self._snapshot(model)

    def mark_executed(self, proposal_id: int) -> AgentProposalSnapshot:
        """Transition a locked approved proposal to executed."""

        model = _agent_proposal_model()._default_manager.select_for_update().get(pk=proposal_id)
        if model.status != "approved" or model.approval_status != "approved":
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_APPROVED,
                "proposal is not approved",
                conflict=True,
            )
        model.status = "executed"
        model.save(update_fields=["status", "updated_at"])
        return self._snapshot(model)

    @staticmethod
    def _snapshot(model: Any) -> AgentProposalSnapshot:
        payload = model.proposal_payload if isinstance(model.proposal_payload, Mapping) else {}
        return AgentProposalSnapshot(
            proposal_id=int(model.pk),
            request_id=model.request_id,
            proposal_type=model.proposal_type,
            status=model.status,
            approval_status=model.approval_status,
            created_by_user_id=model.created_by_id,
            payload=cast(Mapping[str, object], payload),
        )


class DjangoScenarioGovernanceAuditWriter(ScenarioGovernanceAuditWriterProtocol):
    """Write immutable canonical Risk Center audit evidence."""

    def append(self, record: ScenarioGovernanceAuditRecord) -> str:
        """Insert the audit row on the caller's active database transaction."""

        model = ScenarioGovernanceAuditModel(
            operation=record.operation,
            actor_id=record.actor_id,
            actor_kind=record.actor_kind.value,
            approver_actor_id=record.approver_actor_id,
            capability_key=record.capability_key,
            request_fingerprint=record.request_fingerprint,
            correlation_id=record.correlation_id,
            scenario_key=record.scenario_key,
            proposal_id=record.proposal_id,
            preview_id=record.preview_id,
            revision_id=record.revision_id,
            scenario_set_revision_id=record.scenario_set_revision_id,
            activation_id=record.activation_id,
            idempotency_key=record.idempotency_key,
            base_version=record.base_version,
            before_hash=record.before_hash,
            after_hash=record.after_hash,
            details=_json_object(record.details),
        )
        model.save(force_insert=True)
        return str(model.audit_id)


class DjangoScenarioGovernanceRepository(ScenarioGovernanceRepositoryOperationsMixin):
    """Persist previews, proposals, lifecycle writes, idempotency, and audit atomically."""

    def __init__(
        self,
        *,
        proposal_gateway: AgentProposalGatewayProtocol | None = None,
        audit_writer: ScenarioGovernanceAuditWriterProtocol | None = None,
    ) -> None:
        self._proposals = proposal_gateway or DjangoAgentProposalGateway()
        self._audit = audit_writer or DjangoScenarioGovernanceAuditWriter()

    def create_preview(
        self,
        command: PreviewScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Resolve authoritative base/after state and persist exact preview evidence."""

        now = timezone.now()
        if command.expires_at <= now:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "preview expiry must be in the future",
            )
        request = command.request
        state = self._resolve_state(request, lock=False)
        self._require_expected_base(request, state)
        fingerprint = self._fingerprint(request, state)
        model = ScenarioGovernancePreviewModel(
            actor_id=request.actor.actor_id,
            actor_kind=request.actor.kind.value,
            capability_key=request.capability_key,
            operation=request.operation.value,
            scenario_key=state.scenario_key,
            exact_payload=_json_object(request.exact_payload()),
            request_fingerprint=fingerprint,
            base_version=state.base_version,
            base_hash=state.base_hash,
            after_hash=state.after_hash,
            expires_at=command.expires_at,
            created_at=now,
        )
        model.full_clean()
        model.save(force_insert=True)
        return ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.CONFIRMATION_REQUIRED,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=state.scenario_key,
            preview_id=str(model.preview_id),
            request_fingerprint=fingerprint,
            base_version=state.base_version,
            base_hash=state.base_hash,
            after_hash=state.after_hash,
            expires_at=model.expires_at,
        )

    def propose_revision(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Atomically append a proposed revision and persistent AgentProposal."""

        if command.request.operation is not ScenarioGovernanceOperation.PROPOSE:
            raise self._invalid_operation(ScenarioGovernanceOperation.PROPOSE)
        return self._commit(command, self._append_revision_proposal)

    def propose_action(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Create a persistent proposal for activate, rollback, or retire."""

        if command.request.operation is ScenarioGovernanceOperation.PROPOSE:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "propose action cannot create a scenario revision",
            )
        if command.proposal_id is not None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "new action proposals must not provide proposal_id",
            )
        return self._commit(command, self._append_action_proposal)

    def approve_proposal(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Approve one submitted proposal with a persisted human identity."""

        require_human_staff(command.actor, action="scenario proposal approval")
        with transaction.atomic():
            link = self._proposal_link_for_update(command.proposal_id)
            if link.creator_actor_id == command.actor.actor_id:
                raise ScenarioGovernanceError(
                    ScenarioGovernanceErrorCode.SELF_APPROVAL_FORBIDDEN,
                    "proposal creator cannot approve the same proposal",
                )
            proposal = self._proposal_for_update(command.proposal_id)
            if link.status in {"approved", "executed"}:
                if link.approved_by_actor_id != command.actor.actor_id:
                    raise ScenarioGovernanceError(
                        ScenarioGovernanceErrorCode.INVALID_STATE,
                        "proposal was approved by another actor",
                        conflict=True,
                    )
                return self._review_outcome(link, command, ScenarioGovernanceStatus.APPROVED, True)
            if link.status != "submitted" or proposal.status != "submitted":
                raise ScenarioGovernanceError(
                    ScenarioGovernanceErrorCode.INVALID_STATE,
                    "proposal is not awaiting approval",
                    conflict=True,
                )
            self._proposals.approve(command.proposal_id, reason=command.reason)
            approved_at = timezone.now()
            link.status = "approved"
            link.approved_by_actor_id = command.actor.actor_id
            link.approved_at = approved_at
            link.full_clean()
            link.save(
                update_fields=[
                    "status",
                    "approved_by_actor_id",
                    "approved_at",
                    "updated_at",
                ]
            )
            record = self._review_audit(link, command, "proposal_approved")
            audit_id = self._append_audit(record)
            return replace(
                self._review_outcome(
                    link,
                    command,
                    ScenarioGovernanceStatus.APPROVED,
                    False,
                ),
                audit_id=audit_id,
            )

    def reject_proposal(
        self,
        command: ReviewScenarioGovernanceProposalCommand,
    ) -> ScenarioGovernanceOutcome:
        """Reject one submitted proposal with a persisted human identity."""

        require_human_staff(command.actor, action="scenario proposal rejection")
        with transaction.atomic():
            link = self._proposal_link_for_update(command.proposal_id)
            if link.creator_actor_id == command.actor.actor_id:
                raise ScenarioGovernanceError(
                    ScenarioGovernanceErrorCode.SELF_APPROVAL_FORBIDDEN,
                    "proposal creator cannot reject the same proposal",
                )
            proposal = self._proposal_for_update(command.proposal_id)
            if link.status == "rejected":
                if link.rejected_by_actor_id != command.actor.actor_id:
                    raise ScenarioGovernanceError(
                        ScenarioGovernanceErrorCode.INVALID_STATE,
                        "proposal was rejected by another actor",
                        conflict=True,
                    )
                return self._review_outcome(link, command, ScenarioGovernanceStatus.REJECTED, True)
            if link.status != "submitted" or proposal.status != "submitted":
                raise ScenarioGovernanceError(
                    ScenarioGovernanceErrorCode.INVALID_STATE,
                    "proposal is not awaiting review",
                    conflict=True,
                )
            self._proposals.reject(command.proposal_id, reason=command.reason)
            rejected_at = timezone.now()
            link.status = "rejected"
            link.rejected_by_actor_id = command.actor.actor_id
            link.rejected_at = rejected_at
            link.full_clean()
            link.save(
                update_fields=[
                    "status",
                    "rejected_by_actor_id",
                    "rejected_at",
                    "updated_at",
                ]
            )
            record = self._review_audit(link, command, "proposal_rejected")
            audit_id = self._append_audit(record)
            return replace(
                self._review_outcome(
                    link,
                    command,
                    ScenarioGovernanceStatus.REJECTED,
                    False,
                ),
                audit_id=audit_id,
            )

    def activate(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Activate an approved set revision under a scope lock."""

        if command.request.operation is not ScenarioGovernanceOperation.ACTIVATE:
            raise self._invalid_operation(ScenarioGovernanceOperation.ACTIVATE)
        require_human_staff(command.request.actor, action="scenario activation")
        return self._commit(command, self._activate_set_revision)

    def rollback(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Copy a prior set revision into a new version and activate it."""

        if command.request.operation is not ScenarioGovernanceOperation.ROLLBACK:
            raise self._invalid_operation(ScenarioGovernanceOperation.ROLLBACK)
        require_human_staff(command.request.actor, action="scenario rollback")
        return self._commit(command, self._rollback_set_revision)

    def retire(
        self,
        command: CommitScenarioGovernanceCommand,
    ) -> ScenarioGovernanceOutcome:
        """Retire a definition while preserving every immutable revision."""

        if command.request.operation is not ScenarioGovernanceOperation.RETIRE:
            raise self._invalid_operation(ScenarioGovernanceOperation.RETIRE)
        require_human_staff(command.request.actor, action="scenario retirement")
        return self._commit(command, self._retire_definition)

    def _commit(
        self,
        command: CommitScenarioGovernanceCommand,
        executor: Callable[[_CommitContext], _CommitProduct],
    ) -> ScenarioGovernanceOutcome:
        initial_preview = self._preview(command.preview_id, lock=False)
        self._require_preview_identity(initial_preview, command)
        fingerprint = self._fingerprint_with_preview(command.request, initial_preview)
        replay = self._idempotency_result(command, fingerprint, lock=False)
        if replay is not None:
            return replay
        try:
            with transaction.atomic():
                preview = self._preview(command.preview_id, lock=True)
                self._require_preview_identity(preview, command)
                fingerprint = self._fingerprint_with_preview(command.request, preview)
                replay = self._idempotency_result(command, fingerprint, lock=True)
                if replay is not None:
                    return replay
                self._require_usable_preview(preview, command, fingerprint)
                state = self._resolve_state(command.request, lock=True)
                self._require_expected_base(command.request, state)
                self._require_state_matches_preview(state, preview)
                product = executor(
                    _CommitContext(
                        command=command,
                        preview=preview,
                        state=state,
                        request_fingerprint=fingerprint,
                    )
                )
                audit_id = self._append_audit(product.audit)
                outcome = replace(product.outcome, audit_id=audit_id)
                self._consume_preview(preview, command)
                self._save_idempotency(command, fingerprint, preview, outcome)
                return outcome
        except IntegrityError as exc:
            replay = self._idempotency_result(command, fingerprint, lock=False)
            if replay is not None:
                return replay
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.OPTIMISTIC_LOCK_CONFLICT,
                "concurrent scenario governance write conflicted",
                conflict=True,
            ) from exc

    def _append_revision_proposal(self, context: _CommitContext) -> _CommitProduct:
        command = context.command
        request = command.request
        revision_command = request.revision_command
        if revision_command is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "typed revision command is required",
            )
        definition = context.state.definition
        if definition is None:
            definition = self._create_definition(request)
        else:
            self._validate_definition_metadata(definition, request)
        version = (context.state.base_version or 0) + 1
        source_type = revision_command.source_type
        if request.actor.kind is not ScenarioGovernanceActorKind.HUMAN:
            source_type = ScenarioSourceType.AI_MCP
        revision = ScenarioRevision(
            revision_id=str(uuid4()),
            scenario_key=revision_command.scenario_key,
            version=version,
            based_on_version=context.state.base_version,
            status=ScenarioRevisionStatus.PROPOSED,
            scenario_type=revision_command.scenario_type,
            parameters=revision_command.parameters,
            assumptions=revision_command.assumptions,
            source_type=source_type,
            source_evidence=revision_command.source_evidence,
            created_by=request.actor.actor_id,
            change_reason=request.change_reason,
            created_at=timezone.now(),
        )
        if revision.content_hash != context.state.after_hash:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "revision content changed after preview",
                conflict=True,
            )
        revision_model = StressScenarioRevisionModel(
            revision_id=revision.revision_id,
            definition=definition,
            version=revision.version,
            based_on_version=revision.based_on_version,
            status=revision.status.value,
            scenario_type=revision.scenario_type.value,
            parameters=scenario_parameters_to_dict(revision.parameters),
            assumptions=list(revision.assumptions),
            source_evidence=_json_array(revision.source_evidence),
            source_type=revision.source_type.value,
            content_hash=revision.content_hash,
            created_by=revision.created_by,
            change_reason=revision.change_reason,
            effective_at=revision.effective_at,
            created_at=revision.created_at,
        )
        revision_model.save(force_insert=True)
        proposal = self._create_proposal(context, revision_id=revision.revision_id)
        self._create_proposal_link(
            context,
            proposal,
            revision=revision_model,
        )
        outcome = ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.CREATED,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=revision.scenario_key,
            revision_id=revision.revision_id,
            proposal_id=proposal.proposal_id,
            preview_id=str(context.preview.preview_id),
            version=revision.version,
            content_hash=revision.content_hash,
            request_fingerprint=context.request_fingerprint,
            base_version=context.state.base_version,
            base_hash=context.state.base_hash,
            after_hash=context.state.after_hash,
        )
        audit = self._audit_record(
            context,
            operation="proposal_created",
            proposal_id=proposal.proposal_id,
            revision_id=revision.revision_id,
            after_hash=revision.content_hash,
        )
        return _CommitProduct(outcome, audit)

    def _append_action_proposal(self, context: _CommitContext) -> _CommitProduct:
        proposal = self._create_proposal(context)
        set_revision = context.state.target_set_revision or context.state.rollback_target
        self._create_proposal_link(
            context,
            proposal,
            scenario_set_revision=set_revision,
        )
        request = context.command.request
        outcome = ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.CONFIRMATION_REQUIRED,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=context.state.scenario_key,
            proposal_id=proposal.proposal_id,
            preview_id=str(context.preview.preview_id),
            version=(
                set_revision.version if set_revision is not None else context.state.base_version
            ),
            content_hash=(
                set_revision.content_hash if set_revision is not None else context.state.after_hash
            ),
            request_fingerprint=context.request_fingerprint,
            base_version=context.state.base_version,
            base_hash=context.state.base_hash,
            after_hash=context.state.after_hash,
        )
        audit = self._audit_record(
            context,
            operation=f"{request.operation.value}_proposal_created",
            proposal_id=proposal.proposal_id,
            scenario_set_revision_id=(
                str(set_revision.revision_id) if set_revision is not None else None
            ),
        )
        return _CommitProduct(outcome, audit)

    def _activate_set_revision(self, context: _CommitContext) -> _CommitProduct:
        target = context.state.target_set_revision
        if target is None:
            raise self._target_not_found("scenario set revision")
        link = self._approved_proposal(context)
        activation = self._replace_activation(context, target)
        self._execute_proposal(link)
        request = context.command.request
        outcome = ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.ACTIVATED,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=target.scenario_set.set_key,
            proposal_id=link.proposal_id,
            preview_id=str(context.preview.preview_id),
            version=target.version,
            content_hash=target.content_hash,
            activation_id=str(activation.activation_id),
            request_fingerprint=context.request_fingerprint,
            base_version=context.state.base_version,
            base_hash=context.state.base_hash,
            after_hash=context.state.after_hash,
            details={"scenario_set_revision_id": str(target.revision_id)},
        )
        audit = self._audit_record(
            context,
            operation="scenario_set_activated",
            proposal_id=link.proposal_id,
            scenario_set_revision_id=str(target.revision_id),
            activation_id=str(activation.activation_id),
            approver_actor_id=link.approved_by_actor_id,
        )
        return _CommitProduct(outcome, audit)

    def _rollback_set_revision(self, context: _CommitContext) -> _CommitProduct:
        target = context.state.rollback_target
        current = context.state.current_activation
        if target is None or current is None:
            raise self._target_not_found("rollback target or current activation")
        link = self._approved_proposal(context)
        scenario_set = target.scenario_set
        latest = (
            ScenarioSetRevisionModel._default_manager.filter(scenario_set=scenario_set)
            .order_by("-version")
            .first()
        )
        next_version = (latest.version if latest is not None else 0) + 1
        members = tuple(
            ScenarioSetMember(
                scenario_revision_id=str(item.scenario_revision_id),
                probability=Decimal(str(item.probability)),
                probability_source=ProbabilitySource(item.probability_source),
                sort_order=item.sort_order,
            )
            for item in target.members.all()
        )
        domain_revision = ScenarioSetRevision(
            revision_id=str(uuid4()),
            set_key=scenario_set.set_key,
            version=next_version,
            status=ScenarioRevisionStatus.APPROVED,
            members=members,
            driver_axes=tuple(str(item) for item in (target.driver_axes or [])),
            created_by=context.command.request.actor.actor_id,
            change_reason=context.command.request.change_reason,
            effective_from=target.effective_from,
            effective_to=target.effective_to,
            created_at=timezone.now(),
        )
        if domain_revision.content_hash != context.state.after_hash:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "rollback target content changed after preview",
                conflict=True,
            )
        revision_model = ScenarioSetRevisionModel(
            revision_id=domain_revision.revision_id,
            scenario_set=scenario_set,
            version=domain_revision.version,
            status=domain_revision.status.value,
            driver_axes=list(domain_revision.driver_axes),
            content_hash=domain_revision.content_hash,
            created_by=domain_revision.created_by,
            change_reason=domain_revision.change_reason,
            effective_from=domain_revision.effective_from,
            effective_to=domain_revision.effective_to,
            created_at=domain_revision.created_at,
        )
        revision_model.save(force_insert=True)
        source_members = {str(item.scenario_revision_id): item for item in target.members.all()}
        for member in domain_revision.members:
            source = source_members[member.scenario_revision_id]
            member_model = ScenarioSetMemberModel(
                scenario_set_revision=revision_model,
                scenario_revision_id=source.scenario_revision_id,
                probability=member.probability,
                probability_source=member.probability_source.value,
                sort_order=member.sort_order,
                created_at=timezone.now(),
            )
            member_model.save(force_insert=True)
        activation = self._replace_activation(context, revision_model)
        self._execute_proposal(link)
        request = context.command.request
        outcome = ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.ROLLED_BACK,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=scenario_set.set_key,
            revision_id=str(revision_model.revision_id),
            proposal_id=link.proposal_id,
            preview_id=str(context.preview.preview_id),
            version=revision_model.version,
            content_hash=revision_model.content_hash,
            activation_id=str(activation.activation_id),
            request_fingerprint=context.request_fingerprint,
            base_version=context.state.base_version,
            base_hash=context.state.base_hash,
            after_hash=context.state.after_hash,
            details={
                "rollback_target_version": target.version,
                "scenario_set_revision_id": str(revision_model.revision_id),
            },
        )
        audit = self._audit_record(
            context,
            operation="scenario_set_rolled_back",
            proposal_id=link.proposal_id,
            revision_id=str(revision_model.revision_id),
            scenario_set_revision_id=str(revision_model.revision_id),
            activation_id=str(activation.activation_id),
            approver_actor_id=link.approved_by_actor_id,
            details={"rollback_target_version": target.version},
        )
        return _CommitProduct(outcome, audit)

    def _retire_definition(self, context: _CommitContext) -> _CommitProduct:
        definition = context.state.definition
        if definition is None:
            raise self._target_not_found("scenario definition")
        link = self._approved_proposal(context)
        active_reference = (
            ScenarioActivationModel._default_manager.select_for_update()
            .filter(
                is_active=True,
                scenario_set_revision__members__scenario_revision__definition=definition,
            )
            .first()
        )
        if active_reference is not None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.TARGET_IN_USE,
                "scenario remains referenced by an active scenario set",
                conflict=True,
            )
        definition.status = ScenarioDefinitionStatus.RETIRED.value
        definition.save(update_fields=["status", "updated_at"])
        self._execute_proposal(link)
        request = context.command.request
        outcome = ScenarioGovernanceOutcome(
            status=ScenarioGovernanceStatus.RETIRED,
            operation=request.operation,
            correlation_id=request.correlation_id,
            scenario_key=definition.scenario_key,
            proposal_id=link.proposal_id,
            preview_id=str(context.preview.preview_id),
            version=context.state.base_version,
            content_hash=context.state.after_hash,
            request_fingerprint=context.request_fingerprint,
            base_version=context.state.base_version,
            base_hash=context.state.base_hash,
            after_hash=context.state.after_hash,
            details={"definition_status": "retired"},
        )
        audit = self._audit_record(
            context,
            operation="scenario_retired",
            proposal_id=link.proposal_id,
            approver_actor_id=link.approved_by_actor_id,
            details={"definition_status": "retired"},
        )
        return _CommitProduct(outcome, audit)

    def _resolve_state(self, request: ScenarioGovernanceRequest, *, lock: bool) -> _ResolvedState:
        operation = request.operation
        if operation is ScenarioGovernanceOperation.PROPOSE:
            return self._resolve_propose(request, lock=lock)
        if operation is ScenarioGovernanceOperation.ACTIVATE:
            return self._resolve_activate(request, lock=lock)
        if operation is ScenarioGovernanceOperation.ROLLBACK:
            return self._resolve_rollback(request, lock=lock)
        return self._resolve_retire(request, lock=lock)

    def _resolve_propose(self, request: ScenarioGovernanceRequest, *, lock: bool) -> _ResolvedState:
        scenario_key = str(request.target.scenario_key)
        definitions = StressScenarioDefinitionModel._default_manager.all()
        if lock:
            definitions = definitions.select_for_update()
        definition = definitions.filter(scenario_key=scenario_key).first()
        if definition is not None and definition.status != ScenarioDefinitionStatus.ACTIVE.value:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "retired scenario definitions cannot receive revisions",
                conflict=True,
            )
        latest = None
        if definition is not None:
            revisions = StressScenarioRevisionModel._default_manager.all()
            if lock:
                revisions = revisions.select_for_update()
            latest = revisions.filter(definition=definition).order_by("-version").first()
        revision_command = request.revision_command
        if revision_command is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "typed revision command is required",
            )
        candidate = ScenarioRevision(
            revision_id="preview",
            scenario_key=revision_command.scenario_key,
            version=(latest.version if latest is not None else 0) + 1,
            based_on_version=(latest.version if latest is not None else None),
            status=ScenarioRevisionStatus.PROPOSED,
            scenario_type=revision_command.scenario_type,
            parameters=revision_command.parameters,
            assumptions=revision_command.assumptions,
            source_type=revision_command.source_type,
            source_evidence=revision_command.source_evidence,
            created_by=request.actor.actor_id,
            change_reason=request.change_reason,
            created_at=timezone.now(),
        )
        return _ResolvedState(
            scenario_key=scenario_key,
            base_version=(latest.version if latest is not None else None),
            base_hash=(latest.content_hash if latest is not None else None),
            after_hash=candidate.content_hash,
            definition=definition,
            latest_revision=latest,
        )

    def _resolve_activate(
        self, request: ScenarioGovernanceRequest, *, lock: bool
    ) -> _ResolvedState:
        target_id = str(request.target.scenario_set_revision_id)
        revisions = ScenarioSetRevisionModel._default_manager.select_related("scenario_set")
        if lock:
            revisions = revisions.select_for_update()
        try:
            target = revisions.filter(revision_id=target_id).first()
        except (ValidationError, ValueError):
            target = None
        if target is None:
            raise self._target_not_found("scenario set revision")
        if target.status not in {
            ScenarioRevisionStatus.APPROVED.value,
            ScenarioRevisionStatus.ACTIVE.value,
        }:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "only approved scenario set revisions may be activated",
                conflict=True,
            )
        if target.scenario_set.purpose != request.target.purpose:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "scenario set purpose mismatch",
            )
        if lock:
            ScenarioSetModel._default_manager.select_for_update().get(pk=target.scenario_set_id)
        current = self._current_activation(request, lock=lock)
        return _ResolvedState(
            scenario_key=target.scenario_set.set_key,
            base_version=(current.scenario_set_revision.version if current else None),
            base_hash=(current.scenario_set_revision.content_hash if current else None),
            after_hash=target.content_hash,
            target_set_revision=target,
            current_activation=current,
        )

    def _resolve_rollback(
        self, request: ScenarioGovernanceRequest, *, lock: bool
    ) -> _ResolvedState:
        set_key = str(request.target.scenario_key)
        sets = ScenarioSetModel._default_manager.all()
        if lock:
            sets = sets.select_for_update()
        scenario_set = sets.filter(set_key=set_key).first()
        if scenario_set is None:
            raise self._target_not_found("scenario set")
        revisions = ScenarioSetRevisionModel._default_manager.select_related("scenario_set")
        if lock:
            revisions = revisions.select_for_update()
        target_version = request.target.target_version
        if target_version is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_REQUEST,
                "rollback target_version is required",
            )
        target = revisions.filter(
            scenario_set=scenario_set,
            version=target_version,
            status__in=(
                ScenarioRevisionStatus.APPROVED.value,
                ScenarioRevisionStatus.ACTIVE.value,
            ),
        ).first()
        if target is None:
            raise self._target_not_found("approved rollback target")
        current = self._current_activation(request, lock=lock)
        if current is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "rollback requires an active scenario set",
                conflict=True,
            )
        if current.scenario_set_revision.scenario_set_id != scenario_set.pk:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "active scenario set does not match rollback target",
                conflict=True,
            )
        return _ResolvedState(
            scenario_key=set_key,
            base_version=current.scenario_set_revision.version,
            base_hash=current.scenario_set_revision.content_hash,
            after_hash=target.content_hash,
            rollback_target=target,
            current_activation=current,
        )

    def _resolve_retire(self, request: ScenarioGovernanceRequest, *, lock: bool) -> _ResolvedState:
        scenario_key = str(request.target.scenario_key)
        definitions = StressScenarioDefinitionModel._default_manager.all()
        if lock:
            definitions = definitions.select_for_update()
        definition = definitions.filter(scenario_key=scenario_key).first()
        if definition is None:
            raise self._target_not_found("scenario definition")
        if definition.status != ScenarioDefinitionStatus.ACTIVE.value:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.INVALID_STATE,
                "scenario definition is already retired",
                conflict=True,
            )
        revisions = StressScenarioRevisionModel._default_manager.all()
        if lock:
            revisions = revisions.select_for_update()
        latest = revisions.filter(definition=definition).order_by("-version").first()
        if latest is None:
            raise self._target_not_found("scenario revision")
        after_hash = stable_governance_hash(
            {
                "scenario_key": scenario_key,
                "definition_status": "retired",
                "previous_content_hash": latest.content_hash,
            }
        )
        return _ResolvedState(
            scenario_key=scenario_key,
            base_version=latest.version,
            base_hash=latest.content_hash,
            after_hash=after_hash,
            definition=definition,
            latest_revision=latest,
        )


__all__ = [
    "DjangoAgentProposalGateway",
    "DjangoScenarioGovernanceAuditWriter",
    "DjangoScenarioGovernanceRepository",
]
