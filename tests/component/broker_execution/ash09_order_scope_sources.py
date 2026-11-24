"""Native ledger inputs for Broker consent integration; no mocked owner queries or broker IO."""

from dataclasses import asdict, replace
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from django.utils import timezone

from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    DecisionPermission,
    EvidenceOperatorSpec,
    GovernanceState,
    resolve_evidence_envelope,
)
from apps.research.domain.evidence_scope_source_v1 import (
    EvidenceScopeSourceV1,
    root_claim_hash_for_evidence_scope_source_v1,
)
from apps.research.infrastructure.evidence_repository import _build_evidence_store
from apps.research.infrastructure.evidence_scope_source_v1_repository import (
    _build_evidence_scope_source_v1_store,
)
from apps.research.order_execution_evidence_composition import order_execution_output
from tests.component.research.test_evidence_repository import _spec, _track
from tests.unit.research.test_evidence_contracts import _input


def persist_order_research(
    *,
    intent: BrokerCheckpointIntent,
    registrar_session,
    reviewer_session,
    tenant_id: str,
    owner_id: str,
    using: str = "default",
    permission: DecisionPermission = DecisionPermission.DISPLAY_ONLY,
    ordinary_material: bool = False,
) -> dict[str, str]:
    """Persist an exact per-order output, activation, track and three scoped read grants."""
    order = intent.sources.order
    output = ArtifactRef(
        order.owner,
        order.artifact_type,
        order.artifact_id,
        order.artifact_version,
        order.content_hash,
    )
    plan = intent.sources.plan
    return persist_research_output(
        ordinary_material=ordinary_material,
        registrar_session=registrar_session,
        reviewer_session=reviewer_session,
        order=output,
        plan=ArtifactRef(
            plan.portfolio_plan_owner,
            plan.portfolio_plan_artifact_type,
            plan.portfolio_plan_id,
            str(plan.portfolio_plan_version),
            plan.portfolio_plan_content_hash,
        ),
        plan_receipt=ArtifactRef(
            plan.portfolio_receipt_owner,
            plan.portfolio_receipt_capability,
            plan.portfolio_receipt_id,
            plan.portfolio_receipt_version,
            plan.portfolio_receipt_content_hash,
        ),
        owner_user_id=intent.owner_user_id,
        account_id=intent.sources.account.portfolio_account_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        permission=permission,
        using=using,
    )


def persist_research_output(
    *,
    registrar_session,
    reviewer_session,
    order: ArtifactRef,
    plan: ArtifactRef,
    plan_receipt: ArtifactRef,
    owner_user_id: int,
    account_id: str,
    tenant_id: str,
    owner_id: str,
    using: str = "default",
    permission: DecisionPermission = DecisionPermission.DISPLAY_ONLY,
    ordinary_material: bool = False,
) -> dict[str, str]:
    """Publish the native Research graph, including its separate read grants."""
    now = timezone.now()
    end = now + timedelta(hours=1)
    tag = uuid4().hex
    output = (
        ArtifactRef(
            "research",
            "scenario_forecast",
            f"scenario-{tag}",
            "v1",
            sha256(f"scenario-forecast:{tag}:{plan.content_hash}".encode()).hexdigest(),
        )
        if ordinary_material
        else order_execution_output(order)
    )
    template = _spec()
    spec = EvidenceOperatorSpec.create(
        operator_id=f"order-op-{tag}",
        operator_version="v1",
        research_family=template.research_family,
        output_artifact_type=output.artifact_type,
        claim_kind=template.claim_kind,
        method_kind=template.method_kind,
        required_input_roles=template.required_input_roles,
        dependency_flags=frozenset(),
        maximum_permission=permission,
        requires_track_record=True,
        activated_at=now,
        valid_until=end,
    )
    ledger = _build_evidence_store(using=using)
    with ledger.atomic():
        ledger.append_operator_spec(spec, recorded_at=now)
    _activate_display_operator(spec, registrar_session, reviewer_session, using)
    now = timezone.now()
    track = replace(
        _track(),
        snapshot_id=f"track-{tag}",
        artifact=output,
        evaluated_at=now,
        valid_until=end,
        content_hash="",
    )
    observed = replace(_input("features", tag), artifact=order, valid_until=end)
    inputs = (
        observed,
        replace(observed, role="plan", artifact=plan),
        replace(observed, role="approval", artifact=plan_receipt),
    )
    if ordinary_material:
        # An ordinary, scoped Research publication about the plan. No knowledge of a future order.
        inputs = (replace(observed, artifact=plan),)
    envelope = resolve_evidence_envelope(
        output_artifact=output,
        operator_spec=spec,
        inputs=inputs,
        governance_state=GovernanceState.RESEARCH_ONLY,
        governance_grant=None,
        track_record=track,
        evaluated_at=now,
    )
    assert envelope.permission is DecisionPermission.DISPLAY_ONLY and envelope.must_not_execute
    with ledger.atomic():
        ledger.append_track_record(track, recorded_at=now)
        ledger.append_envelope(envelope, recorded_at=now)
    scopes = _build_evidence_scope_source_v1_store(using=using)
    with scopes.atomic():
        for ref in (
            replace(output, content_hash=envelope.content_hash),
            spec.artifact_ref,
            track.artifact_ref,
        ):
            selector = {
                "source_id": f"read-{uuid4().hex}",
                "owner_id": owner_id,
                "tenant_id": tenant_id,
                "account_id": account_id,
                "actor_id": f"django-user:{owner_user_id}",
                "artifact": ref,
            }
            claim = root_claim_hash_for_evidence_scope_source_v1(**selector)
            scopes.append_root(
                EvidenceScopeSourceV1(
                    **selector,
                    source_version="v1",
                    status="active",
                    recorded_at=now,
                    valid_until=end,
                    root_claim_hash=claim,
                )
            )

    return {**asdict(output), "envelope_content_hash": envelope.content_hash}


def _activate_display_operator(spec, registrar_session, reviewer_session, using):
    """Use the actual Risk subject/approval and Research activation use cases for this fixture."""
    from django.contrib.auth import get_user
    from django.test import RequestFactory

    from apps.research.application.evidence_operator_spec_approval_adapter import (
        ExternalOperatorSpecApprovalProjection,
        project_operator_spec_owner_approval,
    )
    from apps.research.application.evidence_operator_spec_lifecycle import (
        ActivateEvidenceOperatorSpecCommand,
    )
    from apps.research.evidence_operator_spec_lifecycle_composition import (
        build_django_evidence_operator_spec_runtime,
    )
    from apps.research.infrastructure.evidence_operator_spec_definition_provider import (
        DjangoEvidenceOperatorSpecDefinitionProvider,
    )
    from apps.risk_center.application.evidence_operator_spec_approval import (
        ApproveEvidenceOperatorSpecCommand,
        EvidenceOperatorSpecApprovalDefinition,
        RegisterEvidenceOperatorSpecApprovalSubjectCommand,
    )
    from apps.risk_center.evidence_operator_spec_approval_composition import (
        build_evidence_operator_spec_approval_write_runtime,
    )
    from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
        DjangoEvidenceOperatorSpecApprovalRepository,
    )

    definitions = DjangoEvidenceOperatorSpecDefinitionProvider(using=using)
    risk_ledger = DjangoEvidenceOperatorSpecApprovalRepository(using=using)

    class Definitions:
        def get_exact(self, **selectors):
            definition = definitions.get_exact(**selectors)
            if definition is None:
                return None
            return EvidenceOperatorSpecApprovalDefinition(
                spec.operator_id,
                spec.operator_version,
                definition.content_hash,
                definition.supersedes_activation_hash,
                spec.activated_at,
                spec.valid_until,
            )

    class Approvals:
        def get_exact(self, **selectors):
            found = risk_ledger.get_for_definition(**selectors)
            if found is None:
                return None
            keys = {k: v for k, v in selectors.items() if k != "as_of"}
            actual = ExternalOperatorSpecApprovalProjection(
                found.owner,
                found.capability,
                found.approval_id,
                found.approval_version,
                found.content_hash,
                found.subject.operator_id,
                found.subject.operator_version,
                found.subject.definition_hash,
                found.subject.supersedes_activation_hash,
                found.approved_by.actor_id,
                found.issued_at,
                found.valid_until,
            )
            return project_operator_spec_owner_approval(actual, **keys)

    def owner_commands(session):
        request = RequestFactory().post("/")
        request.session = session.session
        return build_evidence_operator_spec_approval_write_runtime(
            authenticated_user=get_user(request), definition_provider=Definitions(), using=using
        )

    reg = owner_commands(registrar_session)
    review = owner_commands(reviewer_session)
    subject_id = f"material-subject-{uuid4().hex}"
    approval_id = f"material-approval-{uuid4().hex}"
    reg.register_subject.execute(
        RegisterEvidenceOperatorSpecApprovalSubjectCommand(
            subject_id, "v1", spec.operator_id, spec.operator_version, timezone.now()
        )
    )
    approval = review.approve.execute(
        ApproveEvidenceOperatorSpecCommand(subject_id, "v1", approval_id, "v1", timezone.now())
    )
    activation = build_django_evidence_operator_spec_runtime(
        definition_provider=definitions, approval_query=Approvals(), using=using
    ).activate.execute(
        ActivateEvidenceOperatorSpecCommand(
            spec.operator_id, spec.operator_version, approval_id, "v1", timezone.now()
        )
    )
    assert activation.approval.owner_record_hash == approval.content_hash
