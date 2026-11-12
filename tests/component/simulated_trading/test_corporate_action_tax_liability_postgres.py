"""Migrated financial storage contracts with explicitly controlled tax authority.

These tests exercise real cash, journals and existing Audit/Outbox atomicity.
They do not claim genuine current statutory qualification or real Owner consent.
The separately tested concrete current-owner verifier supplies those gates.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityAppendDisposition,
    TaxLiabilityWriteLease,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    TaxLiabilityAuditOrigin,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    build_audited_tax_liability_use_case,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityCashAction
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError
from tests.component.simulated_trading.test_corporate_action_tax_assessment_postgres import (
    _native_fixture,
)
from tests.component.simulated_trading.test_corporate_action_tax_assessment_postgres import (
    _run as _assess,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.unit.simulated_trading.test_corporate_action_tax_liability_application import _lease

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Actual migrated PostgreSQL financial contract"
    ),
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "apps.account",
            "apps.simulated_trading",
            "apps.audit",
        ],
    ),
]
_EVENT = "simulated.corporate_action.tax_liability_applied"


@pytest.fixture(scope="module", autouse=True)
def require_real_financial_schema(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM django_migrations WHERE app='simulated_trading' AND name='0046_corporate_action_tax_liability_operation'"
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname='sim_ca_tax_liability_op_immutable' AND NOT tgisinternal"
        )
        assert cursor.fetchone() == ("A",)


class _ControlledFinancialScope:
    """Hold actual owner/cash rows while providing clearly synthetic grant/source facts."""

    database_alias = "default"

    def __init__(self, *, fail_exit=False):
        self.active = None
        self.fail_exit = fail_exit

    @contextmanager
    def locked_current_scope(
        self, assessment, *, actor_user_id, using, operation_id, cash_action
    ) -> Iterator[TaxLiabilityWriteLease]:
        account = (
            SimulatedAccountModel.objects.using(using)
            .select_for_update()
            .get(pk=assessment.account_id)
        )
        if account.user_id != actor_user_id:
            raise BusinessLogicError("controlled physical owner mismatch")
        lease = replace(
            _lease(assessment, valid_until=timezone.now() + timedelta(minutes=5)),
            operation_id=operation_id,
            cash_action=cash_action,
            audit_owner_id=f"user:{actor_user_id}",
        )
        qualification = CurrentTaxAssessmentQualification(
            assessment_semantic_sha256=assessment.semantic_sha256,
            account_id=assessment.account_id,
            owner_user_id=assessment.owner_user_id,
            canonical_account_id=lease.canonical_account_id,
            environment="synthetic-financial-storage",
            qualification_id="controlled-storage-only",
            qualification_sha256="a" * 64,
            runtime_profile_id="controlled-profile",
            runtime_profile_content_sha256="b" * 64,
            runtime_snapshot_id="controlled-snapshot",
            runtime_snapshot_sha256="c" * 64,
            valid_until=lease.valid_until,
        )
        self.active = TaxLiabilityAuditOrigin(
            lease,
            "synthetic-financial-storage",
            "controlled-account-source",
            "1",
            "d" * 64,
            account.updated_at,
            qualification,
            "append",
        )
        try:
            yield lease
            if self.fail_exit:
                raise BusinessLogicError("controlled financial authority changed at exit")
        finally:
            self.active = None

    def get_locked_audit_origin(self):
        if self.active is None:
            raise BusinessLogicError("controlled financial scope is not active")
        return self.active


def _fixture(*, cash=None):
    account, assessment = _native_fixture()
    if cash is not None:
        SimulatedAccountModel.objects.filter(pk=account.pk).update(
            current_cash=cash, updated_at=timezone.now()
        )
        account.refresh_from_db()
    _assess(assessment)
    return account, assessment


def _run(
    assessment,
    operation="financial-operation-1",
    action=TaxLiabilityCashAction.COLLECT_AVAILABLE,
    *,
    verifier=None,
    audit=None,
):
    use_case = build_audited_tax_liability_use_case(
        scope_verifier=verifier or _ControlledFinancialScope(), using="default", audit=audit
    )
    return use_case.execute(
        assessment,
        actor_user_id=assessment.owner_user_id,
        operation_id=operation,
        cash_action=action,
    )


def _financial_counts():
    return (
        Operation.objects.count(),
        SystemAuditEventModel.objects.filter(event_type=_EVENT).count(),
        SystemAuditOutboxModel.objects.filter(
            event_id__startswith="simulated-tax-operation:"
        ).count(),
    )


def test_native_partial_collection_and_exact_retry_keep_one_complete_financial_set():
    account, assessment = _fixture(cash=Decimal("0.50"))
    assert assessment.calculation.withholding_amount > Decimal("0.50")
    first = _run(assessment)
    again = _run(assessment)
    account.refresh_from_db()
    assert account.current_cash == 0
    assert first.cash_delta == Decimal("-0.50")
    assert first.outstanding_delta == assessment.calculation.withholding_amount - Decimal("0.50")
    assert again == replace(first, disposition=TaxLiabilityAppendDisposition.EXACT_RETRY)
    assert _financial_counts() == (1, 1, 1)


def test_native_recognition_retains_unpaid_tax_without_cash_movement():
    account, assessment = _fixture()
    first = _run(assessment, action=None)
    account.refresh_from_db()
    assert first.cash_delta == 0 and first.collected_delta == 0
    assert first.outstanding_delta == assessment.calculation.withholding_amount
    assert account.current_cash == Decimal("100")
    assert _financial_counts() == (1, 1, 1)


def test_native_new_operation_recovers_remaining_tax_after_later_funding():
    account, assessment = _fixture(cash=Decimal("0.50"))
    _run(assessment)
    SimulatedAccountModel.objects.filter(pk=account.pk).update(
        current_cash=Decimal("10"), updated_at=timezone.now()
    )
    second = _run(assessment, operation="recover-unpaid-tax")
    account.refresh_from_db()
    assert second.collected_delta == assessment.calculation.withholding_amount - Decimal("0.50")
    assert second.outstanding_delta == -second.collected_delta
    assert account.current_cash == Decimal("10") - second.collected_delta
    assert _financial_counts() == (2, 2, 2)


def test_native_explicit_successor_refunds_only_actual_overcollection():
    account, assessment = _fixture()
    first = _run(assessment)
    corrected = replace(
        assessment,
        assessment_revision_id="tax-correction-lower",
        supersedes_assessment_revision_id=assessment.assessment_revision_id,
        action=replace(
            assessment.action, dividend_per_share=assessment.action.dividend_per_share / 2
        ),
    )
    _assess(corrected)
    refund = _run(
        corrected,
        operation="refund-correction",
        action=TaxLiabilityCashAction.REFUND_OVERCOLLECTION,
    )
    account.refresh_from_db()
    assert (
        refund.cash_delta
        == assessment.calculation.withholding_amount - corrected.calculation.withholding_amount
    )
    assert account.current_cash == Decimal("100") + first.cash_delta + refund.cash_delta
    assert _financial_counts() == (2, 2, 2)


def test_native_late_owner_failure_rolls_back_cash_journal_audit_and_outbox():
    account, assessment = _fixture()
    before = account.updated_at
    with pytest.raises(BusinessLogicError, match="changed at exit"):
        _run(assessment, verifier=_ControlledFinancialScope(fail_exit=True))
    account.refresh_from_db()
    assert account.current_cash == Decimal("100") and account.updated_at == before
    assert _financial_counts() == (0, 0, 0)


def test_native_late_journal_failure_rolls_back_cash_audit_and_outbox():
    account, assessment = _fixture()
    with patch.object(
        Operation, "save", side_effect=IntegrityError("controlled journal insert failure")
    ):
        with pytest.raises(IntegrityError):
            _run(assessment)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100")
    assert _financial_counts() == (0, 0, 0)


def test_native_missing_original_financial_outbox_is_blocked_without_repair():
    account, assessment = _fixture()
    first = _run(assessment)
    audit = build_tax_assessment_audit_coordinator(using="default")
    original = type(audit).get_exact_outbox_winner_targeted

    def hide_financial_outbox(self, event):
        return None if event.event_type == _EVENT else original(self, event)

    with patch.object(type(audit), "get_exact_outbox_winner_targeted", hide_financial_outbox):
        with pytest.raises(BusinessLogicError, match="repair is forbidden"):
            _run(assessment, audit=audit)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100") + first.cash_delta
    assert _financial_counts() == (1, 1, 1)


def test_native_same_operation_id_changed_action_cannot_write_again():
    account, assessment = _fixture()
    first = _run(assessment)
    with pytest.raises(BusinessLogicError):
        _run(assessment, action=None)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100") + first.cash_delta
    assert _financial_counts() == (1, 1, 1)


def test_native_concurrent_exact_operations_collect_only_once():
    account, assessment = _fixture()
    barrier = Barrier(2)

    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            return _run(assessment)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert {item.disposition for item in results} == {
        TaxLiabilityAppendDisposition.STORED,
        TaxLiabilityAppendDisposition.EXACT_RETRY,
    }
    account.refresh_from_db()
    assert account.current_cash == Decimal("100") - assessment.calculation.withholding_amount
    assert _financial_counts() == (1, 1, 1)


def test_native_financial_journal_always_guard_blocks_raw_replica_mutations():
    _, assessment = _fixture()
    _run(assessment)
    for statement in (
        "UPDATE sim_ca_tax_liability_operation SET cash_delta_text='999'",
        "DELETE FROM sim_ca_tax_liability_operation",
    ):
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL session_replication_role='replica'")
            cursor.execute(statement)
    assert _financial_counts() == (1, 1, 1)


def test_native_partial_dispositions_can_reuse_revision_labels_without_cross_readback():
    account, first = _fixture()
    _run(first)
    last = first.history.settlement_days[-1]
    next_day = replace(
        last,
        settlement_date=date(2025, 3, 4),
        opening_eod_quantity=Decimal("60"),
        gross_purchase_quantity=Decimal("0"),
        gross_sale_quantity=Decimal("5"),
        closing_eod_quantity=Decimal("55"),
        evidence_id="synthetic-later-tax-disposition",
        evidence_sha256="f" * 64,
    )
    history = replace(
        first.history,
        complete_through=next_day.settlement_date,
        covered_session_dates=first.history.covered_session_dates + (next_day.settlement_date,),
        settlement_days=first.history.settlement_days + (next_day,),
    )
    second = replace(first, history=history, target_settlement_date=next_day.settlement_date)
    assert second.assessment_revision_id == first.assessment_revision_id
    assert second.calculation.idempotency_key != first.calculation.idempotency_key
    _assess(second)
    _run(second, operation="later-partial-disposition")
    account.refresh_from_db()
    assert (
        account.current_cash
        == Decimal("100")
        - first.calculation.withholding_amount
        - second.calculation.withholding_amount
    )
    assert _financial_counts() == (2, 2, 2)
