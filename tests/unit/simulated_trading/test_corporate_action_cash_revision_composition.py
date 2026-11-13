"""Pure cash-revision scope, source-lineage, and composition contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.simulated_trading import audited_corporate_action_posting_composition as audited
from apps.simulated_trading import official_disclosure_action_composition as official
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    build_audited_cash_revision_use_case,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_RECORD_DATE = date(2026, 9, 23)
_EX_DATE = date(2026, 9, 24)
_PAYMENT_DATE = date(2026, 9, 25)
_T0 = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_T1 = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)
_T2 = datetime(2026, 11, 10, 1, 20, tzinfo=UTC)
_T3 = datetime(2026, 11, 10, 1, 30, tzinfo=UTC)
_T4 = datetime(2026, 11, 10, 1, 40, tzinfo=UTC)
_T5 = datetime(2026, 11, 10, 1, 50, tzinfo=UTC)


@pytest.mark.parametrize(
    "stage, inverse",
    [
        (
            CorporateActionStage.CASH_ENTITLEMENT,
            CorporateActionLedgerDelta(cash_receivable=Decimal("-200.00")),
        ),
        (
            CorporateActionStage.CASH_PAYMENT,
            CorporateActionLedgerDelta(cash=Decimal("-200.00"), cash_receivable=Decimal("200.00")),
        ),
    ],
)
def test_replay_row_verification_accepts_the_actual_inverse_delta(stage, inverse):
    """A reversal persists its predecessor's inverse, rather than a zero request delta."""
    original = _stage_request(
        _lineage()[0].event,
        logical_event_id="notice-root",
        terms=_terms(),
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=stage,
    )
    reversal = _stage_request(
        _lineage()[1].event,
        logical_event_id="notice-root",
        terms=_terms(),
        entry_kind=CorporateActionEntryKind.REVERSAL,
        stage=stage,
        supersedes_revision_id=original.source_revision_id,
        reversal_of_entry_id=101,
    )
    account = SimulatedAccountModel(pk=11, user_id=21)
    target = DjangoCorporateActionPostingRepository._make_row(
        request=original,
        account=account,
        account_revision=1,
        delta=calculate_corporate_action_delta(original),
        reverses=None,
    )
    target.pk = 101
    row = DjangoCorporateActionPostingRepository._make_row(
        request=reversal,
        account=account,
        account_revision=2,
        delta=inverse,
        reverses=target,
    )
    row.pk = 102
    assert audited._ledger_row_matches_request(row, reversal, reversal_target=target)
    assert not audited._ledger_row_matches_request(row, reversal)
    target.source_namespace = "another-source"
    assert not audited._ledger_row_matches_request(row, reversal, reversal_target=target)
    target.source_namespace = original.source_namespace
    target.pk = 999
    assert not audited._ledger_row_matches_request(row, reversal, reversal_target=target)
    target.pk = 101
    row.cash_receivable_delta += Decimal("0.01")
    assert not audited._ledger_row_matches_request(row, reversal, reversal_target=target)


def _document(
    document_id: str,
    body: bytes,
    *,
    first_seen_at: datetime,
    recorded_at: datetime,
    supersedes: tuple[str, str] | None = None,
) -> PersistedSecurityDisclosureEvent:
    """Build one synthetic immutable disclosure revision and its knowledge clock."""

    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id=document_id,
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type="synthetic cash dividend notice",
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        source_url=f"https://disc.static.szse.cn/synthetic/{document_id}.PDF",
        source_document_body=body,
        first_seen_at=first_seen_at,
        announced_at=date(2026, 9, 17),
        source_available_at=date(2026, 9, 17),
        effective_at=_EX_DATE,
        supersedes_source_event_id=supersedes[0] if supersedes else None,
        supersedes_source_revision_id=supersedes[1] if supersedes else None,
    )
    return PersistedSecurityDisclosureEvent(event=event, recorded_at=recorded_at)


def _lineage() -> tuple[PersistedSecurityDisclosureEvent, ...]:
    """Build a synthetic root and two explicitly linked corrected source records."""

    first = _document(
        "notice-root",
        b"synthetic-root",
        first_seen_at=_T0,
        recorded_at=_T0 + timedelta(seconds=1),
    )
    second = _document(
        "notice-correction-one",
        b"synthetic-correction-one",
        first_seen_at=_T1,
        recorded_at=_T1 + timedelta(seconds=1),
        supersedes=(first.event.source_event_id, first.event.source_revision_id),
    )
    third = _document(
        "notice-correction-two",
        b"synthetic-correction-two",
        first_seen_at=_T2,
        recorded_at=_T2 + timedelta(seconds=1),
        supersedes=(second.event.source_event_id, second.event.source_revision_id),
    )
    return first, second, third


def _terms() -> SzseDistributionTerms:
    """Build explicit synthetic parsed source terms for the qualified fixture."""

    return SzseDistributionTerms(
        record_date=_RECORD_DATE,
        ex_date=_EX_DATE,
        payment_date=_PAYMENT_DATE,
        cash_per_ten=Decimal("2.00"),
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )


def _stage_request(
    event: SecurityDisclosureEvent,
    *,
    logical_event_id: str,
    terms: SzseDistributionTerms,
    entry_kind: CorporateActionEntryKind,
    stage: CorporateActionStage,
    qualified_at: datetime = _T3,
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    cash_amount: Decimal | None = Decimal("200.00"),
) -> CorporateActionStageRequest:
    """Bind a cash request's logical root separately from its exact source record."""

    entitlement = stage is CorporateActionStage.CASH_ENTITLEMENT
    reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    return CorporateActionStageRequest(
        account_id=11,
        owner_user_id=21,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=logical_event_id,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.source_body_sha256,
        qualification_sha256=official.szse_action_qualification_sha256(event, terms),
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=event.first_seen_at,
        qualified_at=qualified_at,
        posted_at=qualified_at + timedelta(seconds=1),
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=stage,
        entry_kind=entry_kind,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=terms.record_date if entitlement else terms.payment_date or _PAYMENT_DATE,
        cash_amount=None if reversal else cash_amount,
        payment_date=(terms.payment_date if not entitlement and not reversal else None),
        tax_treatment=None if reversal else terms.tax_treatment,
        ownership_snapshot_id=(
            f"snapshot:{event.source_event_id}:{_RECORD_DATE.isoformat()}"
            if entitlement and not reversal
            else None
        ),
        ownership_snapshot_sha256=("d" * 64 if entitlement and not reversal else None),
        ownership_snapshot_as_of_date=(terms.record_date if entitlement and not reversal else None),
        ownership_snapshot_observed_at=(qualified_at if entitlement and not reversal else None),
        eligible_quantity=(Decimal("1000.000000") if entitlement and not reversal else None),
        entitlement_calculation_sha256=("e" * 64 if entitlement and not reversal else None),
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


class _DisclosureReader:
    """Return a complete deterministic synthetic Data Center read for unit tests."""

    def __init__(self, events: tuple[PersistedSecurityDisclosureEvent, ...]) -> None:
        self.events = events

    def execute(self, scope: object) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        del scope
        return self.events


def test_correction_source_uses_complete_chain_and_actual_current_record_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two revisions bind to the logical root while source_record_id names the current PDF."""

    events = _lineage()
    current = events[-1].event
    terms = replace(_terms(), cash_per_ten=Decimal("2.50"))
    reader = _DisclosureReader(events)
    monkeypatch.setattr(official, "make_security_disclosure_event_reader", lambda **kwargs: reader)
    monkeypatch.setattr(
        official,
        "read_verified_szse_distribution",
        lambda event, *, body_store_root: terms,
    )
    monkeypatch.setattr(official.timezone, "now", lambda: _T5)
    qualifier = official.VerifiedSzseActionSourceQualifier(body_store_root=Path("."))

    reversal = _stage_request(
        current,
        logical_event_id=events[0].event.source_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        supersedes_revision_id=events[-2].event.source_revision_id,
        reversal_of_entry_id=101,
        qualified_at=_T3,
    )
    successor = _stage_request(
        current,
        logical_event_id=events[0].event.source_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        supersedes_revision_id=events[-2].event.source_revision_id,
        qualified_at=_T3,
        cash_amount=Decimal("250.00"),
    )
    later_payment = _stage_request(
        current,
        logical_event_id=events[0].event.source_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=CorporateActionStage.CASH_PAYMENT,
        qualified_at=_T3,
        cash_amount=Decimal("250.00"),
    )

    assert reversal.source_event_id == events[0].event.source_event_id
    assert reversal.source_record_id == current.source_event_id
    assert qualifier.verify_source(reversal)
    assert qualifier.verify_source(successor)
    assert qualifier.verify_source(later_payment)
    assert not qualifier.verify_source(
        replace(reversal, supersedes_revision_id=events[0].event.source_revision_id)
    )
    assert not qualifier.verify_source(replace(successor, source_record_id="wrong-current-pdf"))

    qualifier._reader.events = (events[0], events[-1])
    assert not qualifier.verify_source(successor)

    late_ancestor = replace(events[-2], recorded_at=_T4)
    qualifier._reader.events = (events[0], late_ancestor, events[-1])
    assert not qualifier.verify_source(successor)

    branch = _document(
        "notice-branch",
        b"synthetic competing correction",
        first_seen_at=_T1,
        recorded_at=_T1 + timedelta(seconds=1),
        supersedes=(events[0].event.source_event_id, events[0].event.source_revision_id),
    )
    qualifier._reader.events = events + (branch,)
    assert not qualifier.verify_source(successor)

    qualifier._reader.events = events + (
        _document(
            "notice-correction-three",
            b"later synthetic correction",
            first_seen_at=_T4,
            recorded_at=_T4 + timedelta(seconds=1),
            supersedes=(current.source_event_id, current.source_revision_id),
        ),
    )
    assert not qualifier.verify_source(successor)


def test_tax_action_uses_actual_current_record_body_terms_and_complete_logical_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _lineage()
    event = events[-1].event
    terms = replace(_terms(), cash_per_ten=Decimal("2.50"))
    reader = _DisclosureReader(events)
    monkeypatch.setattr(official, "make_security_disclosure_event_reader", lambda **kwargs: reader)
    monkeypatch.setattr(official, "read_verified_szse_distribution", lambda *args, **kwargs: terms)
    monkeypatch.setattr(official.timezone, "now", lambda: _T5)
    qualifier = official.VerifiedSzseActionSourceQualifier(body_store_root=Path("."))
    action = QualifiedCorporateActionTaxFacts(
        account_id=11,
        owner_user_id=21,
        security_id="internal-security-11",
        asset_code=event.asset_code,
        corporate_action_id="logical-dividend-root",
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=events[0].event.source_event_id,
        source_revision_id=event.source_revision_id,
        source_revision_sha256=event.content_hash,
        source_payload_sha256=event.source_body_sha256,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        dividend_per_share=Decimal("0.25"),
    )
    assert qualifier.verify_tax_action(action, as_of=_T3)
    assert not qualifier.verify_tax_action(
        replace(action, dividend_per_share=Decimal("0.24")), as_of=_T3
    )
    assert not qualifier.verify_tax_action(
        replace(action, source_revision_sha256="a" * 64), as_of=_T3
    )
    assert not qualifier.verify_tax_action(action, as_of=_T5 + timedelta(seconds=1))
    reader.events = (events[0], events[-1])
    assert not qualifier.verify_tax_action(action, as_of=_T3)
    reader.events = events
    monkeypatch.setattr(official, "read_verified_szse_distribution", lambda *args, **kwargs: None)
    assert not qualifier.verify_tax_action(action, as_of=_T3)


def test_cash_revision_preparation_normalizes_financial_order_and_restores_receipts() -> None:
    """The audited boundary canonicalizes dependencies without changing caller receipt order."""

    events = _lineage()
    logical_event_id = events[0].event.source_event_id
    predecessor = events[-2].event.source_revision_id
    current = events[-1].event
    terms = _terms()
    correction_common = {
        "qualified_at": _T3,
        "supersedes_revision_id": predecessor,
    }
    reversal_entitlement = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        reversal_of_entry_id=101,
        **correction_common,
    )
    reversal_payment = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        stage=CorporateActionStage.CASH_PAYMENT,
        reversal_of_entry_id=102,
        **correction_common,
    )
    successor_entitlement = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        cash_amount=Decimal("250.00"),
        **correction_common,
    )
    successor_payment = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        stage=CorporateActionStage.CASH_PAYMENT,
        cash_amount=Decimal("250.00"),
        **correction_common,
    )
    submitted = (
        successor_payment,
        reversal_entitlement,
        successor_entitlement,
        reversal_payment,
    )

    canonical, representative = audited._prepare_cash_revision_requests(submitted)

    assert canonical == (
        reversal_payment,
        reversal_entitlement,
        successor_entitlement,
        successor_payment,
    )
    assert representative is successor_entitlement
    canonical_receipts = tuple(
        CorporateActionPostingReceipt(
            entry_id=index,
            account_revision=index,
            stage_key=request.stage_key,
            request_payload_sha256=request.payload_sha256,
            replayed=index % 2 == 0,
        )
        for index, request in enumerate(canonical, start=1)
    )
    restored = audited._restore_cash_revision_receipt_order(submitted, canonical_receipts)
    assert tuple(receipt.stage_key for receipt in restored) == tuple(
        request.stage_key for request in submitted
    )


def test_cash_revision_preparation_rejects_heterogeneous_source_and_scope() -> None:
    """Correction members cannot mix account, source-record, or predecessor bindings."""

    events = _lineage()
    logical_event_id = events[0].event.source_event_id
    current = events[-1].event
    terms = _terms()
    predecessor = events[-2].event.source_revision_id
    reversal = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        qualified_at=_T3,
        supersedes_revision_id=predecessor,
        reversal_of_entry_id=101,
    )
    successor = _stage_request(
        current,
        logical_event_id=logical_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        qualified_at=_T3,
        supersedes_revision_id=predecessor,
        cash_amount=Decimal("250.00"),
    )

    changed_record_date = successor.record_date + timedelta(days=1)
    for changed in (
        replace(successor, account_id=successor.account_id + 1),
        replace(successor, source_record_id="other-current-record"),
        replace(successor, supersedes_revision_id=events[0].event.source_revision_id),
        replace(
            successor,
            record_date=changed_record_date,
            stage_date=changed_record_date,
            ownership_snapshot_id=(
                f"snapshot:{current.source_event_id}:{changed_record_date.isoformat()}"
            ),
            ownership_snapshot_as_of_date=changed_record_date,
        ),
        replace(successor, effective_date=successor.effective_date + timedelta(days=1)),
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as captured:
            audited._prepare_cash_revision_requests((reversal, changed))
        assert captured.value.code == "CORPORATE_ACTION_BATCH_IDENTITY_INVALID"


def test_share_disclosure_qualification_preserves_exact_tax_treatment() -> None:
    """Cash correction support must not weaken the existing share source qualifier."""

    body = b"synthetic share terms"
    event = SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code="002727.SZ",
        source_security_code="002727",
        source_event_id="synthetic-share-notice",
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type="synthetic stock dividend notice",
        event_type=SecurityDisclosureEventType.STOCK_DIVIDEND,
        source_url="https://disc.static.szse.cn/synthetic/synthetic-share-notice.PDF",
        source_document_body=body,
        first_seen_at=_T0,
        announced_at=date(2026, 9, 17),
        source_available_at=date(2026, 9, 17),
        effective_at=_EX_DATE,
    )
    terms = SzseDistributionTerms(
        record_date=_RECORD_DATE,
        ex_date=_EX_DATE,
        payment_date=None,
        cash_per_ten=None,
        shares_per_ten=Decimal("1.00"),
        tax_treatment="deferred_withholding",
    )
    request = replace(
        _stage_request(
            event,
            logical_event_id=event.source_event_id,
            terms=terms,
            entry_kind=CorporateActionEntryKind.POSTING,
            stage=CorporateActionStage.CASH_ENTITLEMENT,
            qualified_at=_T1,
        ),
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        cash_amount=None,
        share_amount=Decimal("100.00"),
        odd_lot_policy="whole_shares",
    )

    assert official.VerifiedSzseActionSourceQualifier._matches_terms(request, event, terms)
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(
        replace(request, tax_treatment="not_applicable"), event, terms
    )


def test_exact_replay_ledger_query_is_scoped_by_source_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-account logical-event alias in another namespace is outside replay scope."""

    request = _stage_request(
        _lineage()[0].event,
        logical_event_id="notice-root",
        terms=_terms(),
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
    )
    binding = SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id="simulated-account-11",
        owner_user_id=21,
        tenant_id="tenant-11",
        owner_id="owner-11",
        account_source_id="source-11",
        account_source_version="1",
        account_source_content_hash="a" * 64,
        policy_id="policy-11",
        policy_version="1",
        policy_content_hash="b" * 64,
    )
    grant = SimulatedCorporateActionWriteGrant(
        grant_id="grant-11",
        grant_version="1",
        binding=binding,
        consent_evidence_id="consent-11",
        consent_evidence_version="1",
        consent_evidence_hash="c" * 64,
        issuer_evidence_id="issuer-11",
        issuer_evidence_version="1",
        issuer_evidence_hash="d" * 64,
        consented_at=_T0,
        issued_at=_T1,
        recorded_at=_T2,
        valid_until=_T5 + timedelta(days=1),
    )
    captured: dict[str, object] = {}

    class _Query:
        def select_for_update(self):
            return self

        def filter(self, **kwargs):
            captured["filters"] = kwargs
            return self

        def order_by(self, *fields):
            captured["order_by"] = fields
            return ()

    def _using(alias):
        captured["alias"] = alias
        return _Query()

    monkeypatch.setattr(audited.CorporateActionPostingModel._base_manager, "using", _using)
    verifier = audited._DjangoCorporateActionReplayTimestampVerifier(
        coordinator=SimpleNamespace(database_alias="default"),
        posting=DjangoCorporateActionPostingRepository(using="default"),
        requests=(request,),
        representative=request,
        using="default",
    )

    assert verifier.verify_exact_replay(request=request, grant=grant) is None
    assert captured["alias"] == "default"
    assert captured["filters"] == {
        "account_id": request.account_id,
        "source_namespace": request.source_namespace,
        "source_event_id": request.source_event_id,
    }


def test_cash_revision_builder_wires_general_stage_use_case_to_audited_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new public builder composes the existing stage application with owner Audit UOW."""

    class _Repository:
        requests: tuple[CorporateActionStageRequest, ...] | None = None

        def post_revision(
            self, requests: tuple[CorporateActionStageRequest, ...]
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            self.requests = requests
            return ()

    class _Factory:
        def __init__(self, *, environment: str, owner_grant_gate: object) -> None:
            self.environment = environment
            self.owner_grant_gate = owner_grant_gate

    repository = _Repository()
    captured: dict[str, object] = {}

    def _build_use_case(
        *,
        body_store_root: Path,
        runtime_environment: str,
        audited_repository: object,
        using: str,
    ) -> PostCorporateActionStageUseCase:
        captured.update(
            body_store_root=body_store_root,
            runtime_environment=runtime_environment,
            audited_repository=audited_repository,
            using=using,
        )
        return PostCorporateActionStageUseCase(repository)

    monkeypatch.setattr(audited, "DjangoAuditedCorporateActionPostingRepositoryFactory", _Factory)
    monkeypatch.setattr(audited, "build_corporate_action_revision_use_case", _build_use_case)

    use_case = build_audited_cash_revision_use_case(
        body_store_root=Path("synthetic-body-root"),
        runtime_environment="development",
        owner_grant_gate=cast(DjangoCorporateActionOwnerGrantGate, object()),
    )
    request = _stage_request(
        _lineage()[0].event,
        logical_event_id="notice-root",
        terms=_terms(),
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        qualified_at=_T1,
    )

    assert type(use_case) is PostCorporateActionStageUseCase
    use_case.execute((request,))
    assert repository.requests == (request,)
    factory = captured["audited_repository"]
    assert type(factory) is _Factory
    assert factory.environment == "development"
    assert factory.owner_grant_gate is not None
    assert captured["using"] == "default"


def _share_delivery_source_fixture():
    event = replace(_lineage()[0].event, event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    terms = SzseDistributionTerms(
        record_date=_RECORD_DATE,
        ex_date=_EX_DATE,
        payment_date=None,
        cash_per_ten=None,
        shares_per_ten=Decimal("1.00"),
        tax_treatment="not_applicable",
        share_delivery_date=_EX_DATE,
        share_sellable_date=_PAYMENT_DATE,
    )
    request = replace(
        _stage_request(
            event,
            logical_event_id=event.source_event_id,
            terms=terms,
            entry_kind=CorporateActionEntryKind.POSTING,
            stage=CorporateActionStage.CASH_ENTITLEMENT,
        ),
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_DELIVERY,
        stage_date=_EX_DATE,
        cash_amount=None,
        share_amount=Decimal("100"),
        payment_date=None,
        sellable_date=_PAYMENT_DATE,
        odd_lot_policy="whole_shares",
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    return event, terms, request


@pytest.mark.parametrize(
    "defect", ["missing_delivery", "missing_sellable", "wrong_sellable", "unqualified_tax"]
)
def test_share_credit_requires_exact_independent_source_dates_and_tax(defect):
    event, terms, request = _share_delivery_source_fixture()
    assert official.VerifiedSzseActionSourceQualifier._matches_terms(request, event, terms)
    if defect == "missing_delivery":
        terms = replace(terms, share_delivery_date=None)
    elif defect == "missing_sellable":
        terms = replace(terms, share_sellable_date=None)
    elif defect == "wrong_sellable":
        request = replace(request, sellable_date=_PAYMENT_DATE + timedelta(days=1))
    else:
        terms = replace(terms, tax_treatment="deferred_withholding")
        request = replace(request, tax_treatment="deferred_withholding")
    request = replace(
        request, qualification_sha256=official.szse_action_qualification_sha256(event, terms)
    )
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(request, event, terms)


def test_share_qualification_digest_binds_both_independent_dates():
    event, terms, request = _share_delivery_source_fixture()
    original = official.szse_action_qualification_sha256(event, terms)
    assert original != official.szse_action_qualification_sha256(
        event, replace(terms, share_delivery_date=_EX_DATE + timedelta(days=1))
    )
    assert original != official.szse_action_qualification_sha256(
        event, replace(terms, share_sellable_date=_PAYMENT_DATE + timedelta(days=1))
    )


def test_official_share_delivery_cannot_be_dated_after_shanghai_today(monkeypatch):
    event, terms, request = _share_delivery_source_fixture()
    delivery = _T3.date() + timedelta(days=1)
    sellable = delivery + timedelta(days=1)
    terms = replace(terms, share_delivery_date=delivery, share_sellable_date=sellable)
    request = replace(
        request,
        stage_date=delivery,
        sellable_date=sellable,
        qualification_sha256=official.szse_action_qualification_sha256(event, terms),
    )
    persisted = PersistedSecurityDisclosureEvent(
        event=event, recorded_at=_T0 + timedelta(seconds=1)
    )
    monkeypatch.setattr(
        official,
        "make_security_disclosure_event_reader",
        lambda **kw: _DisclosureReader((persisted,)),
    )
    monkeypatch.setattr(official, "read_verified_szse_distribution", lambda *a, **kw: terms)
    monkeypatch.setattr(official.timezone, "now", lambda: _T3)
    qualifier = official.VerifiedSzseActionSourceQualifier(body_store_root=Path("."))
    assert not qualifier.verify_source(request)


@pytest.mark.parametrize(
    "defect", ["delivery_before_ex", "sellable_before_delivery", "late_delivery", "early_release"]
)
def test_share_stage_cannot_invent_or_reorder_the_official_dates(defect):
    """A known date is not permission to shift delivery or unlock shares early."""
    event, terms, request = _share_delivery_source_fixture()
    if defect == "delivery_before_ex":
        terms = replace(terms, share_delivery_date=_EX_DATE - timedelta(days=1))
    elif defect == "sellable_before_delivery":
        terms = replace(terms, share_sellable_date=_EX_DATE - timedelta(days=1))
    elif defect == "late_delivery":
        request = replace(request, stage_date=_EX_DATE + timedelta(days=1))
    else:
        request = replace(
            request,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            stage_date=_EX_DATE,
            sellable_date=_EX_DATE,
        )
    request = replace(
        request, qualification_sha256=official.szse_action_qualification_sha256(event, terms)
    )
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(request, event, terms)


def test_share_release_uses_the_independent_announced_sellable_day():
    """The unlock is separate from delivery and does not grant registry rounding."""
    event, terms, request = _share_delivery_source_fixture()
    release = replace(
        request, stage=CorporateActionStage.SHARE_SELLABLE_RELEASE, stage_date=_PAYMENT_DATE
    )
    assert official.VerifiedSzseActionSourceQualifier._matches_terms(release, event, terms)
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(
        replace(
            release, odd_lot_policy="registry_final_quantity", odd_lot_confirmation_sha256="a" * 64
        ),
        event,
        terms,
    )


def test_share_entitlement_needs_exact_record_date_quantity_without_guessed_rounding():
    """Missing future delivery dates do not prevent exact whole-share receivable evidence."""
    event, terms, delivery = _share_delivery_source_fixture()
    terms = replace(terms, share_delivery_date=None, share_sellable_date=None)
    original = _stage_request(
        event,
        logical_event_id=event.source_event_id,
        terms=terms,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
    )
    entitlement = replace(
        original,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        cash_amount=None,
        share_amount=Decimal("100.000000"),
        odd_lot_policy="whole_shares",
        qualification_sha256=official.szse_action_qualification_sha256(event, terms),
    )
    assert official.VerifiedSzseActionSourceQualifier._matches_terms(entitlement, event, terms)
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(
        replace(entitlement, eligible_quantity=Decimal("999.999999")), event, terms
    )
    assert not official.VerifiedSzseActionSourceQualifier._matches_terms(
        replace(
            entitlement,
            odd_lot_policy="registry_final_quantity",
            odd_lot_confirmation_sha256="a" * 64,
        ),
        event,
        terms,
    )


def test_official_share_clock_uses_shanghai_day_not_utc_day(monkeypatch):
    """A Shanghai midnight delivery is reached while UTC remains on the previous day."""
    event, terms, request = _share_delivery_source_fixture()
    reached_at = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    delivery_on = date(2026, 11, 11)
    terms = replace(terms, share_delivery_date=delivery_on, share_sellable_date=delivery_on)
    request = replace(
        request,
        stage_date=delivery_on,
        sellable_date=delivery_on,
        qualification_sha256=official.szse_action_qualification_sha256(event, terms),
    )
    persisted = PersistedSecurityDisclosureEvent(
        event=event, recorded_at=_T0 + timedelta(seconds=1)
    )
    monkeypatch.setattr(
        official,
        "make_security_disclosure_event_reader",
        lambda **kw: _DisclosureReader((persisted,)),
    )
    monkeypatch.setattr(official, "read_verified_szse_distribution", lambda *a, **kw: terms)
    monkeypatch.setattr(official.timezone, "now", lambda: reached_at)
    qualifier = official.VerifiedSzseActionSourceQualifier(body_store_root=Path("."))
    assert qualifier.verify_source(request)
    monkeypatch.setattr(official.timezone, "now", lambda: reached_at - timedelta(microseconds=1))
    assert not qualifier.verify_source(request)
