"""Read accepted local tax debts from complete original assessment/journal/Audit chains.

Zero means the local accepted tax ledger is empty or fully collected. It does
not establish undisclosed-event coverage, statutory freshness or price marks.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

from django.db import connections, models
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    DjangoRetainedTaxAssessmentAuditVerifier,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityScope
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    recorded_id,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_readback import (
    DjangoTaxLiabilityReadback,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError


def _corrupt(message: str) -> BusinessLogicError:
    """Reject incomplete or inconsistent accepted local tax evidence."""
    return BusinessLogicError(message, code="TAX_LEDGER_CORRUPT")


def _scope(header: Header) -> TaxLiabilityScope:
    """Restore the exact disposition selector, retaining the physical account and owner."""
    return TaxLiabilityScope(
        account_id=header.account_id,
        owner_user_id=header.owner_user_id,
        security_id=header.security_id,
        asset_code=header.asset_code,
        corporate_action_id=header.corporate_action_id,
        source_namespace=header.source_namespace,
        logical_source_event_id=header.source_event_id,
        target_disposition_id=header.disposition_id,
        record_date=header.record_date,
        target_settlement_date=header.settlement_date,
    )


def _head(headers: list[Header]) -> Header:
    """Require one complete unbranched assessment lineage within the exact disposition."""
    by_id = {recorded_id(row): row for row in headers}
    predecessors: set[int] = set()
    roots = 0
    for row in headers:
        parent_id = row.supersedes_id
        if parent_id is None:
            roots += 1
            if row.supersedes_assessment_revision_id is not None:
                raise _corrupt("Tax assessment root has a contradictory predecessor")
        else:
            parent = by_id.get(parent_id)
            if (
                type(parent_id) is not int
                or parent is None
                or parent_id in predecessors
                or row.supersedes_assessment_revision_id != parent.assessment_revision_id
                or row.recorded_at < parent.recorded_at
                or recorded_id(row) <= recorded_id(parent)
            ):
                raise _corrupt("Tax assessment lineage is incomplete or branched")
            predecessors.add(parent_id)
    heads = [row for row in headers if recorded_id(row) not in predecessors]
    if roots != 1 or len(heads) != 1 or len(predecessors) != len(headers) - 1:
        raise _corrupt("Tax assessment has no unique complete current head")
    return heads[0]


def read_locked_corporate_action_tax_payable(
    *, account: SimulatedAccountModel, using: str, as_of: datetime | None = None
) -> Decimal:
    """Return all original unpaid taxes under the physical account serialization fence.

    New or superseding unapplied assessments block new cash admission. All
    independent disposition chains and their exact original Audit/Outbox pairs
    are re-read; current tax permission is neither required nor issued by a
    historical debt read. The caller keeps ownership of its outer transaction.
    """
    connection = connections[using]
    if (
        not connection.in_atomic_block
        or connection.get_autocommit()
        or type(account.pk) is not int
        or type(account.user_id) is not int
        or account.account_type != "simulated"
        or account._state.db != using
    ):
        raise BusinessLogicError(
            "Tax balance requires the owned account transaction", code="TAX_BALANCE_SCOPE_BLOCKED"
        )
    locked = (
        SimulatedAccountModel._default_manager.using(using).select_for_update().get(pk=account.pk)
    )
    if (
        locked.user_id != account.user_id
        or locked.account_type != account.account_type
        or locked.current_cash != account.current_cash
        or locked.updated_at != account.updated_at
    ):
        raise _corrupt("Tax balance owner differs from the locked physical account")
    cutoff = timezone.now() if as_of is None else as_of
    if type(cutoff) is not datetime or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise _corrupt("Tax balance cutoff must be timezone-aware")
    headers = tuple(
        Header._default_manager.using(using)
        .select_for_update()
        .filter(account_id=account.pk)
        .order_by("pk")
    )
    operations = tuple(
        Operation._default_manager.using(using)
        .select_for_update()
        .filter(account_id=account.pk)
        .order_by("scope_sha256", "sequence")
    )
    if not headers and not operations:
        return Decimal("0")
    grouped: dict[str, list[Header]] = {}
    scopes: dict[str, TaxLiabilityScope] = {}
    for header in headers:
        if header.owner_user_id != account.user_id or header.recorded_at > cutoff:
            raise _corrupt("Tax assessment is outside the current owned local ledger")
        scope = _scope(header)
        key = tax_liability_scope_sha256(scope)
        grouped.setdefault(key, []).append(header)
        scopes[key] = scope
    operations_by_scope: dict[str, list[Operation]] = {}
    for row in operations:
        if row.scope_sha256 not in grouped or row.owner_user_id != account.user_id:
            raise _corrupt("Tax operation has no exact owned assessment scope")
        operations_by_scope.setdefault(row.scope_sha256, []).append(row)
    field = SimulatedAccountModel._meta.get_field("current_cash")
    if not isinstance(field, models.DecimalField) or field.decimal_places is None:
        raise _corrupt("Tax balance has no exact physical cash precision")
    quantum = Decimal(1).scaleb(-field.decimal_places)
    audit = build_tax_assessment_audit_coordinator(using=using)
    readback = DjangoTaxLiabilityReadback(
        using=using,
        audit=audit,
        assessment_audit=DjangoRetainedTaxAssessmentAuditVerifier(audit=audit),
    )
    total = Decimal("0")
    with audit.caller_owned_readonly(), localcontext() as context:
        context.prec = 96
        for key in sorted(grouped):
            for header in grouped[key]:
                readback.verify_assessment(header, as_of=cutoff)
            head = _head(grouped[key])
            retained = operations_by_scope.get(key)
            if not retained:
                raise BusinessLogicError(
                    "Tax assessment has not been applied to its financial ledger",
                    code="TAX_ASSESSMENT_NOT_APPLIED",
                )
            first = retained[0]
            chain = readback.read_chain(
                scope=scopes[key],
                canonical_account_namespace=first.canonical_account_namespace,
                canonical_account_id=first.canonical_account_id,
                currency=SimulatedDividendTaxCurrency.CNY,
                as_of=cutoff,
            )
            if not chain or len(chain) != len(retained):
                raise _corrupt("Tax financial chain is incomplete")
            last = chain[-1]
            if last.material.assessment_id != head.pk:
                raise BusinessLogicError(
                    "The current tax assessment has not been applied",
                    code="TAX_ASSESSMENT_NOT_APPLIED",
                )
            state = last.material.transition.state_after
            if state.currency_quantum != quantum:
                raise _corrupt("Tax currency precision differs from the cash ledger")
            if (
                audit.get_current_head_targeted(
                    stream_id=last.event.stream_id, as_of=cutoff, scope=last.event.scope, lock=True
                )
                != last.event
            ):
                raise _corrupt("Tax Audit has an unbound financial successor")
            total += state.outstanding_amount
    return total
