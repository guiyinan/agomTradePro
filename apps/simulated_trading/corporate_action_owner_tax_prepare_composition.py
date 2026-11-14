"""Prepare an exact current disposition while preserving the retained assessment lineage."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import date
from uuid import uuid4

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionOperation,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    DjangoRetainedTaxAssessmentAuditVerifier,
)
from apps.simulated_trading.corporate_action_owner_execution_composition import (
    DeferredOwnerTaxQualification,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    DjangoCorporateActionTaxAssessmentRepository,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_balance_repository import _head
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import AuthorizationError, BusinessLogicError


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionTaxPreview:
    """One fully rebuilt preview; it never appends or recognizes tax automatically."""

    assessment: CorporateActionTaxAssessment
    corrects_existing_assessment: bool


def prepare_owner_corporate_action_tax_assessment(
    *,
    action: QualifiedCorporateActionTaxFacts,
    operation: OwnerCorporateActionOperation,
    canonical_account_id: str,
    settlement_date: date,
    environment: str,
) -> OwnerCorporateActionTaxPreview:
    """Require a user-selected date and reuse the exact existing disposition revision.

    A changed assessment is an explicit previewed successor only for assess.
    Recognition and collection require the retained current semantic facts;
    neither may silently assess, choose a latest sale or create another chain.
    An established caller transaction owns this read; no nested savepoint is
    opened before the original read-only Audit/Outbox verification.
    """
    if (
        operation not in {"tax_assess", "tax_recognize", "tax_collect"}
        or type(settlement_date) is not date
    ):
        raise ValueError("tax preparation requires an exact operation and settlement date")
    using = DEFAULT_DB_ALIAS
    candidate = (
        DeferredOwnerTaxQualification(environment=environment)
        .build_provider(
            account_id=action.account_id, owner_user_id=action.owner_user_id, as_of=timezone.now()
        )
        .prepare_current(
            action=action,
            canonical_account_id=canonical_account_id,
            target_settlement_date=settlement_date,
            assessment_revision_id=f"owner-assessment-{uuid4().hex}",
            supersedes_assessment_revision_id=None,
        )
    )
    scope = nullcontext() if connections[using].in_atomic_block else transaction.atomic(using=using)
    with scope:
        account = (
            SimulatedAccountModel._base_manager.using(using)
            .select_for_update()
            .filter(
                pk=action.account_id,
                user_id=action.owner_user_id,
                account_type="simulated",
                is_active=True,
            )
            .first()
        )
        if account is None:
            raise AuthorizationError("仅可核对本人启用中的模拟账户。")
        rows = list(
            Header._base_manager.using(using)
            .select_for_update()
            .filter(
                account_id=action.account_id,
                idempotency_key=candidate.calculation.idempotency_key,
            )
            .order_by("pk")
        )
        if not rows:
            if operation != "tax_assess":
                raise BusinessLogicError(
                    "请先评估这笔卖出的模拟税额。", code="CORPORATE_ACTION_TAX_ASSESS_FIRST"
                )
            return OwnerCorporateActionTaxPreview(candidate, False)
        repository = DjangoCorporateActionTaxAssessmentRepository(using=using)
        audit = build_tax_assessment_audit_coordinator(using=using)
        historical_audit = DjangoRetainedTaxAssessmentAuditVerifier(audit=audit)
        cutoff = timezone.now()
        with audit.caller_owned_readonly():
            for row in rows:
                repository.verify_retained_integrity(row)
                historical_audit.verify_original(row, as_of=cutoff)
        head = _head(rows)
        if head.owner_user_id != action.owner_user_id or head.recorded_at > cutoff:
            raise BusinessLogicError(
                "税务评估所属账户或时间无法核对。", code="TAX_ASSESSMENT_EVIDENCE_INVALID"
            )
        if head.semantic_sha256 == candidate.semantic_sha256:
            retained = replace(
                candidate,
                assessment_revision_id=head.assessment_revision_id,
                supersedes_assessment_revision_id=head.supersedes_assessment_revision_id,
            )
            repository.verify_stored(head, retained)
            return OwnerCorporateActionTaxPreview(retained, False)
        if operation != "tax_assess":
            raise BusinessLogicError(
                "来源或税务事实已变化，请先核对新的评估。",
                code="CORPORATE_ACTION_TAX_REASSESS_REQUIRED",
            )
        return OwnerCorporateActionTaxPreview(
            replace(candidate, supersedes_assessment_revision_id=head.assessment_revision_id), True
        )
