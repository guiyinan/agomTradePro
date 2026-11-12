"""Actual migrated PG atomicity with explicitly synthetic qualified inputs.

The controlled verifier below tests storage fences, not live consent, custody
dates, official-source qualification or an enabled financial capability.
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
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentWriteLease,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    TaxAssessmentAuditOrigin,
    build_audited_tax_assessment_use_case,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentAllocationModel as Allocation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import (
    _assessment,
    _source_bundle,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment_application import _lease

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native migrated PostgreSQL contract; executed by the required PostgreSQL workflow.",
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
_EVENT = "simulated.corporate_action.tax_assessed"


@pytest.fixture(scope="module", autouse=True)
def require_real_assessment_schema(django_db_setup: None, django_db_blocker: object) -> None:
    """Reject syncdb substitutes; require the genuine migration and both ALWAYS guards."""
    del django_db_setup
    with django_db_blocker.unblock():
        assert connection.vendor == "postgresql"
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app='simulated_trading' AND name='0045_corporate_action_tax_assessment'"
            )
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN ('sim_ca_tax_assessment_immutable','sim_ca_tax_alloc_immutable') AND tgenabled='A' AND NOT tgisinternal"
            )
            assert cursor.fetchone() == (2,)


def _native_fixture() -> tuple[SimulatedAccountModel, CorporateActionTaxAssessment]:
    user = get_user_model().objects.create_user(username=f"tax-{uuid4()}")
    account = SimulatedAccountModel._default_manager.create(
        user=user,
        account_name="Synthetic tax storage fixture",
        account_type="simulated",
        initial_capital=Decimal("100"),
        current_cash=Decimal("100"),
        current_market_value=Decimal("0"),
        total_value=Decimal("100"),
        is_active=True,
    )
    candidate = _assessment(
        bundle=_source_bundle(captured_at=timezone.now() - timedelta(minutes=1))
    )
    history = candidate.history
    history = replace(
        history,
        account_id=account.pk,
        owner_user_id=user.pk,
        record_date_ownership_proof=replace(
            history.record_date_ownership_proof, account_id=account.pk, owner_user_id=user.pk
        ),
        opening_anchor=replace(
            history.opening_anchor, account_id=account.pk, owner_user_id=user.pk
        ),
        settlement_days=tuple(
            replace(day, account_id=account.pk, owner_user_id=user.pk)
            for day in history.settlement_days
        ),
    )
    action = replace(candidate.action, account_id=account.pk, owner_user_id=user.pk)
    # Explicit synthetic terms produce a positive due amount; no statutory or
    # real custody qualification is claimed by this fixture.
    policy = replace(
        candidate.policy,
        bands=(
            replace(candidate.policy.bands[0], maximum_holding_months=24),
            candidate.policy.bands[1],
        ),
    )
    result = replace(candidate, action=action, history=history, policy=policy)
    assert result.calculation.withholding_amount > 0
    return account, result


class _ControlledVerifier:
    """Lock a real physical owner while supplying explicit test-only policy evidence."""

    database_alias = "default"

    def __init__(self, *, fail_exit: bool = False) -> None:
        self.active: TaxAssessmentWriteLease | None = None
        self.fail_exit = fail_exit

    @contextmanager
    def locked_current_scope(
        self, assessment: CorporateActionTaxAssessment, *, actor_user_id: int, using: str
    ) -> Iterator[TaxAssessmentWriteLease]:
        account = (
            SimulatedAccountModel._default_manager.using(using)
            .select_for_update()
            .get(pk=assessment.account_id)
        )
        if account.user_id != actor_user_id:
            raise BusinessLogicError("test physical owner differs")
        self.active = replace(_lease(assessment), valid_until=timezone.now() + timedelta(minutes=5))
        try:
            yield self.active
            if self.fail_exit:
                raise BusinessLogicError("controlled authority changed before commit")
        finally:
            self.active = None

    def get_locked_audit_origin(self) -> TaxAssessmentAuditOrigin:
        if self.active is None:
            raise BusinessLogicError("test authority is not locked")
        return TaxAssessmentAuditOrigin(
            self.active,
            AuditScopeRef("synthetic-tax-tenant", f"user:{self.active.owner_user_id}"),
            "e" * 64,
            AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        )


def _run(
    assessment: CorporateActionTaxAssessment, verifier: _ControlledVerifier | None = None
) -> object:
    use_case = build_audited_tax_assessment_use_case(
        scope_verifier=verifier or _ControlledVerifier(), using="default"
    )
    return use_case.execute(assessment, actor_user_id=assessment.owner_user_id)


def _counts() -> tuple[int, int, int, int]:
    return (
        Header._default_manager.count(),
        Allocation._default_manager.count(),
        SystemAuditEventModel._default_manager.filter(event_type=_EVENT).count(),
        SystemAuditOutboxModel._default_manager.count(),
    )


def test_native_assessment_and_retry_keep_one_header_allocation_audit_outbox_set() -> None:
    account, assessment = _native_fixture()
    first = _run(assessment)
    again = _run(assessment)
    assert first.semantic_sha256 == again.semantic_sha256
    assert _counts() == (1, 1, 1, 1)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100")
    assert account.current_market_value == 0
    assert account.total_value == Decimal("100")


def test_native_new_observation_and_nonce_return_first_persisted_manifest() -> None:
    _, assessment = _native_fixture()
    original = _run(assessment)
    observed = replace(
        assessment,
        assessment_revision_id="fresh-request-nonce",
        statutory_source_bundle=_source_bundle(
            capture_id=uuid4(),
            captured_at=timezone.now() - timedelta(seconds=1),
            bundle_version="new-observation",
        ),
        history=replace(
            assessment.history,
            record_date_ownership_proof=replace(
                assessment.history.record_date_ownership_proof,
                ownership_snapshot_id="new-observation-proof",
                ownership_snapshot_sha256="f" * 64,
            ),
        ),
    )
    assert observed.semantic_sha256 == assessment.semantic_sha256
    assert observed.observation_manifest_sha256 != original.observation_manifest_sha256
    retried = _run(observed)
    assert retried.assessment_revision_id == original.assessment_revision_id
    assert retried.observation_manifest_sha256 == original.observation_manifest_sha256
    assert _counts() == (1, 1, 1, 1)


def test_native_changed_facts_require_explicit_successor_and_preserve_history() -> None:
    _, assessment = _native_fixture()
    _run(assessment)
    changed = replace(
        assessment,
        assessment_revision_id="correction-2",
        action=replace(assessment.action, dividend_per_share=Decimal("0.60")),
    )
    with pytest.raises(BusinessLogicError):
        _run(changed)
    assert _counts() == (1, 1, 1, 1)
    corrected = replace(
        changed, supersedes_assessment_revision_id=assessment.assessment_revision_id
    )
    _run(corrected)
    assert _counts() == (2, 2, 2, 2)
    with pytest.raises(BusinessLogicError):
        _run(assessment)


def test_native_authority_change_at_exit_rolls_back_all_four_writes() -> None:
    _, assessment = _native_fixture()
    with pytest.raises(BusinessLogicError, match="changed before commit"):
        _run(assessment, _ControlledVerifier(fail_exit=True))
    assert _counts() == (0, 0, 0, 0)


def test_native_late_outbox_verification_failure_rolls_back_all_writes() -> None:
    _, assessment = _native_fixture()
    audit = build_tax_assessment_audit_coordinator(using="default")
    use_case = build_audited_tax_assessment_use_case(
        scope_verifier=_ControlledVerifier(), using="default", audit=audit
    )
    with patch.object(type(audit), "get_exact_outbox_winner_targeted", return_value=None):
        with pytest.raises(BusinessLogicError):
            use_case.execute(assessment, actor_user_id=assessment.owner_user_id)
    assert _counts() == (0, 0, 0, 0)


def test_native_missing_original_outbox_is_blocked_without_repair() -> None:
    _, assessment = _native_fixture()
    _run(assessment)
    audit = build_tax_assessment_audit_coordinator(using="default")
    use_case = build_audited_tax_assessment_use_case(
        scope_verifier=_ControlledVerifier(), using="default", audit=audit
    )
    with patch.object(type(audit), "get_exact_outbox_winner_targeted", return_value=None):
        with pytest.raises(BusinessLogicError):
            use_case.execute(assessment, actor_user_id=assessment.owner_user_id)
    assert _counts() == (1, 1, 1, 1)


def test_native_source_action_alias_cannot_create_another_tax_stream() -> None:
    _, assessment = _native_fixture()
    _run(assessment)
    alias = replace(
        assessment,
        assessment_revision_id="alias-attempt",
        action=replace(assessment.action, corporate_action_id="different-caller-action"),
    )
    with pytest.raises(BusinessLogicError):
        _run(alias)
    assert _counts() == (1, 1, 1, 1)


def test_native_concurrent_first_writes_keep_one_complete_set() -> None:
    _, assessment = _native_fixture()
    barrier = Barrier(2)

    def worker() -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=15)
            return _run(assessment).semantic_sha256
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results == [assessment.semantic_sha256] * 2
    assert _counts() == (1, 1, 1, 1)


def test_native_always_guards_reject_raw_mutation_even_in_replica_mode() -> None:
    _, assessment = _native_fixture()
    _run(assessment)
    for statement in (
        "UPDATE sim_ca_tax_assessment SET semantic_sha256=repeat('0',64)",
        "DELETE FROM sim_ca_tax_assess_allocation",
    ):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL session_replication_role='replica'")
                    cursor.execute(statement)
    assert _counts() == (1, 1, 1, 1)


def test_native_later_partial_sale_has_its_own_fifo_assessment_and_audit_stream() -> None:
    account, first = _native_fixture()
    _run(first)
    last = first.history.settlement_days[-1]
    next_day = replace(
        last,
        settlement_date=date(2025, 3, 4),
        opening_eod_quantity=Decimal("60"),
        gross_purchase_quantity=Decimal("0"),
        gross_sale_quantity=Decimal("5"),
        closing_eod_quantity=Decimal("55"),
        evidence_id="synthetic-later-partial-sale",
        evidence_sha256="f" * 64,
    )
    history = replace(
        first.history,
        complete_through=next_day.settlement_date,
        covered_session_dates=first.history.covered_session_dates + (next_day.settlement_date,),
        settlement_days=first.history.settlement_days + (next_day,),
    )
    second = replace(
        first,
        assessment_revision_id="partial-sale-2",
        history=history,
        target_settlement_date=next_day.settlement_date,
    )
    _run(second)
    assert second.calculation.allocations[0].sold_quantity == Decimal("5")
    assert second.calculation.disposition_id != first.calculation.disposition_id
    assert _counts() == (2, 2, 2, 2)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100")


def test_native_allocation_insert_failure_rolls_back_header_and_all_audit_writes() -> None:
    _, assessment = _native_fixture()
    with patch.object(
        Allocation, "save", side_effect=IntegrityError("controlled allocation failure")
    ):
        with pytest.raises(IntegrityError):
            _run(assessment)
    assert _counts() == (0, 0, 0, 0)


def test_native_physical_account_owner_cannot_be_substituted_by_consistent_dtos() -> None:
    _, assessment = _native_fixture()
    other = get_user_model().objects.create_user(username=f"other-tax-{uuid4()}")
    history = assessment.history
    crossed = replace(
        assessment,
        action=replace(assessment.action, owner_user_id=other.pk),
        history=replace(
            history,
            owner_user_id=other.pk,
            opening_anchor=replace(history.opening_anchor, owner_user_id=other.pk),
            record_date_ownership_proof=replace(
                history.record_date_ownership_proof, owner_user_id=other.pk
            ),
            settlement_days=tuple(
                replace(day, owner_user_id=other.pk) for day in history.settlement_days
            ),
        ),
    )
    with pytest.raises(BusinessLogicError):
        _run(crossed)
    assert _counts() == (0, 0, 0, 0)
