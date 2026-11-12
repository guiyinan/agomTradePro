"""Same-transaction cash, immutable financial journal and Audit/Outbox writer."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext

from django.db import connections, models

from apps.audit.corporate_action_tax_assessment_composition import TaxAssessmentAuditCoordinatorPort
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
    TaxAssessmentClockPort,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityAppendDisposition,
    TaxLiabilityCurrentState,
    TaxLiabilityEvidenceReference,
    TaxLiabilityFinancialSnapshot,
    TaxLiabilityWriteLease,
    TaxLiabilityWriteReceipt,
    _aware,
    _blocked,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    AuditedTaxLiabilityScopeVerifierPort,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityTransition,
    TaxLiabilityCashAction,
    TaxLiabilityOperationIdentity,
    TaxLiabilityScope,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    DjangoCorporateActionTaxAssessmentRepository,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    build_tax_liability_audit_event,
    tax_liability_audit_stream_id,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    canonical_liability_json,
    encode_liability_state,
    encode_liability_transition,
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_evidence import (
    TaxLiabilityOperationMaterial,
    _decimal,
    _instant,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    _claim_tax_liability_insert,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_readback import (
    DjangoTaxLiabilityReadback,
    RetainedTaxAssessmentAuditVerifierPort,
    VerifiedTaxLiabilityOperation,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    active_order_reservation_holds,
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    try_acquire_scoped_advisory_exclusive,
)


def require_ledger_cash_capacity(amount: Decimal, *, currency_quantum: Decimal) -> None:
    """Reject unsupported configured quantum, negative cash or implicit DB rounding."""
    field = SimulatedAccountModel._meta.get_field("current_cash")
    if (
        not isinstance(field, models.DecimalField)
        or field.decimal_places is None
        or field.max_digits is None
    ):
        raise _blocked("The cash ledger has no explicit exact decimal capacity")
    quantum = Decimal(1).scaleb(-field.decimal_places)
    if (
        currency_quantum != quantum
        or type(amount) is not Decimal
        or not amount.is_finite()
        or amount < 0
    ):
        raise _blocked("Configured tax currency precision is unsupported by the cash ledger")
    try:
        with localcontext() as context:
            context.prec = max(field.max_digits + 2, 80)
            if amount.quantize(quantum) != amount or amount >= Decimal(10) ** (
                field.max_digits - field.decimal_places
            ):
                raise _blocked("Tax cash movement exceeds exact ledger capacity")
    except InvalidOperation as error:
        raise _blocked("Tax cash movement cannot be represented exactly") from error


class DjangoTaxLiabilityAtomicWriter:
    """An ephemeral writer bound to one private UOW token and live verifier context."""

    def __init__(
        self,
        *,
        using: str,
        token: object,
        verifier: AuditedTaxLiabilityScopeVerifierPort,
        audit: TaxAssessmentAuditCoordinatorPort,
        clock: TaxAssessmentClockPort,
        assessment_audit: RetainedTaxAssessmentAuditVerifierPort,
    ) -> None:
        """Require same-alias live scope and existing public Audit capabilities."""
        if verifier.database_alias != using or audit.database_alias != using:
            raise _blocked("Financial cash, authority and Audit must share one alias")
        self._using, self._token, self._verifier = using, token, verifier
        self._audit, self._clock = audit, clock
        self._readback = DjangoTaxLiabilityReadback(
            using=using, audit=audit, assessment_audit=assessment_audit
        )
        self._assessments = DjangoCorporateActionTaxAssessmentRepository(using=using)
        self._slot: tuple[str, TaxLiabilityScope, str, str, SimulatedDividendTaxCurrency] | None = (
            None
        )
        self._snapshot: TaxLiabilityFinancialSnapshot | None = None
        self._snapshot_provenance_json: str | None = None
        self._closed = False

    def close(self) -> None:
        """Revoke the writer immediately when its caller-owned UOW exits."""
        self._closed = True

    def _require_active(self) -> None:
        """Reject retained writer instances and any call outside actual locked authority."""
        if self._closed or not connections[self._using].in_atomic_block:
            raise _blocked("Financial writer is outside its active atomic UOW")
        origin = self._verifier.get_locked_audit_origin()
        origin.__post_init__()
        origin.lease.assert_live(as_of=self._clock.now())

    def _account(self, scope: TaxLiabilityScope) -> SimulatedAccountModel:
        """Lock and validate actual simulated known cash, never a caller-supplied balance."""
        self._require_active()
        row = (
            SimulatedAccountModel.objects.using(self._using)
            .select_for_update()
            .filter(pk=scope.account_id)
            .first()
        )
        if (
            row is None
            or row.user_id != scope.owner_user_id
            or row.account_type != "simulated"
            or not row.is_active
            or row.cash_known is not True
            or row.cash_reconciliation_status != "simulated_ledger"
        ):
            raise _blocked("Exact active simulated owner ledger with known cash is required")
        require_ledger_cash_capacity(
            row.current_cash,
            currency_quantum=self._verifier.get_locked_audit_origin().lease.currency_quantum,
        )
        return row

    def require_stored_assessment(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
    ) -> TaxAssessmentWriteReceipt:
        """Read exact original assessment evidence without appending or repairing it."""
        self._require_active()
        origin = self._verifier.get_locked_audit_origin()
        origin.verify_for(
            assessment,
            actor_user_id=actor_user_id,
            operation_id=origin.lease.operation_id,
            cash_action=origin.lease.cash_action,
            using=self._using,
            as_of=self._clock.now(),
        )
        header = (
            Header._default_manager.using(self._using)
            .select_for_update()
            .filter(
                account_id=assessment.account_id,
                assessment_revision_id=assessment.assessment_revision_id,
                idempotency_key=assessment.calculation.idempotency_key,
                semantic_sha256=assessment.semantic_sha256,
            )
            .first()
        )
        if header is None:
            raise _blocked(
                "The original audited assessment must exist before financial recognition"
            )
        self._assessments.verify_stored(header, assessment)
        self._readback.verify_assessment(header, as_of=self._clock.now())
        return TaxAssessmentWriteReceipt(
            TaxAssessmentAppendDisposition.EXACT_RETRY,
            header.assessment_revision_id,
            header.semantic_sha256,
            header.observation_manifest_sha256,
        )

    def lock_operation_and_state(
        self,
        *,
        operation_id: str,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> None:
        """Serialize absent operation slots and disposition heads after the owner row."""
        self._account(scope)
        lease = self._verifier.get_locked_audit_origin().lease
        if (operation_id, scope, canonical_account_namespace, canonical_account_id, currency) != (
            lease.operation_id,
            lease.scope,
            lease.canonical_account_namespace,
            lease.canonical_account_id,
            lease.currency,
        ):
            raise _blocked("Financial lock selector differs from current exact authority")
        if self._slot is not None:
            raise _blocked("One UOW can hold only one immutable financial operation")
        try_acquire_scoped_advisory_exclusive(
            using=self._using,
            keys=(
                ScopedAdvisoryLockKey(
                    "simulated-tax-operation", (str(scope.account_id), operation_id)
                ),
                ScopedAdvisoryLockKey(
                    "simulated-tax-state",
                    (str(scope.account_id), tax_liability_scope_sha256(scope)),
                ),
            ),
        )
        self._slot = (
            operation_id,
            scope,
            canonical_account_namespace,
            canonical_account_id,
            currency,
        )

    def _chain(self) -> tuple[VerifiedTaxLiabilityOperation, ...]:
        """Read the full original chain only for the exact active locked slot."""
        self._require_active()
        if self._slot is None:
            raise _blocked("Financial operation/state locks must precede readback")
        _, scope, namespace, account, currency = self._slot
        return self._readback.read_chain(
            scope=scope,
            canonical_account_namespace=namespace,
            canonical_account_id=account,
            currency=currency,
            as_of=self._clock.now(),
        )

    def get_operation(self, *, operation_id: str) -> TaxLiabilityWriteReceipt | None:
        """Return exact original evidence, blocking same operation IDs in another scope."""
        chain = self._chain()
        assert self._slot is not None
        if operation_id != self._slot[0]:
            raise _blocked("Requested financial replay differs from the locked operation")
        matches = [entry for entry in chain if entry.material.identity.operation_id == operation_id]
        if matches:
            return replace(
                matches[0].receipt, disposition=TaxLiabilityAppendDisposition.EXACT_RETRY
            )
        if (
            Operation._default_manager.using(self._using)
            .filter(account_id=self._slot[1].account_id, operation_id=operation_id)
            .exists()
        ):
            raise _blocked("Financial operation ID already belongs to another disposition")
        return None

    def read_current_state(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> TaxLiabilityCurrentState | None:
        """Return the complete verified current state with its original last receipt."""
        if self._slot is None or self._slot[1:] != (
            scope,
            canonical_account_namespace,
            canonical_account_id,
            currency,
        ):
            raise _blocked("Current state read differs from the locked financial scope")
        chain = self._chain()
        if not chain:
            return None
        last = chain[-1]
        return TaxLiabilityCurrentState(
            last.material.transition.state_after,
            canonical_account_namespace,
            canonical_account_id,
            currency,
            last.material.identity.stored_assessment_manifest_sha256,
            last.receipt,
        )

    def read_financial_snapshot(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> TaxLiabilityFinancialSnapshot:
        """Read actual known cash and all independently validated active order holds."""
        if self._slot is None or self._slot[1:] != (
            scope,
            canonical_account_namespace,
            canonical_account_id,
            currency,
        ):
            raise _blocked("Financial cash read differs from the exact locked scope")
        account = self._account(scope)
        rows = lock_active_order_reservations(account_id=scope.account_id, using=self._using)
        held, _ = active_order_reservation_holds(
            rows,
            account_id=scope.account_id,
            owner_user_id=scope.owner_user_id,
            security_id=scope.security_id,
            asset_code=scope.asset_code,
        )
        observed_at = _aware(self._clock.now(), field_name="financial snapshot server clock")
        payload = canonical_liability_json(
            {
                "schema": "simulated-tax-cash-snapshot.v1",
                "account_id": scope.account_id,
                "owner_user_id": scope.owner_user_id,
                "canonical_account_namespace": canonical_account_namespace,
                "canonical_account_id": canonical_account_id,
                "currency": currency.value,
                "scope_sha256": tax_liability_scope_sha256(scope),
                "book_cash": _decimal(account.current_cash),
                "reserved_cash": _decimal(held),
                "physical_updated_at": _instant(account.updated_at),
                "observed_at": _instant(observed_at),
                "active_holds": [
                    {
                        "id": row.pk,
                        "key": row.idempotency_key,
                        "request_sha256": row.reservation_request_hash,
                        "updated_at": _instant(row.updated_at),
                    }
                    for row in rows
                ],
            }
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        snapshot = TaxLiabilityFinancialSnapshot(
            scope.account_id,
            scope.owner_user_id,
            scope,
            canonical_account_namespace,
            canonical_account_id,
            currency,
            account.current_cash,
            held,
            TaxLiabilityEvidenceReference(f"tax-cash-snapshot:{digest}", "v1", digest),
            observed_at,
        )
        snapshot.verify_for(self._verifier.get_locked_audit_origin().lease, as_of=observed_at)
        self._snapshot = snapshot
        self._snapshot_provenance_json = payload
        return snapshot

    def append_transition(
        self,
        assessment: CorporateActionTaxAssessment,
        transition: CorporateActionTaxLiabilityTransition,
        *,
        actor_user_id: int,
        stored_assessment: TaxAssessmentWriteReceipt,
        lease: TaxLiabilityWriteLease,
        operation_id: str,
        operation_request_sha256: str,
        expected_prior_state_sha256: str | None,
        cash_action: TaxLiabilityCashAction | None,
        cash_snapshot: TaxLiabilityFinancialSnapshot | None,
    ) -> TaxLiabilityWriteReceipt:
        """Write exact cash/state/journal/Audit/Outbox or roll back the entire UOW."""
        chain = self._chain()
        prior = chain[-1] if chain else None
        origin = self._verifier.get_locked_audit_origin()
        now = _aware(self._clock.now(), field_name="financial operation server clock")
        origin.verify_for(
            assessment,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            cash_action=cash_action,
            using=self._using,
            as_of=now,
        )
        if (
            origin.write_mode != "append"
            or origin.lease != lease
            or self._slot is None
            or self._slot[0] != operation_id
        ):
            raise _blocked("A verified original retry cannot authorize any new financial append")
        transition.verify_integrity()
        expected_state = None if prior is None else prior.material.transition.state_after
        if (
            expected_prior_state_sha256
            != (None if expected_state is None else expected_state.state_sha256)
            or transition.before_state != expected_state
        ):
            raise _blocked("Financial liability head changed before append")
        if transition != plan_corporate_action_tax_liability(
            assessment, prior_state=expected_state, cash_request=transition.cash_request
        ):
            raise _blocked("Financial transition differs from independent exact Domain planning")
        if cash_snapshot != self._snapshot or (cash_action is None) != (cash_snapshot is None):
            raise _blocked("Financial append must retain its exact server-read cash snapshot")
        account = self._account(lease.scope)
        if account.updated_at != origin.source_row_updated_at or (
            cash_snapshot is not None and account.current_cash != cash_snapshot.book_cash
        ):
            raise _blocked("Physical account no longer matches locked current source facts")
        identity = TaxLiabilityOperationIdentity(
            operation_id,
            lease.scope,
            lease.canonical_account_namespace,
            lease.canonical_account_id,
            lease.currency,
            assessment.assessment_revision_id,
            assessment.supersedes_assessment_revision_id,
            assessment.semantic_sha256,
            stored_assessment.observation_manifest_sha256,
            cash_action,
        )
        if (
            identity.request_sha256 != operation_request_sha256
            or transition.state_after.scope != lease.scope
            or transition.state_after.assessment_semantic_sha256 != assessment.semantic_sha256
            or transition.state_after.assessed_amount != assessment.calculation.withholding_amount
        ):
            raise _blocked(
                "Financial append intent or assessed amount differs from exact assessment"
            )
        with localcontext() as context:
            context.prec = 80
            cash_after = account.current_cash + transition.cash_delta
        require_ledger_cash_capacity(cash_after, currency_quantum=lease.currency_quantum)
        changed = transition.cash_delta != 0 or transition.outstanding_delta != 0
        material = TaxLiabilityOperationMaterial(
            assessment_id=self._assessment_id(assessment),
            identity=identity,
            transition=transition,
            sequence=len(chain) + 1,
            predecessor_operation_sha256=None if prior is None else prior.row.operation_sha256,
            origin=origin,
            cash_snapshot=cash_snapshot,
            cash_before=account.current_cash,
            cash_after=cash_after,
            physical_updated_before=account.updated_at,
            physical_updated_after=now if changed else account.updated_at,
            recorded_at=now,
            cash_snapshot_provenance_json=self._snapshot_provenance_json,
        )
        event = build_tax_liability_audit_event(
            material, predecessor_hash=None if prior is None else prior.event.content_hash
        )
        self._audit.lock_streams((tax_liability_audit_stream_id(identity),))
        winner = self._audit.get_winner_targeted(
            event_id=event.event_id, event_version=event.event_version, as_of=now, lock=True
        )
        head = self._audit.get_current_head_targeted(
            stream_id=event.stream_id, as_of=now, scope=origin.scope, lock=True
        )
        if (
            winner is not None
            or head != (None if prior is None else prior.event)
            or self._audit.get_exact_outbox_winner_targeted(event) is not None
        ):
            raise _blocked("Orphan financial Audit/Outbox evidence cannot be repaired or rebound")
        if changed:
            updated = (
                SimulatedAccountModel.objects.using(self._using)
                .filter(
                    pk=account.pk,
                    user_id=actor_user_id,
                    account_type="simulated",
                    is_active=True,
                    cash_known=True,
                    cash_reconciliation_status="simulated_ledger",
                    current_cash=account.current_cash,
                    updated_at=account.updated_at,
                )
                .update(current_cash=cash_after, updated_at=now)
            )
            if updated != 1:
                raise _blocked("Physical financial compare-and-swap failed")
        commit = self._audit.append_and_enqueue_targeted(
            event,
            expected_predecessor_hash=event.predecessor_hash,
            recorded_at=now,
            scope=origin.scope,
            identity_winner=None,
            stream_head=head,
        )
        outbox = self._audit.get_exact_outbox_winner_targeted(event)
        if commit.event != event or outbox is None or outbox.event != event:
            raise _blocked("Financial write did not retain exact original Audit/Outbox")
        state = transition.state_after
        row = Operation(
            account_id=lease.physical_account_id,
            owner_user_id=lease.owner_user_id,
            assessment_id=material.assessment_id,
            operation_id=operation_id,
            operation_request_sha256=identity.request_sha256,
            scope_sha256=tax_liability_scope_sha256(lease.scope),
            sequence=material.sequence,
            predecessor_id=None if prior is None else prior.row.pk,
            canonical_account_namespace=lease.canonical_account_namespace,
            canonical_account_id=lease.canonical_account_id,
            currency=lease.currency.value,
            state_payload_json=encode_liability_state(state),
            state_sha256=state.state_sha256,
            transition_payload_json=encode_liability_transition(transition),
            transition_sha256=transition.transition_sha256,
            operation_payload_json=material.payload_json,
            operation_sha256=material.content_sha256,
            assessed_amount_text=_decimal(state.assessed_amount),
            net_collected_amount_text=_decimal(state.net_collected_amount),
            outstanding_amount_text=_decimal(state.outstanding_amount),
            tax_due_delta_text=_decimal(transition.tax_due_delta),
            collected_delta_text=_decimal(transition.collected_delta),
            outstanding_delta_text=_decimal(transition.outstanding_delta),
            cash_delta_text=_decimal(transition.cash_delta),
            audit_event_id=event.event_id,
            audit_event_version=event.event_version,
            audit_event_sha256=event.content_hash,
            outbox_record_id=str(outbox.outbox_id),
            outbox_payload_sha256=outbox.payload_hash,
            recorded_at=now,
        )
        values = {
            field.attname: getattr(row, field.attname)
            for field in row._meta.concrete_fields
            if field is not row._meta.auto_field
        }
        with _claim_tax_liability_insert(
            token=self._token, using=self._using, model_type=Operation, expected_values=values
        ):
            row.save(using=self._using)
        stored_chain = self._chain()
        if not stored_chain or stored_chain[-1].row.pk != row.pk:
            raise _blocked("Financial append did not retain its complete verified journal")
        origin.verify_for(
            assessment,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            cash_action=cash_action,
            using=self._using,
            as_of=self._clock.now(),
        )
        return stored_chain[-1].receipt

    def _assessment_id(self, assessment: CorporateActionTaxAssessment) -> int:
        """Read the exact existing revision again under its current transaction lock."""
        row = (
            Header._default_manager.using(self._using)
            .select_for_update()
            .get(
                account_id=assessment.account_id,
                assessment_revision_id=assessment.assessment_revision_id,
                idempotency_key=assessment.calculation.idempotency_key,
                semantic_sha256=assessment.semantic_sha256,
            )
        )
        self._assessments.verify_stored(row, assessment)
        if type(row.pk) is not int or row.pk <= 0:
            raise _blocked("Persisted assessment identity is invalid")
        return row.pk


__all__ = ["DjangoTaxLiabilityAtomicWriter", "require_ledger_cash_capacity"]
