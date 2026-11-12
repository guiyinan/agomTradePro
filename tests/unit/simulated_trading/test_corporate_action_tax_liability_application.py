from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from apps.simulated_trading.application import corporate_action_tax_liability as liability_app
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentAppendDisposition,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    TaxLiabilityCashAction,
    TaxLiabilityCashRequest,
    TaxLiabilityScope,
    TaxLiabilityTransitionKind,
    plan_corporate_action_tax_liability,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_liability import (
    _taxable_assessment,
)

_NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def test_locked_cash_observed_after_read_start_is_valid_at_read_completion() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    writer = _Writer(assessment, lease=lease)
    writer.cash_snapshot = _snapshot(
        assessment,
        lease,
        observed_at=_NOW + timedelta(seconds=2),
    )
    use_case, _, _, _, _ = _use_case(
        assessment,
        lease,
        writer=writer,
        clock=_Clock(tuple(_NOW + timedelta(seconds=i) for i in range(6))),
    )
    result = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="cash-after-read-start",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    assert result.cash_delta < 0


def test_current_financial_scope_receives_exact_operation_identity_and_action() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)

    class _CaptureIntentVerifier(_Verifier):
        @contextmanager
        def locked_current_scope(self, candidate, *, actor_user_id, using, **intent):
            self.intent = intent
            yield replace(self.lease, **intent)

    verifier = _CaptureIntentVerifier(lease)
    use_case, _, _, _, _ = _use_case(assessment, lease, verifier=verifier)
    use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="exact-financial-intent",
    )
    assert verifier.intent == {"operation_id": "exact-financial-intent", "cash_action": None}


@pytest.mark.parametrize("fault", ["operation", "action"])
def test_withholding_lease_for_another_operation_cannot_authorize_a_new_append(fault) -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)

    class _WrongIntentVerifier(_Verifier):
        @contextmanager
        def locked_current_scope(
            self,
            candidate,
            *,
            actor_user_id,
            using,
            operation_id,
            cash_action,
        ):
            yield replace(
                self.lease,
                operation_id="other-operation" if fault == "operation" else operation_id,
                cash_action=None if fault == "action" else cash_action,
            )

    use_case, writer, uow, _, _ = _use_case(
        assessment,
        lease,
        verifier=_WrongIntentVerifier(lease),
    )
    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="requested-operation",
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )
    assert writer.append_calls == [] and writer.cash_snapshot_calls == 0
    assert uow.rollbacks == 1


def _scope(assessment) -> TaxLiabilityScope:
    return TaxLiabilityScope(
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        security_id=assessment.security_id,
        asset_code=assessment.asset_code,
        corporate_action_id=assessment.action.corporate_action_id,
        source_namespace=assessment.action.source_namespace,
        logical_source_event_id=assessment.action.source_event_id,
        target_disposition_id=assessment.bridge.request.target_disposition_id,
        record_date=assessment.history.record_date,
        target_settlement_date=assessment.target_settlement_date,
    )


def _lease(assessment, *, valid_until: datetime = _NOW + timedelta(minutes=10)):
    return liability_app.TaxLiabilityWriteLease(
        database_alias="default",
        actor_user_id=assessment.owner_user_id,
        owner_user_id=assessment.owner_user_id,
        physical_account_id=assessment.account_id,
        scope=_scope(assessment),
        canonical_account_namespace="account",
        canonical_account_id="canonical-simulated-account-17",
        currency=SimulatedDividendTaxCurrency.CNY,
        currency_quantum=assessment.policy.currency_quantum,
        assessment_revision_id=assessment.assessment_revision_id,
        assessment_semantic_sha256=assessment.semantic_sha256,
        operation_id="test-operation-placeholder",
        cash_action=None,
        permission="simulated.corporate_action_tax.withhold",
        grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        capabilities=(Capability.TAX_WITHHOLD,),
        terms_version="simulated-corporate-action-owner-terms.v2",
        terms_sha256="d" * 64,
        service_actor_id=SIMULATED_CORPORATE_ACTION_SERVICE_ACTOR_ID,
        authority_grant_id="synthetic-tax-withhold-grant",
        authority_grant_version="grant-v2",
        authority_grant_content_sha256="e" * 64,
        audit_tenant_id="synthetic-tenant-v1",
        audit_owner_id="synthetic-owner-17",
        valid_until=valid_until,
    )


def _assessment_receipt(assessment) -> TaxAssessmentWriteReceipt:
    return TaxAssessmentWriteReceipt(
        disposition=TaxAssessmentAppendDisposition.STORED,
        assessment_revision_id=assessment.assessment_revision_id,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
    )


def _reference(stem: str):
    return liability_app.TaxLiabilityEvidenceReference(
        reference_id=f"synthetic-{stem}-17",
        reference_version="1",
        content_sha256="a" * 64,
    )


def _receipt(
    *,
    disposition,
    operation_id,
    request_sha256,
    assessment,
    lease,
    transition,
    cash_action=None,
    cash_snapshot=None,
    assessment_manifest_sha256: str | None = None,
):
    return liability_app.TaxLiabilityWriteReceipt(
        disposition=disposition,
        operation_id=operation_id,
        operation_request_sha256=request_sha256,
        scope=transition.state_after.scope,
        canonical_account_namespace=lease.canonical_account_namespace,
        canonical_account_id=lease.canonical_account_id,
        currency=lease.currency,
        currency_quantum=transition.state_after.currency_quantum,
        cash_action=cash_action,
        cash_snapshot_reference=(None if cash_snapshot is None else cash_snapshot.evidence),
        assessment_revision_id=assessment.assessment_revision_id,
        assessment_semantic_sha256=assessment.semantic_sha256,
        assessment_observation_manifest_sha256=(
            assessment.observation_manifest_sha256
            if assessment_manifest_sha256 is None
            else assessment_manifest_sha256
        ),
        transition_sha256=transition.transition_sha256,
        state_after_sha256=transition.state_after.state_sha256,
        tax_due_delta=transition.tax_due_delta,
        collected_delta=transition.collected_delta,
        outstanding_delta=transition.outstanding_delta,
        cash_delta=transition.cash_delta,
        liability_record=_reference("liability-record"),
        journal_entry=_reference("journal-entry"),
        audit_event=_reference("audit-event"),
        outbox_record=_reference("outbox-record"),
    )


def _snapshot(
    assessment,
    lease,
    *,
    book_cash: Decimal = Decimal("100.00"),
    reserved_cash: Decimal = Decimal("0.00"),
    observed_at: datetime = _NOW,
):
    content = f"{assessment.account_id}|{book_cash}|{reserved_cash}|{observed_at.isoformat()}"
    return liability_app.TaxLiabilityFinancialSnapshot(
        physical_account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        scope=_scope(assessment),
        canonical_account_namespace=lease.canonical_account_namespace,
        canonical_account_id=lease.canonical_account_id,
        currency=lease.currency,
        book_cash=book_cash,
        reserved_cash=reserved_cash,
        evidence=liability_app.TaxLiabilityEvidenceReference(
            reference_id="synthetic-cash-snapshot-v1",
            reference_version="1",
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ),
        observed_at=observed_at,
    )


class _Clock:
    def __init__(self, values: tuple[datetime, ...] = (_NOW,)) -> None:
        self.values = values
        self.calls = 0

    def now(self) -> datetime:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


class _Verifier:
    database_alias = "default"

    def __init__(self, lease, *, exit_error: BaseException | None = None) -> None:
        self.lease = lease
        self.exit_error = exit_error
        self.calls: list[tuple[object, int, str]] = []

    @contextmanager
    def locked_current_scope(
        self, assessment, *, actor_user_id: int, using: str, operation_id, cash_action
    ) -> Iterator[liability_app.TaxLiabilityWriteLease]:
        self.calls.append((assessment, actor_user_id, using))
        yield (
            replace(self.lease, operation_id=operation_id, cash_action=cash_action)
            if type(self.lease) is liability_app.TaxLiabilityWriteLease
            else self.lease
        )
        if self.exit_error is not None:
            raise self.exit_error


class _Writer:
    def __init__(
        self,
        assessment,
        *,
        lease=None,
        malformed_assessment: object | None = None,
    ) -> None:
        self.assessment_receipt: object = (
            _assessment_receipt(assessment)
            if malformed_assessment is None
            else malformed_assessment
        )
        self.current: object | None = None
        self.operations: dict[str, liability_app.TaxLiabilityWriteReceipt] = {}
        self.append_calls: list[tuple[object, ...]] = []
        self.lock_calls: list[tuple[object, ...]] = []
        self.read_current_calls = 0
        self.cash_snapshot_calls = 0
        self.cash_snapshot = _snapshot(assessment, _lease(assessment) if lease is None else lease)
        self.fail_replay = False
        self.return_bad_append: object | None = None

    def require_stored_assessment(
        self, assessment, *, actor_user_id: int
    ) -> TaxAssessmentWriteReceipt:
        assert actor_user_id == assessment.owner_user_id
        if isinstance(self.assessment_receipt, BaseException):
            raise self.assessment_receipt
        return self.assessment_receipt  # type: ignore[return-value]

    def lock_operation_and_state(
        self,
        *,
        operation_id: str,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ) -> None:
        self.lock_calls.append(
            (operation_id, scope, canonical_account_namespace, canonical_account_id, currency)
        )

    def get_operation(self, *, operation_id: str):
        if self.fail_replay:
            raise BusinessLogicError("original journal or Audit/Outbox evidence is incomplete")
        receipt = self.operations.get(operation_id)
        if receipt is None:
            return None
        return replace(
            receipt,
            disposition=liability_app.TaxLiabilityAppendDisposition.EXACT_RETRY,
        )

    def read_current_state(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ):
        self.read_current_calls += 1
        return self.current

    def read_financial_snapshot(
        self,
        *,
        scope: TaxLiabilityScope,
        canonical_account_namespace: str,
        canonical_account_id: str,
        currency: SimulatedDividendTaxCurrency,
    ):
        self.cash_snapshot_calls += 1
        return self.cash_snapshot

    def append_transition(
        self,
        assessment,
        transition,
        *,
        actor_user_id: int,
        stored_assessment: TaxAssessmentWriteReceipt,
        lease: liability_app.TaxLiabilityWriteLease,
        operation_id: str,
        operation_request_sha256: str,
        expected_prior_state_sha256: str | None,
        cash_action: TaxLiabilityCashAction | None,
        cash_snapshot,
    ):
        self.append_calls.append(
            (
                assessment,
                transition,
                actor_user_id,
                stored_assessment,
                lease,
                operation_id,
                operation_request_sha256,
                expected_prior_state_sha256,
            )
        )
        if self.return_bad_append is not None:
            return self.return_bad_append
        receipt = _receipt(
            disposition=liability_app.TaxLiabilityAppendDisposition.STORED,
            operation_id=operation_id,
            request_sha256=operation_request_sha256,
            assessment=assessment,
            lease=lease,
            transition=transition,
            cash_action=cash_action,
            cash_snapshot=cash_snapshot,
            assessment_manifest_sha256=stored_assessment.observation_manifest_sha256,
        )
        self.operations[operation_id] = receipt
        self.current = liability_app.TaxLiabilityCurrentState(
            state=transition.state_after,
            canonical_account_namespace=lease.canonical_account_namespace,
            canonical_account_id=lease.canonical_account_id,
            currency=lease.currency,
            assessment_observation_manifest_sha256=(stored_assessment.observation_manifest_sha256),
            last_operation_receipt=receipt,
        )
        return receipt


class _UnitOfWork:
    database_alias = "default"

    def __init__(self, writer: _Writer) -> None:
        self.writer = writer
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def atomic(self, *, using: str) -> Iterator[_Writer]:
        assert using == "default"
        old_current = self.writer.current
        old_operations = self.writer.operations.copy()
        try:
            yield self.writer
        except BaseException:
            self.writer.current = old_current
            self.writer.operations = old_operations
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


def _use_case(assessment, lease, *, writer=None, clock=None, verifier=None):
    selected_writer = _Writer(assessment, lease=lease) if writer is None else writer
    selected_clock = _Clock() if clock is None else clock
    selected_verifier = _Verifier(lease) if verifier is None else verifier
    uow = _UnitOfWork(selected_writer)
    use_case = liability_app.CorporateActionTaxLiabilityUseCase(
        scope_verifier=selected_verifier,
        unit_of_work=uow,
        clock=selected_clock,
        using="default",
    )
    return use_case, selected_writer, uow, selected_clock, selected_verifier


def _cash_request(
    action: TaxLiabilityCashAction,
    *,
    book_cash: Decimal = Decimal("100.00"),
    reserved_cash: Decimal = Decimal("0.00"),
) -> TaxLiabilityCashRequest:
    return TaxLiabilityCashRequest(
        action=action,
        book_cash=book_cash,
        reserved_cash=reserved_cash,
    )


def test_recognizes_stored_disposition_without_implicit_cash_action() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, verifier = _use_case(assessment, lease)

    receipt = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="recognize-disposition-v1",
    )

    assert receipt.disposition is liability_app.TaxLiabilityAppendDisposition.STORED
    assert receipt.cash_delta == Decimal("0")
    assert receipt.collected_delta == Decimal("0")
    assert receipt.scope == _scope(assessment)
    assert receipt.currency is SimulatedDividendTaxCurrency.CNY
    assert receipt.assessment_revision_id == assessment.assessment_revision_id
    assert receipt.audit_event.reference_id and receipt.outbox_record.reference_id
    assert writer.cash_snapshot_calls == 0
    assert len(writer.append_calls) == 1
    assert writer.append_calls[0][-1] is None
    assert uow.commits == 1 and uow.rollbacks == 0
    assert verifier.calls == [(assessment, assessment.owner_user_id, "default")]


def test_operation_retry_returns_original_artifacts_and_does_not_reapply() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, _ = _use_case(assessment, lease)
    first = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="recognize-once-v1",
    )
    second = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="recognize-once-v1",
    )

    assert second.disposition is liability_app.TaxLiabilityAppendDisposition.EXACT_RETRY
    assert second == replace(
        first, disposition=liability_app.TaxLiabilityAppendDisposition.EXACT_RETRY
    )
    assert len(writer.append_calls) == 1
    assert writer.read_current_calls == 1
    assert uow.commits == 2


def test_operation_id_cannot_replay_another_operations_original_receipt() -> None:
    assessment = _taxable_assessment()
    use_case, writer, uow, _, _ = _use_case(assessment, _lease(assessment))
    use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="expected-operation-v1",
    )
    writer.operations["expected-operation-v1"] = replace(
        writer.operations["expected-operation-v1"],
        operation_id="another-operation-v1",
    )

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="expected-operation-v1",
        )

    assert len(writer.append_calls) == 1
    assert uow.rollbacks == 1


def test_same_operation_id_with_changed_cash_action_blocks_before_append() -> None:
    assessment = _taxable_assessment()
    use_case, writer, uow, _, _ = _use_case(assessment, _lease(assessment))
    use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="cash-operation-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="cash-operation-v1",
            cash_action=TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
        )

    assert len(writer.append_calls) == 1
    assert uow.rollbacks == 1


def test_application_never_accepts_client_supplied_cash_balances() -> None:
    assessment = _taxable_assessment()
    use_case, writer, uow, _, _ = _use_case(assessment, _lease(assessment))

    with pytest.raises(TypeError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="forged-client-cash-v1",
            cash_request=_cash_request(
                TaxLiabilityCashAction.COLLECT_AVAILABLE,
                book_cash=Decimal("100000.00"),
            ),
        )

    assert writer.cash_snapshot_calls == 0
    assert not writer.append_calls
    assert uow.commits == 0


def test_v2_withholding_lease_requires_explicit_withhold_capability() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)

    with pytest.raises(BusinessLogicError):
        replace(lease, capabilities=(Capability.TAX_ASSESS,))
    with pytest.raises(BusinessLogicError):
        replace(lease, grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA + "-wrong")
    with pytest.raises(BusinessLogicError):
        replace(lease, currency="USD")


def test_exact_cash_operation_retry_returns_original_snapshot_after_balance_changes() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, _, _, _ = _use_case(assessment, lease)
    writer.cash_snapshot = _snapshot(assessment, lease, book_cash=Decimal("0.50"))
    first = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="cash-retry-after-deposit-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    writer.cash_snapshot = _snapshot(assessment, lease, book_cash=Decimal("99.00"))
    replay = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="cash-retry-after-deposit-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )

    assert first.collected_delta == Decimal("0.50")
    assert replay.disposition is liability_app.TaxLiabilityAppendDisposition.EXACT_RETRY
    assert replay.cash_snapshot_reference == first.cash_snapshot_reference
    assert replay.cash_delta == Decimal("-0.50")
    assert writer.cash_snapshot_calls == 1
    assert len(writer.append_calls) == 1


def test_partial_collection_and_later_recovery_are_separate_operations() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, _, _, _ = _use_case(assessment, lease)
    writer.cash_snapshot = _snapshot(assessment, lease, book_cash=Decimal("0.50"))
    first = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="collect-first-part-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    writer.cash_snapshot = _snapshot(assessment, lease)
    second = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="collect-recovery-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )

    assert first.collected_delta == Decimal("0.50")
    assert first.cash_delta == Decimal("-0.50")
    assert second.collected_delta == Decimal("0.50")
    assert second.cash_delta == Decimal("-0.50")
    assert writer.current.state.net_collected_amount == Decimal("1.00")
    assert writer.append_calls[1][1].kind is TaxLiabilityTransitionKind.EXACT_REPLAY
    assert first.operation_id != second.operation_id


def test_current_financial_snapshot_must_match_exact_canonical_account() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, _ = _use_case(assessment, lease)
    writer.cash_snapshot = replace(
        writer.cash_snapshot,
        canonical_account_id="another-canonical-account",
    )

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="wrong-snapshot-account-v1",
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )

    assert writer.cash_snapshot_calls == 1
    assert not writer.append_calls
    assert uow.rollbacks == 1


def test_locked_cash_outside_domain_capacity_fails_as_business_error() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, _ = _use_case(assessment, lease)
    writer.cash_snapshot = _snapshot(
        assessment,
        lease,
        book_cash=Decimal("1E+68"),
    )

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="unsupported-cash-capacity-v1",
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )

    assert writer.cash_snapshot_calls == 1
    assert not writer.append_calls
    assert uow.rollbacks == 1


def test_successor_correction_requires_explicit_refund_of_overcollection() -> None:
    first_assessment = _taxable_assessment()
    first_use_case, writer, _, _, _ = _use_case(first_assessment, _lease(first_assessment))
    first = first_use_case.execute(
        first_assessment,
        actor_user_id=first_assessment.owner_user_id,
        operation_id="collect-original-tax-v1",
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    )
    assert first.collected_delta == Decimal("1.00")

    correction = _taxable_assessment(
        revision_id="liability-assessment-corrected-v2",
        supersedes=first_assessment.assessment_revision_id,
        dividend_per_share=Decimal("0.25"),
    )
    correction_use_case, _, _, _, _ = _use_case(
        correction,
        _lease(correction),
        writer=writer,
    )
    correction_lease = _lease(correction)
    writer.assessment_receipt = _assessment_receipt(correction)
    writer.cash_snapshot = _snapshot(correction, correction_lease, book_cash=Decimal("0.00"))
    refund = correction_use_case.execute(
        correction,
        actor_user_id=correction.owner_user_id,
        operation_id="refund-corrected-overcollection-v1",
        cash_action=TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
    )

    assert refund.tax_due_delta == Decimal("-0.50")
    assert refund.collected_delta == Decimal("-0.50")
    assert refund.cash_delta == Decimal("0.50")
    assert writer.current.state.assessment_revision_id == correction.assessment_revision_id


def test_missing_original_assessment_audit_or_outbox_blocks_without_append() -> None:
    assessment = _taxable_assessment()
    writer = _Writer(assessment)
    writer.assessment_receipt = BusinessLogicError("original assessment evidence is incomplete")
    use_case, _, uow, _, _ = _use_case(assessment, _lease(assessment), writer=writer)

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="missing-assessment-proof-v1",
        )

    assert not writer.append_calls
    assert uow.rollbacks == 1


def test_replay_with_missing_original_journal_or_audit_outbox_never_reappends() -> None:
    assessment = _taxable_assessment()
    use_case, writer, uow, _, _ = _use_case(assessment, _lease(assessment))
    use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="original-operation-v1",
    )
    writer.fail_replay = True

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="original-operation-v1",
        )

    assert len(writer.append_calls) == 1
    assert uow.rollbacks == 1


def test_bad_writer_receipt_rolls_back_all_written_artifacts() -> None:
    assessment = _taxable_assessment()
    writer = _Writer(assessment)
    writer.return_bad_append = object()
    use_case, _, uow, _, _ = _use_case(assessment, _lease(assessment), writer=writer)

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="malformed-writer-receipt-v1",
        )

    assert uow.rollbacks == 1
    assert writer.current is None
    assert not writer.operations


def test_wrong_owner_alias_and_untyped_withholding_lease_fail_closed() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, _ = _use_case(assessment, lease)

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id + 1,
            operation_id="wrong-owner-v1",
        )
    assert not writer.append_calls
    assert uow.rollbacks == 0

    untyped_verifier = _Verifier(object())
    untyped_use_case, untyped_writer, untyped_uow, _, _ = _use_case(
        assessment,
        lease,
        verifier=untyped_verifier,
    )
    with pytest.raises(BusinessLogicError):
        untyped_use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="untyped-lease-v1",
        )
    assert not untyped_writer.append_calls
    assert untyped_uow.rollbacks == 1


def test_alias_mismatch_is_rejected_before_opening_the_atomic_writer() -> None:
    assessment = _taxable_assessment()
    use_case, writer, uow, _, _ = _use_case(assessment, _lease(assessment))
    use_case._unit_of_work.database_alias = "other"

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="wrong-alias-v1",
        )

    assert not writer.append_calls
    assert uow.commits == 0
    assert uow.rollbacks == 0


def test_exit_expiry_or_backward_server_clock_rolls_back() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment, valid_until=_NOW + timedelta(seconds=2))
    expiry_case, expiry_writer, expiry_uow, _, _ = _use_case(
        assessment,
        lease,
        clock=_Clock((_NOW, _NOW + timedelta(seconds=1), _NOW + timedelta(seconds=2))),
    )
    with pytest.raises(BusinessLogicError):
        expiry_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="expiry-on-exit-v1",
            cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        )
    assert expiry_uow.rollbacks == 1
    assert expiry_writer.current is None
    assert expiry_writer.cash_snapshot_calls == 1

    backward_case, backward_writer, backward_uow, _, _ = _use_case(
        assessment,
        _lease(assessment),
        clock=_Clock((_NOW, _NOW + timedelta(seconds=1), _NOW)),
    )
    with pytest.raises(BusinessLogicError):
        backward_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="backward-clock-on-exit-v1",
        )
    assert backward_uow.rollbacks == 1
    assert backward_writer.current is None


def test_verifier_exit_rejection_rolls_back_the_liability_and_journal() -> None:
    assessment = _taxable_assessment()
    verifier = _Verifier(_lease(assessment), exit_error=BusinessLogicError("grant changed"))
    use_case, writer, uow, _, _ = _use_case(
        assessment,
        verifier.lease,
        verifier=verifier,
    )

    with pytest.raises(BusinessLogicError):
        use_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="owner-revoked-before-commit-v1",
        )

    assert uow.rollbacks == 1
    assert writer.current is None
    assert not writer.operations


def test_current_state_must_match_currency_and_canonical_account() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    use_case, writer, uow, _, _ = _use_case(assessment, lease)
    first = use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id="initial-state-v1",
    )
    state = writer.current
    assert type(state) is liability_app.TaxLiabilityCurrentState

    mismatched_receipt = replace(
        state.last_operation_receipt,
        canonical_account_id="other-canonical-account",
    )
    wrong_account = replace(
        state,
        canonical_account_id="other-canonical-account",
        last_operation_receipt=mismatched_receipt,
    )
    writer.current = wrong_account
    mismatch_case, _, mismatch_uow, _, _ = _use_case(
        assessment,
        lease,
        writer=writer,
    )
    with pytest.raises(BusinessLogicError):
        mismatch_case.execute(
            assessment,
            actor_user_id=assessment.owner_user_id,
            operation_id="wrong-current-account-v1",
        )
    assert mismatch_uow.rollbacks == 1
    assert first.state_after_sha256 == state.state.state_sha256


def test_operation_receipt_requires_complete_original_artifact_references() -> None:
    assessment = _taxable_assessment()
    lease = _lease(assessment)
    request = _cash_request(TaxLiabilityCashAction.COLLECT_AVAILABLE)
    transition = plan_corporate_action_tax_liability(
        assessment, prior_state=None, cash_request=request
    )
    valid = _receipt(
        disposition=liability_app.TaxLiabilityAppendDisposition.STORED,
        operation_id="receipt-v1",
        request_sha256="1" * 64,
        assessment=assessment,
        lease=lease,
        transition=transition,
        cash_action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
        cash_snapshot=_snapshot(assessment, lease),
    )

    with pytest.raises(BusinessLogicError):
        replace(valid, outbox_record=object())
