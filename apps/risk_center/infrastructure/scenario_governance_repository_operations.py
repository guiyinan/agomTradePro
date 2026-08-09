"""Supporting write, proposal, preview, and audit operations for scenario governance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.risk_center.application.scenario_governance import (
    AgentProposalGatewayProtocol,
    AgentProposalSnapshot,
    CommitScenarioGovernanceCommand,
    ReviewScenarioGovernanceProposalCommand,
    ScenarioGovernanceAuditWriterProtocol,
    ScenarioGovernanceRequest,
)
from apps.risk_center.domain.scenario_governance import (
    ScenarioGovernanceAuditRecord,
    ScenarioGovernanceError,
    ScenarioGovernanceErrorCode,
    ScenarioGovernanceOperation,
    ScenarioGovernanceOutcome,
    ScenarioGovernanceStatus,
    scenario_governance_fingerprint,
)
from apps.risk_center.domain.scenarios import ScenarioDefinitionStatus
from apps.risk_center.infrastructure.models import (
    ScenarioActivationModel,
    ScenarioSetRevisionModel,
    StressScenarioDefinitionModel,
    StressScenarioRevisionModel,
)
from apps.risk_center.infrastructure.scenario_governance_models import (
    ScenarioGovernanceIdempotencyModel,
    ScenarioGovernancePreviewModel,
    ScenarioGovernanceProposalLinkModel,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    ResolvedScenarioGovernanceState as _ResolvedState,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    ScenarioGovernanceCommitContext as _CommitContext,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    json_object as _json_object,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    optional_payload_text as _optional_payload_text,
)
from apps.risk_center.infrastructure.scenario_governance_repository_support import (
    required_text as _required_text,
)


class ScenarioGovernanceRepositoryOperationsMixin:
    """Provide operational helpers for the transactional repository."""

    _proposals: AgentProposalGatewayProtocol
    _audit: ScenarioGovernanceAuditWriterProtocol

    def _current_activation(
        self,
        request: ScenarioGovernanceRequest,
        *,
        lock: bool,
    ) -> ScenarioActivationModel | None:
        queryset = ScenarioActivationModel._default_manager.select_related(
            "scenario_set_revision__scenario_set"
        )
        if lock:
            queryset = queryset.select_for_update()
        return queryset.filter(
            environment=request.target.environment,
            purpose=request.target.purpose,
            is_active=True,
        ).first()

    def _replace_activation(
        self,
        context: _CommitContext,
        target: ScenarioSetRevisionModel,
    ) -> ScenarioActivationModel:
        current = context.state.current_activation
        now = timezone.now()
        if current is not None:
            current.is_active = False
            current.deactivated_at = now
            current.save(update_fields=["is_active", "deactivated_at"])
        request = context.command.request
        return ScenarioActivationModel._default_manager.create(
            environment=str(request.target.environment),
            purpose=str(request.target.purpose),
            scenario_set_revision=target,
            previous_activation=current,
            activated_by=request.actor.actor_id,
            reason=request.change_reason,
            correlation_id=request.correlation_id,
            activated_at=now,
            is_active=True,
        )

    def _create_definition(
        self,
        request: ScenarioGovernanceRequest,
    ) -> StressScenarioDefinitionModel:
        payload = request.payload
        model = StressScenarioDefinitionModel(
            scenario_key=str(request.target.scenario_key),
            name=_required_text(payload, "name", maximum=160),
            category=_required_text(payload, "category", maximum=80),
            owner=_required_text(payload, "owner", maximum=80),
            status=ScenarioDefinitionStatus.ACTIVE.value,
            description=_optional_payload_text(payload, "description", maximum=2_000),
            legacy_aliases=[],
            created_at=timezone.now(),
        )
        model.full_clean()
        model.save(force_insert=True)
        return model

    def _validate_definition_metadata(
        self,
        definition: StressScenarioDefinitionModel,
        request: ScenarioGovernanceRequest,
    ) -> None:
        payload = request.payload
        supplied = {
            "name": payload.get("name"),
            "category": payload.get("category"),
            "owner": payload.get("owner"),
        }
        for field_name, value in supplied.items():
            if value is not None and str(value).strip() != str(getattr(definition, field_name)):
                raise ScenarioGovernanceError(
                    ScenarioGovernanceErrorCode.INVALID_REQUEST,
                    f"existing scenario definition {field_name} cannot be changed by revision",
                )

    def _create_proposal(
        self,
        context: _CommitContext,
        *,
        revision_id: str | None = None,
    ) -> AgentProposalSnapshot:
        request = context.command.request
        return self._proposals.create_submitted(
            created_by_user_id=request.actor.user_id,
            payload={
                "governance_contract": "risk_center.scenario.v1",
                "operation": request.operation.value,
                "capability_key": request.capability_key,
                "creator_actor_id": request.actor.actor_id,
                "creator_actor_kind": request.actor.kind.value,
                "preview_id": str(context.preview.preview_id),
                "request_fingerprint": context.request_fingerprint,
                "base_version": context.state.base_version,
                "base_hash": context.state.base_hash,
                "after_hash": context.state.after_hash,
                "revision_id": revision_id,
                "exact_payload": request.exact_payload(),
            },
        )

    def _create_proposal_link(
        self,
        context: _CommitContext,
        proposal: AgentProposalSnapshot,
        *,
        revision: StressScenarioRevisionModel | None = None,
        scenario_set_revision: ScenarioSetRevisionModel | None = None,
    ) -> ScenarioGovernanceProposalLinkModel:
        request = context.command.request
        model = ScenarioGovernanceProposalLinkModel(
            proposal_id=proposal.proposal_id,
            preview=context.preview,
            operation=request.operation.value,
            creator_actor_id=request.actor.actor_id,
            creator_actor_kind=request.actor.kind.value,
            capability_key=request.capability_key,
            request_fingerprint=context.request_fingerprint,
            status="submitted",
            scenario_key=context.state.scenario_key,
            revision=revision,
            scenario_set_revision=scenario_set_revision,
            target_version=request.target.target_version,
            created_at=timezone.now(),
        )
        model.full_clean()
        model.save(force_insert=True)
        return model

    def _approved_proposal(
        self,
        context: _CommitContext,
    ) -> ScenarioGovernanceProposalLinkModel:
        proposal_id = context.command.proposal_id
        if proposal_id is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_FOUND,
                "approved proposal_id is required",
            )
        link = self._proposal_link_for_update(proposal_id)
        proposal = self._proposal_for_update(proposal_id)
        actor = context.command.request.actor
        if link.operation != context.command.request.operation.value:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "proposal operation does not match confirmed operation",
                conflict=True,
            )
        if link.capability_key != context.command.request.capability_key:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "proposal capability does not match confirmed capability",
                conflict=True,
            )
        if link.request_fingerprint != context.request_fingerprint:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "proposal payload or base evidence does not match preview",
                conflict=True,
            )
        if link.status != "approved" or proposal.status != "approved":
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_APPROVED,
                "scenario governance proposal is not approved",
                conflict=True,
            )
        if not link.approved_by_actor_id or link.approved_at is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_APPROVED,
                "scenario governance proposal lacks approval evidence",
                conflict=True,
            )
        if link.approved_by_actor_id == link.creator_actor_id:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.SELF_APPROVAL_FORBIDDEN,
                "proposal creator cannot approve the same proposal",
            )
        if actor.actor_id != link.approved_by_actor_id:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PERMISSION_DENIED,
                "the persisted human approver must execute this proposal",
            )
        return link

    def _execute_proposal(self, link: ScenarioGovernanceProposalLinkModel) -> None:
        self._proposals.mark_executed(link.proposal_id)
        executed_at = timezone.now()
        link.status = "executed"
        link.executed_at = executed_at
        link.full_clean()
        link.save(update_fields=["status", "executed_at", "updated_at"])

    def _proposal_link_for_update(
        self,
        proposal_id: int,
    ) -> ScenarioGovernanceProposalLinkModel:
        link = (
            ScenarioGovernanceProposalLinkModel._default_manager.select_for_update()
            .select_related("revision", "scenario_set_revision", "preview")
            .filter(proposal_id=proposal_id)
            .first()
        )
        if link is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_FOUND,
                "scenario governance proposal was not found",
            )
        return link

    def _proposal_for_update(self, proposal_id: int) -> AgentProposalSnapshot:
        proposal = self._proposals.get_for_update(proposal_id)
        if proposal is None or proposal.proposal_type != "scenario_governance":
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PROPOSAL_NOT_FOUND,
                "persistent AgentProposal was not found",
            )
        return proposal

    def _review_outcome(
        self,
        link: ScenarioGovernanceProposalLinkModel,
        command: ReviewScenarioGovernanceProposalCommand,
        status: ScenarioGovernanceStatus,
        replayed: bool,
    ) -> ScenarioGovernanceOutcome:
        revision = link.revision
        set_revision = link.scenario_set_revision
        return ScenarioGovernanceOutcome(
            status=status,
            operation=ScenarioGovernanceOperation(link.operation),
            correlation_id=command.correlation_id,
            scenario_key=link.scenario_key,
            revision_id=(str(revision.revision_id) if revision is not None else None),
            proposal_id=link.proposal_id,
            preview_id=str(link.preview_id),
            version=(
                revision.version
                if revision is not None
                else set_revision.version if set_revision is not None else None
            ),
            content_hash=(
                revision.content_hash
                if revision is not None
                else set_revision.content_hash if set_revision is not None else None
            ),
            request_fingerprint=link.request_fingerprint,
            replayed=replayed,
        )

    def _review_audit(
        self,
        link: ScenarioGovernanceProposalLinkModel,
        command: ReviewScenarioGovernanceProposalCommand,
        operation: str,
    ) -> ScenarioGovernanceAuditRecord:
        return ScenarioGovernanceAuditRecord(
            operation=operation,
            actor_id=command.actor.actor_id,
            actor_kind=command.actor.kind,
            approver_actor_id=command.actor.actor_id,
            capability_key=link.capability_key,
            request_fingerprint=link.request_fingerprint,
            correlation_id=command.correlation_id,
            scenario_key=link.scenario_key,
            proposal_id=link.proposal_id,
            preview_id=str(link.preview_id),
            revision_id=(str(link.revision_id) if link.revision_id else None),
            scenario_set_revision_id=(
                str(link.scenario_set_revision_id) if link.scenario_set_revision_id else None
            ),
            after_hash=(
                link.revision.content_hash
                if link.revision is not None
                else (
                    link.scenario_set_revision.content_hash
                    if link.scenario_set_revision is not None
                    else link.preview.after_hash
                )
            ),
            details={"reason": command.reason},
        )

    def _audit_record(
        self,
        context: _CommitContext,
        *,
        operation: str,
        proposal_id: int | None = None,
        revision_id: str | None = None,
        scenario_set_revision_id: str | None = None,
        activation_id: str | None = None,
        approver_actor_id: str | None = None,
        after_hash: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> ScenarioGovernanceAuditRecord:
        request = context.command.request
        return ScenarioGovernanceAuditRecord(
            operation=operation,
            actor_id=request.actor.actor_id,
            actor_kind=request.actor.kind,
            approver_actor_id=approver_actor_id,
            capability_key=request.capability_key,
            request_fingerprint=context.request_fingerprint,
            correlation_id=request.correlation_id,
            scenario_key=context.state.scenario_key,
            proposal_id=proposal_id,
            preview_id=str(context.preview.preview_id),
            revision_id=revision_id,
            scenario_set_revision_id=scenario_set_revision_id,
            activation_id=activation_id,
            idempotency_key=context.command.idempotency_key,
            base_version=context.state.base_version,
            before_hash=context.state.base_hash,
            after_hash=after_hash or context.state.after_hash,
            details=details or {},
        )

    def _append_audit(self, record: ScenarioGovernanceAuditRecord) -> str:
        try:
            return self._audit.append(record)
        except ScenarioGovernanceError:
            raise
        except Exception as exc:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.AUDIT_WRITE_FAILED,
                "canonical scenario governance audit could not be persisted",
            ) from exc

    def _preview(self, preview_id: str, *, lock: bool) -> ScenarioGovernancePreviewModel:
        queryset = ScenarioGovernancePreviewModel._default_manager.all()
        if lock:
            queryset = queryset.select_for_update()
        try:
            model = queryset.filter(preview_id=preview_id).first()
        except (ValidationError, ValueError):
            model = None
        if model is None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_NOT_FOUND,
                "scenario governance preview was not found",
            )
        return model

    def _require_preview_identity(
        self,
        preview: ScenarioGovernancePreviewModel,
        command: CommitScenarioGovernanceCommand,
    ) -> None:
        request = command.request
        if (
            preview.actor_id != request.actor.actor_id
            or preview.actor_kind != request.actor.kind.value
        ):
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "preview belongs to a different actor",
            )
        if (
            preview.capability_key != request.capability_key
            or preview.operation != request.operation.value
        ):
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "preview belongs to a different capability or operation",
            )

    def _require_usable_preview(
        self,
        preview: ScenarioGovernancePreviewModel,
        command: CommitScenarioGovernanceCommand,
        fingerprint: str,
    ) -> None:
        now = timezone.now()
        if preview.consumed_at is not None:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_ALREADY_USED,
                "scenario governance preview has already been consumed",
                conflict=True,
            )
        if preview.expires_at <= now:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_EXPIRED,
                "scenario governance preview has expired",
                conflict=True,
            )
        if preview.request_fingerprint != fingerprint:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "confirmed payload differs from the persisted preview",
                conflict=True,
            )
        if (
            preview.base_version != command.request.expected_base_version
            or preview.base_hash != command.request.expected_base_hash
        ):
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.PREVIEW_BINDING_MISMATCH,
                "confirmed optimistic-lock evidence differs from preview",
                conflict=True,
            )

    def _require_expected_base(
        self,
        request: ScenarioGovernanceRequest,
        state: _ResolvedState,
    ) -> None:
        if (
            request.expected_base_version != state.base_version
            or request.expected_base_hash != state.base_hash
        ):
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.OPTIMISTIC_LOCK_CONFLICT,
                "active or latest scenario version changed",
                conflict=True,
            )

    def _require_state_matches_preview(
        self,
        state: _ResolvedState,
        preview: ScenarioGovernancePreviewModel,
    ) -> None:
        if (
            state.base_version != preview.base_version
            or state.base_hash != preview.base_hash
            or state.after_hash != preview.after_hash
        ):
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.OPTIMISTIC_LOCK_CONFLICT,
                "scenario state changed after preview",
                conflict=True,
            )

    def _fingerprint(self, request: ScenarioGovernanceRequest, state: _ResolvedState) -> str:
        return scenario_governance_fingerprint(
            operation=request.operation,
            capability_key=request.capability_key,
            payload=request.exact_payload(),
            base_version=state.base_version,
            base_hash=state.base_hash,
        )

    def _fingerprint_with_preview(
        self,
        request: ScenarioGovernanceRequest,
        preview: ScenarioGovernancePreviewModel,
    ) -> str:
        return scenario_governance_fingerprint(
            operation=request.operation,
            capability_key=request.capability_key,
            payload=request.exact_payload(),
            base_version=preview.base_version,
            base_hash=preview.base_hash,
        )

    def _idempotency_result(
        self,
        command: CommitScenarioGovernanceCommand,
        fingerprint: str,
        *,
        lock: bool,
    ) -> ScenarioGovernanceOutcome | None:
        queryset = ScenarioGovernanceIdempotencyModel._default_manager.all()
        if lock:
            queryset = queryset.select_for_update()
        model = queryset.filter(
            actor_id=command.request.actor.actor_id,
            capability_key=command.request.capability_key,
            idempotency_key=command.idempotency_key,
        ).first()
        if model is None:
            return None
        if model.request_fingerprint != fingerprint:
            raise ScenarioGovernanceError(
                ScenarioGovernanceErrorCode.IDEMPOTENCY_CONFLICT,
                "idempotency key was already used with a different request",
                conflict=True,
            )
        result = model.result if isinstance(model.result, Mapping) else {}
        return ScenarioGovernanceOutcome.from_mapping(
            cast(Mapping[str, object], result)
        ).as_replay()

    def _consume_preview(
        self,
        preview: ScenarioGovernancePreviewModel,
        command: CommitScenarioGovernanceCommand,
    ) -> None:
        preview.consumed_at = timezone.now()
        preview.consumed_idempotency_key = command.idempotency_key
        preview.full_clean()
        preview.save(update_fields=["consumed_at", "consumed_idempotency_key"])

    def _save_idempotency(
        self,
        command: CommitScenarioGovernanceCommand,
        fingerprint: str,
        preview: ScenarioGovernancePreviewModel,
        outcome: ScenarioGovernanceOutcome,
    ) -> None:
        model = ScenarioGovernanceIdempotencyModel(
            actor_id=command.request.actor.actor_id,
            capability_key=command.request.capability_key,
            idempotency_key=command.idempotency_key,
            operation=command.request.operation.value,
            request_fingerprint=fingerprint,
            preview=preview,
            result=_json_object(outcome.as_dict()),
            created_at=timezone.now(),
        )
        model.full_clean()
        model.save(force_insert=True)

    @staticmethod
    def _invalid_operation(
        expected: ScenarioGovernanceOperation,
    ) -> ScenarioGovernanceError:
        return ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.INVALID_REQUEST,
            f"expected {expected.value} scenario governance operation",
        )

    @staticmethod
    def _target_not_found(target: str) -> ScenarioGovernanceError:
        return ScenarioGovernanceError(
            ScenarioGovernanceErrorCode.TARGET_NOT_FOUND,
            f"{target} was not found",
        )
