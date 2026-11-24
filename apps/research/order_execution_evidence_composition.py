"""Read display-only materials for a specific order through the scoped Research facade."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from django.db import connections
from django.utils import timezone

from apps.research.application.evidence_scope_source_v1_provider import (
    EvidenceScopeSourceV1Selector,
)
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    DecisionPermission,
    EvidenceBlockerCode,
    GovernanceState,
)
from apps.research.evidence_composition import (
    make_authorized_evidence_read_facade,
    read_evidence_scope_source_head,
)
from apps.research.infrastructure.evidence_models import (
    EvidenceEnvelopeModel,
    EvidenceScopeSourceV1Model,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
)


@dataclass(frozen=True, slots=True)
class OrderResearchEvidence:
    """Exact scoped display records shown to a human order reviewer."""

    output: ArtifactRef
    envelope_content_hash: str
    operator: ArtifactRef
    track: ArtifactRef
    activation_hash: str
    read_scope_hashes: tuple[str, ...]
    valid_until: datetime
    permission: str
    governance_state: str
    blockers: tuple[str, ...]
    owner_approval_id: str
    owner_approval_version: str
    owner_approval_hash: str
    operator_definition_hash: str
    linked_order_sources: tuple[ArtifactRef, ...]
    summary: dict[str, str | int | bool]


def order_execution_output(order: ArtifactRef) -> ArtifactRef:
    """Name Research's order evaluation and cryptographically bind its Broker input."""
    if order.owner != "broker_execution" or order.artifact_type != "live_order_approval_snapshot":
        raise ValueError("order evidence requires a formal Broker approval artifact")
    encoded = json.dumps(
        {"schema": "research.broker-order-review-material.v1", "order": order.to_payload()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ArtifactRef(
        "research",
        "broker_order_review_material",
        order.artifact_id,
        order.artifact_version,
        hashlib.sha256(encoded).hexdigest(),
    )


@dataclass(slots=True)
class _OwnerSelectors:
    using: str
    actor_id: str
    owner_id: str
    tenant_id: str
    account_id: str
    grants: list[tuple[str, datetime]] = field(default_factory=list)

    @property
    def unit_of_work_key(self) -> str:
        """Bind all reads to the caller's transaction alias."""
        return f"django:{self.using}"

    def get_selector(
        self, *, artifact: ArtifactRef, as_of: datetime
    ) -> EvidenceScopeSourceV1Selector | None:
        """Select a unique current immutable source for this exact actor and artifact."""
        chains = list(
            EvidenceScopeSourceV1Model._default_manager.using(self.using)
            .filter(
                actor_id=self.actor_id,
                owner_id=self.owner_id,
                tenant_id=self.tenant_id,
                account_id=self.account_id,
                artifact_owner=artifact.owner,
                artifact_type=artifact.artifact_type,
                artifact_id=artifact.artifact_id,
                artifact_version=artifact.artifact_version,
                artifact_content_hash=artifact.content_hash,
                recorded_at__lte=as_of,
            )
            .order_by()
            .values_list("source_id", flat=True)
            .distinct()[:2]
        )
        if len(chains) != 1:
            return None
        head = read_evidence_scope_source_head(source_id=chains[0], as_of=as_of, using=self.using)
        if (
            head is None
            or head.artifact != artifact
            or not head.is_current_at(as_of)
            or (head.actor_id, head.owner_id, head.tenant_id, head.account_id)
            != (self.actor_id, self.owner_id, self.tenant_id, self.account_id)
        ):
            return None
        self.grants.append((head.content_hash, head.valid_until))
        return EvidenceScopeSourceV1Selector(
            head.source_id,
            head.source_version,
            head.content_hash,
            self.owner_id,
            self.tenant_id,
            self.account_id,
            self.actor_id,
        )


def read_order_execution_evidence(
    *,
    order: ArtifactRef,
    plan: ArtifactRef,
    plan_receipt: ArtifactRef,
    selected_output: ArtifactRef | None = None,
    expected_envelope_hash: str | None = None,
    owner_user_id: int,
    owner_id: str,
    tenant_id: str,
    account_id: str,
    using: str,
) -> OrderResearchEvidence | None:
    """Fence source successors, authorize each read, then verify the display-only envelope and its exact lineage."""
    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        return None
    with db.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone()[0] != "read committed":
            return None
        cursor.execute(
            "LOCK TABLE research_evidence_scope_source_v1, research_evidence_envelope, research_evidence_operator_spec, research_evidence_track_record, research_evidence_operator_spec_approval, research_activated_evidence_operator_spec IN SHARE MODE NOWAIT"
        )
    return _read_fenced_evidence(
        order=order,
        plan=plan,
        plan_receipt=plan_receipt,
        selected_output=selected_output,
        expected_envelope_hash=expected_envelope_hash,
        owner_user_id=owner_user_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        account_id=account_id,
        using=using,
    )


def _read_fenced_evidence(
    *,
    order: ArtifactRef,
    plan: ArtifactRef,
    plan_receipt: ArtifactRef,
    selected_output: ArtifactRef | None = None,
    expected_envelope_hash: str | None = None,
    owner_user_id: int,
    owner_id: str,
    tenant_id: str,
    account_id: str,
    using: str,
) -> OrderResearchEvidence | None:
    if (selected_output is None) != (expected_envelope_hash is None):
        return None
    output = selected_output or order_execution_output(order)
    cutoff = timezone.now()
    envelope_hash = (
        EvidenceEnvelopeModel._default_manager.using(using)
        .filter(
            output_owner=output.owner,
            output_artifact_type=output.artifact_type,
            output_artifact_id=output.artifact_id,
            output_artifact_version=output.artifact_version,
            output_artifact_hash=output.content_hash,
            recorded_at__lte=cutoff,
        )
        .values_list("content_hash", flat=True)
        .first()
    )
    if envelope_hash is None or (
        expected_envelope_hash is not None and expected_envelope_hash != envelope_hash
    ):
        return None
    selectors = _OwnerSelectors(
        using, f"django-user:{owner_user_id}", owner_id, tenant_id, account_id
    )
    facade = make_authorized_evidence_read_facade(selector_provider=selectors, using=using)
    envelope = facade.get_envelope(
        output_owner=output.owner,
        output_artifact_type=output.artifact_type,
        output_artifact_id=output.artifact_id,
        output_artifact_version=output.artifact_version,
        expected_content_hash=envelope_hash,
        as_of=cutoff,
    )
    if (
        envelope is None
        or envelope.output_artifact != output
        or envelope.content_hash != envelope_hash
        or envelope.governance_state
        not in (GovernanceState.RESEARCH_ONLY, GovernanceState.PROMOTED)
        or envelope.permission is not DecisionPermission.DISPLAY_ONLY
        or not envelope.must_not_execute
        or set(envelope.blockers) - {EvidenceBlockerCode.OUTPUT_NOT_PROMOTED}
        or envelope.track_record_ref is None
    ):
        return None
    op = envelope.operator_spec_ref
    tr = envelope.track_record_ref
    operator = facade.get_operator_spec(
        operator_id=op.artifact_id,
        operator_version=op.artifact_version,
        expected_content_hash=op.content_hash,
        as_of=cutoff,
    )
    track = facade.get_track_record(
        snapshot_id=tr.artifact_id,
        snapshot_version=tr.artifact_version,
        expected_content_hash=tr.content_hash,
        as_of=cutoff,
    )
    if (
        operator is None
        or operator.artifact_ref != op
        or operator.output_artifact_type != output.artifact_type
        or track is None
        or track.artifact_ref != tr
        or track.artifact != output
        or track.drift_detected
        or track.resolved <= 0
        or track.n_eff <= 0
        or track.coverage <= 0
    ):
        return None
    anchors = {order, plan, plan_receipt}
    linked = tuple(sorted(anchors.intersection(envelope.lineage)))
    if not linked or (selected_output is None and set(linked) != anchors):
        return None
    if (
        operator.maximum_permission != DecisionPermission.DISPLAY_ONLY
        or (operator.claim_kind, operator.method_kind, operator.research_family)
        != (envelope.claim_kind, envelope.method_kind, envelope.research_family)
        or not {
            op,
            tr,
            track.promotion_ref,
            *track.outcome_refs,
        }.issubset(envelope.lineage)
    ):
        return None
    active = DjangoEvidenceOperatorSpecLifecycleRepository(using=using).get_active(
        operator_id=op.artifact_id, as_of=cutoff
    )
    if active.definition.operator_spec != operator or len(selectors.grants) != 3:
        return None
    deadline = min(
        envelope.valid_until,
        track.valid_until,
        operator.valid_until,
        active.approval.valid_until,
        *(end for _, end in selectors.grants),
    )
    if deadline <= timezone.now():
        return None
    return OrderResearchEvidence(
        output,
        envelope_hash,
        op,
        tr,
        active.content_hash,
        tuple(h for h, _ in selectors.grants),
        deadline,
        envelope.permission.value,
        envelope.governance_state.value,
        tuple(code.value for code in envelope.blockers),
        active.approval.owner_record_id,
        active.approval.owner_record_version,
        active.approval.owner_record_hash,
        active.definition.content_hash,
        linked,
        {
            "claim": envelope.claim_kind.value,
            "method": envelope.method_kind.value,
            "family": envelope.research_family,
            "evaluated_at": envelope.evaluated_at.isoformat(),
            "valid_until": envelope.valid_until.isoformat(),
            "track_target": track.target,
            "track_horizon": track.horizon,
            "eligible": track.eligible,
            "resolved": track.resolved,
            "coverage": str(track.coverage),
            "effective_sample": str(track.n_eff),
            "drift_detected": track.drift_detected,
        },
    )
