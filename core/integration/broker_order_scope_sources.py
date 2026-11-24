"""Assemble independently fenced Account, Portfolio and Research facts for one Broker mandate."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.request import Request

from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.broker_execution.application.order_scope_sources import (
    OrderArtifactRef,
    OrderBenchmarkPin,
    OrderMaterialSelector,
    OrderReviewMaterials,
    OrderScopeOwner,
    OrderScopeSources,
)


class _ScopeSources:
    def signer(
        self, *, request: Request, using: str, before_commit: Callable[[], None]
    ) -> AbstractContextManager[User]:
        """Return Account's session-only credential lock with the caller's final expiry check."""
        from apps.account.live_account_owner_composition import locked_account_owner_session

        return locked_account_owner_session(
            request=request, using=using, before_commit=before_commit
        )

    def owner(
        self, *, account_namespace: str, account_id: str, owner_user_id: int, using: str
    ) -> OrderScopeOwner | None:
        """Bind the actual physical real account, policy and current staff role."""
        from apps.account.live_account_owner_composition import (
            read_current_order_owner_role,
            read_live_account_owner,
        )

        owner = read_live_account_owner(
            account_namespace=account_namespace,
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
        )
        if owner is None:
            return None
        role = read_current_order_owner_role(owner_user_id=owner_user_id, using=using)
        if role is None:
            return None
        return OrderScopeOwner(**asdict(owner), role=role)

    def materials(
        self,
        *,
        intent: BrokerCheckpointIntent,
        owner: OrderScopeOwner,
        pin: OrderBenchmarkPin | None,
        selection: OrderMaterialSelector | None,
        using: str,
    ) -> OrderReviewMaterials | None:
        """Re-read the approved plan and benchmark; Research supplies only scoped display material."""
        from apps.portfolio.benchmark_execution_composition import (
            read_current_benchmark_approval,
            select_current_benchmark_approval,
        )
        from apps.portfolio.transition_plan_checkpoint_composition import (
            read_locked_transition_order,
        )
        from apps.research.domain.evidence_contracts import ArtifactRef
        from apps.research.order_execution_evidence_composition import read_order_execution_evidence

        plan, order = intent.sources.plan, intent.sources.order
        row, receipt = read_locked_transition_order(
            plan_id=intent.plan_id,
            plan_version=intent.plan_version,
            ordinal=intent.plan_order_ordinal,
            receipt_id=plan.portfolio_receipt_id,
            receipt_version=plan.portfolio_receipt_version,
            using=using,
            as_of=timezone.now(),
        )
        if (row.content_hash, row.account_id, row.order_content_hash, row.valid_until) != (
            plan.portfolio_plan_content_hash,
            plan.portfolio_account_id,
            plan.plan_order_content_hash,
            plan.portfolio_plan_valid_until,
        ) or (
            receipt.plan_id,
            receipt.plan_version,
            receipt.plan_content_hash,
            receipt.account_id,
            receipt.subject_id,
            receipt.subject_version,
            receipt.subject_content_hash,
            receipt.content_hash,
            receipt.valid_until,
        ) != (
            intent.plan_id,
            intent.plan_version,
            row.content_hash,
            row.account_id,
            plan.portfolio_subject_id,
            plan.portfolio_subject_version,
            plan.portfolio_subject_content_hash,
            plan.portfolio_receipt_content_hash,
            plan.portfolio_receipt_valid_until,
        ):
            return None
        if pin is None:
            benchmark = select_current_benchmark_approval(
                account_namespace=owner.account_namespace,
                account_id=owner.account_id,
                owner_user_id=owner.owner_user_id,
                tenant_id=owner.tenant_id,
                owner_id=owner.owner_id,
                using=using,
            )
        else:
            benchmark = read_current_benchmark_approval(
                approval_id=pin.approval_id,
                expected_version=pin.approval_version,
                expected_content_hash=pin.content_hash,
                account_namespace=owner.account_namespace,
                account_id=owner.account_id,
                owner_user_id=owner.owner_user_id,
                tenant_id=owner.tenant_id,
                owner_id=owner.owner_id,
                using=using,
            )
        if benchmark is None:
            return None
        research = read_order_execution_evidence(
            selected_output=None if selection is None else ArtifactRef(**asdict(selection.output)),
            expected_envelope_hash=None if selection is None else selection.envelope_content_hash,
            order=ArtifactRef(
                order.owner,
                order.artifact_type,
                order.artifact_id,
                order.artifact_version,
                order.content_hash,
            ),
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
            owner_user_id=owner.owner_user_id,
            owner_id=owner.owner_id,
            tenant_id=owner.tenant_id,
            account_id=owner.account_id,
            using=using,
        )
        from apps.risk_center.evidence_operator_spec_approval_composition import (
            current_order_material_spec_approval,
        )

        if (
            research is None
            or research.permission != "display_only"
            or not current_order_material_spec_approval(
                approval_id=research.owner_approval_id,
                approval_version=research.owner_approval_version,
                expected_content_hash=research.owner_approval_hash,
                operator_id=research.operator.artifact_id,
                operator_version=research.operator.artifact_version,
                definition_hash=research.operator_definition_hash,
                as_of=timezone.now(),
                using=using,
            )
        ):
            return None
        return OrderReviewMaterials(
            OrderBenchmarkPin(
                benchmark.approval_id, benchmark.approval_version, benchmark.content_hash
            ),
            OrderArtifactRef(**asdict(research.output)),
            research.envelope_content_hash,
            OrderArtifactRef(**asdict(research.operator)),
            OrderArtifactRef(**asdict(research.track)),
            research.activation_hash,
            research.read_scope_hashes,
            research.permission,
            research.governance_state,
            research.blockers,
            tuple(OrderArtifactRef(**asdict(ref)) for ref in research.linked_order_sources),
            research.summary,
            min(research.valid_until, benchmark.valid_until),
        )


def build_order_scope_sources() -> OrderScopeSources:
    """Provide only the registered production owner readers."""
    return _ScopeSources()
