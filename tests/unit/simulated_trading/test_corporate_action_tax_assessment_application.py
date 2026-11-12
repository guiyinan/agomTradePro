from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from apps.simulated_trading.application import corporate_action_tax_assessment as application_module
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    CorporateActionTaxAssessmentUseCase,
    TaxAssessmentAppendDisposition,
    TaxAssessmentWriteLease,
    TaxAssessmentWriteReceipt,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import (
    _assessment,
    _history,
    _source_bundle,
)

_ALIAS = "default"
_PERMISSION = "simulated.corporate_action_tax.assess"
_NOW = datetime(2026, 11, 12, 8, tzinfo=UTC)


class _Clock:
    """Mutable deterministic server clock for half-open deadline tests."""

    def __init__(self) -> None:
        self.current = _NOW

    def now(self) -> datetime:
        return self.current


def _lease(assessment: CorporateActionTaxAssessment) -> TaxAssessmentWriteLease:
    """Build an explicit test-only lease matching every assessment scope field."""

    action = assessment.action
    history = assessment.history
    return TaxAssessmentWriteLease(
        database_alias=_ALIAS,
        actor_user_id=assessment.owner_user_id,
        owner_user_id=assessment.owner_user_id,
        account_id=assessment.account_id,
        asset_code=assessment.asset_code,
        security_id=assessment.security_id,
        corporate_action_id=action.corporate_action_id,
        action_source_namespace=action.source_namespace,
        action_source_record_id=action.source_record_id,
        action_source_event_id=action.source_event_id,
        action_source_revision_id=action.source_revision_id,
        action_source_revision_sha256=action.source_revision_sha256,
        action_source_payload_sha256=action.source_payload_sha256,
        settlement_source_revision_id=history.source_revision_id,
        settlement_source_revision_sha256=history.source_revision_sha256,
        record_date=history.record_date,
        target_settlement_date=assessment.target_settlement_date,
        settlement_date_rule_id=history.settlement_date_rule_id,
        settlement_date_rule_sha256=history.settlement_date_rule_sha256,
        settlement_calendar_id=history.settlement_calendar_id,
        settlement_calendar_sha256=history.settlement_calendar_sha256,
        policy_id=assessment.policy.policy_id,
        policy_version=assessment.policy.version,
        policy_sha256=assessment.policy.policy_sha256,
        statutory_revision_set_sha256=assessment.statutory_source_bundle.source_revision_set_sha256,
        authority_grant_id="synthetic-explicit-tax-consent-v1",
        authority_grant_version="synthetic-grant-version-1",
        permission=_PERMISSION,
        valid_until=_NOW + timedelta(minutes=5),
    )


def test_authority_uses_the_live_grants_opaque_version_not_an_invented_sequence() -> None:
    lease = replace(_lease(_assessment()), authority_grant_version="confirmed-grant-version-2")
    assert lease.authority_grant_version == "confirmed-grant-version-2"
    with pytest.raises(BusinessLogicError):
        replace(lease, authority_grant_version=1)


class _Verifier:
    """Explicit owner-tax-scope test verifier; never a production authority."""

    database_alias = _ALIAS

    def __init__(self, lease: TaxAssessmentWriteLease, *, clock: _Clock) -> None:
        self.lease = lease
        self.clock = clock
        self.calls = 0
        self.advance_to_expiry_on_exit = False

    @contextmanager
    def locked_current_scope(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
        using: str,
    ) -> Iterator[TaxAssessmentWriteLease]:
        self.calls += 1
        assert type(assessment) is CorporateActionTaxAssessment
        assert actor_user_id == assessment.owner_user_id
        assert using == self.database_alias
        yield self.lease
        if self.advance_to_expiry_on_exit:
            self.clock.current = self.lease.valid_until


class _Writer:
    """Atomic test writer which records assessment plus Audit/Outbox append calls."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail_audit = False
        self.result: TaxAssessmentWriteReceipt | None = None

    def append_with_audit_outbox(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        actor_user_id: int,
    ) -> TaxAssessmentWriteReceipt:
        assert actor_user_id == assessment.owner_user_id
        self.events.append("append-header-allocations-audit-outbox")
        if self.fail_audit:
            raise BusinessLogicError("synthetic Audit/Outbox failure")
        if self.result is not None:
            return self.result
        return TaxAssessmentWriteReceipt(
            disposition=TaxAssessmentAppendDisposition.STORED,
            assessment_revision_id=assessment.assessment_revision_id,
            semantic_sha256=assessment.semantic_sha256,
            observation_manifest_sha256=assessment.observation_manifest_sha256,
        )


class _AtomicUnitOfWork:
    """Transaction fake that records commit or rollback boundaries."""

    def __init__(self) -> None:
        self.database_alias = _ALIAS
        self.events: list[str] = []
        self.writer = _Writer(self.events)

    @contextmanager
    def atomic(self, *, using: str) -> Iterator[_Writer]:
        assert using == self.database_alias
        self.events.append("atomic-enter")
        try:
            yield self.writer
        except BaseException:
            self.events.append("atomic-rollback")
            raise
        else:
            self.events.append("atomic-commit")


def _use_case(
    assessment: CorporateActionTaxAssessment,
    *,
    clock: _Clock | None = None,
    verifier: _Verifier | None = None,
    unit_of_work: _AtomicUnitOfWork | None = None,
) -> tuple[CorporateActionTaxAssessmentUseCase, _Verifier, _AtomicUnitOfWork, _Clock]:
    """Assemble a controlled test use case with a distinct tax permission lease."""

    selected_clock = _Clock() if clock is None else clock
    selected_verifier = (
        _Verifier(_lease(assessment), clock=selected_clock) if verifier is None else verifier
    )
    selected_uow = _AtomicUnitOfWork() if unit_of_work is None else unit_of_work
    return (
        CorporateActionTaxAssessmentUseCase(
            scope_verifier=selected_verifier,
            unit_of_work=selected_uow,
            clock=selected_clock,
            using=_ALIAS,
        ),
        selected_verifier,
        selected_uow,
        selected_clock,
    )


def test_write_requires_owner_tax_scope_and_commits_audit_outbox_with_assessment() -> None:
    assessment = _assessment()
    use_case, verifier, uow, _clock = _use_case(assessment)

    receipt = use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert receipt.assessment_revision_id == assessment.assessment_revision_id
    assert receipt.semantic_sha256 == assessment.semantic_sha256
    assert receipt.disposition is TaxAssessmentAppendDisposition.STORED
    assert verifier.calls == 1
    assert uow.events == [
        "atomic-enter",
        "append-header-allocations-audit-outbox",
        "atomic-commit",
    ]


def test_staff_or_other_actor_cannot_use_owner_lease() -> None:
    assessment = _assessment()
    use_case, verifier, uow, _clock = _use_case(assessment)

    with pytest.raises(BusinessLogicError, match="exact assessment owner"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id + 1)

    assert verifier.calls == 0
    assert uow.events == []


def test_wrong_scope_or_cash_permission_is_blocked_before_append() -> None:
    assessment = _assessment()
    clock = _Clock()
    lease = replace(_lease(assessment), policy_sha256="9" * 64)
    verifier = _Verifier(lease, clock=clock)
    use_case, _verifier, uow, _clock = _use_case(
        assessment,
        clock=clock,
        verifier=verifier,
    )

    with pytest.raises(BusinessLogicError, match="scope differs"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert uow.events == ["atomic-enter", "atomic-rollback"]

    with pytest.raises(BusinessLogicError, match="permission"):
        replace(_lease(assessment), permission="simulated.corporate_action.cash.write")


def test_half_open_expiry_is_rechecked_after_locked_context_exits_before_commit() -> None:
    assessment = _assessment()
    clock = _Clock()
    verifier = _Verifier(_lease(assessment), clock=clock)
    verifier.advance_to_expiry_on_exit = True
    use_case, _verifier, uow, _clock = _use_case(
        assessment,
        clock=clock,
        verifier=verifier,
    )

    with pytest.raises(BusinessLogicError, match="expired"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert uow.events == [
        "atomic-enter",
        "append-header-allocations-audit-outbox",
        "atomic-rollback",
    ]


def test_alias_mismatch_blocks_before_atomic_or_audit_outbox() -> None:
    assessment = _assessment()
    clock = _Clock()
    verifier = _Verifier(_lease(assessment), clock=clock)
    uow = _AtomicUnitOfWork()
    uow.database_alias = "other"
    use_case, _verifier, _uow, _clock = _use_case(
        assessment,
        clock=clock,
        verifier=verifier,
        unit_of_work=uow,
    )

    with pytest.raises(BusinessLogicError, match="share one alias"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert uow.events == []


def test_audit_outbox_failure_rolls_back_the_assessment_append() -> None:
    assessment = _assessment()
    use_case, _verifier, uow, _clock = _use_case(assessment)
    uow.writer.fail_audit = True

    with pytest.raises(BusinessLogicError, match="Audit/Outbox failure"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert uow.events == [
        "atomic-enter",
        "append-header-allocations-audit-outbox",
        "atomic-rollback",
    ]


def test_exact_retry_returns_the_original_stored_observation_manifest() -> None:
    first = _assessment()
    retry = _assessment(
        bundle=_source_bundle(
            capture_id=UUID("22222222-2222-4222-8222-222222222222"),
            captured_at=datetime(2026, 11, 13, 1, tzinfo=UTC),
            bundle_id="synthetic-retry-capture",
            bundle_version="capture-v2",
        ),
        history=_history(
            proof_id="synthetic-retry-proof",
            proof_sha256="9" * 64,
            proof_observed_at=datetime(2025, 3, 2, tzinfo=UTC),
        ),
    )
    use_case, _verifier, uow, _clock = _use_case(retry)
    persisted = TaxAssessmentWriteReceipt(
        disposition=TaxAssessmentAppendDisposition.EXACT_RETRY,
        assessment_revision_id=first.assessment_revision_id,
        semantic_sha256=first.semantic_sha256,
        observation_manifest_sha256=first.observation_manifest_sha256,
    )
    uow.writer.result = persisted

    result = use_case.execute(retry, actor_user_id=retry.owner_user_id)

    assert result == persisted
    assert result.observation_manifest_sha256 != retry.observation_manifest_sha256


def test_write_receipt_rejects_invalid_stored_identity_and_retry_semantics() -> None:
    assessment = _assessment()
    use_case, _verifier, uow, _clock = _use_case(assessment)
    uow.writer.result = TaxAssessmentWriteReceipt(
        disposition=TaxAssessmentAppendDisposition.STORED,
        assessment_revision_id="wrong-assessment-revision",
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
    )
    with pytest.raises(BusinessLogicError, match="receipt"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    uow2 = _AtomicUnitOfWork()
    uow2.writer.result = TaxAssessmentWriteReceipt(
        disposition=TaxAssessmentAppendDisposition.EXACT_RETRY,
        assessment_revision_id=assessment.assessment_revision_id,
        semantic_sha256="f" * 64,
        observation_manifest_sha256="e" * 64,
    )
    use_case2, _verifier2, _uow2, _clock2 = _use_case(assessment, unit_of_work=uow2)
    with pytest.raises(BusinessLogicError, match="semantic"):
        use_case2.execute(assessment, actor_user_id=assessment.owner_user_id)


def test_expiry_is_checked_after_final_integrity_recalculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    clock = _Clock()
    lease = _lease(assessment)
    verifier = _Verifier(lease, clock=clock)
    use_case, _verifier, uow, _clock = _use_case(
        assessment,
        clock=clock,
        verifier=verifier,
    )
    original = CorporateActionTaxAssessment.verify_integrity
    calls = 0

    def verify_then_expire(
        record: CorporateActionTaxAssessment,
    ) -> CorporateActionTaxAssessment:
        nonlocal calls
        calls += 1
        result = original(record)
        if calls == 3:
            clock.current = lease.valid_until
        return result

    monkeypatch.setattr(CorporateActionTaxAssessment, "verify_integrity", verify_then_expire)

    with pytest.raises(BusinessLogicError, match="expired"):
        use_case.execute(assessment, actor_user_id=assessment.owner_user_id)

    assert uow.events[-1] == "atomic-rollback"


def test_application_tokens_reject_unencodable_utf8() -> None:
    with pytest.raises(BusinessLogicError, match="invalid"):
        application_module._token("\ud800", field_name="test")
