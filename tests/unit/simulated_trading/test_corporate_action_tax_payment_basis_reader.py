"""Pure contracts for the audited cash-payment history reader."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.audit.domain.system_audit_event import AuditEvidenceRef, AuditScopeRef
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionLedgerDelta,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from apps.simulated_trading.infrastructure import (
    corporate_action_tax_payment_basis_reader as reader,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from core.exceptions import BusinessLogicError

_RECORD_DATE = date(2026, 11, 11)
_PAYMENT_DATE = date(2026, 11, 12)
_SOURCE_OBSERVED = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
_QUALIFIED = datetime(2026, 11, 12, 3, 1, tzinfo=UTC)
_POSTED = datetime(2026, 11, 12, 3, 2, tzinfo=UTC)
_AUDIT_RECORDED = datetime(2026, 11, 12, 3, 10, tzinfo=UTC)


def _request(
    stage: CorporateActionStage,
    *,
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    revision_id: str = "revision-1",
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
) -> CorporateActionStageRequest:
    """Build one structurally valid synthetic cash stage for pure history checks."""

    reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    entitlement = stage is CorporateActionStage.CASH_ENTITLEMENT
    return CorporateActionStageRequest(
        account_id=7,
        owner_user_id=11,
        security_id="600000.SH",
        asset_code="equity-cn",
        asset_name="Synthetic Equity",
        source_namespace="exchange_official_disclosure",
        source_record_id="source-record-1",
        source_event_id="source-event-1",
        source_revision_id=revision_id,
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=_SOURCE_OBSERVED,
        qualified_at=_QUALIFIED,
        posted_at=_POSTED,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD_DATE,
        effective_date=_PAYMENT_DATE,
        stage_date=_RECORD_DATE if entitlement else _PAYMENT_DATE,
        cash_amount=None if reversal else Decimal("35.00"),
        payment_date=(_PAYMENT_DATE if not entitlement and not reversal else None),
        tax_treatment=None if reversal else "deferred_withholding",
        ownership_snapshot_id=("snapshot-1" if entitlement and not reversal else None),
        ownership_snapshot_sha256=("c" * 64 if entitlement and not reversal else None),
        ownership_snapshot_as_of_date=(_RECORD_DATE if entitlement and not reversal else None),
        ownership_snapshot_observed_at=(_QUALIFIED if entitlement and not reversal else None),
        eligible_quantity=(Decimal("70.000000") if entitlement and not reversal else None),
        entitlement_calculation_sha256=("d" * 64 if entitlement and not reversal else None),
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _row(
    entry_id: int,
    account_revision: int,
    request: CorporateActionStageRequest,
    *,
    reversal_target: CorporateActionPostingModel | None = None,
) -> CorporateActionPostingModel:
    """Build the immutable row fields consumed by the pure revision validator."""

    if request.entry_kind is CorporateActionEntryKind.REVERSAL:
        if reversal_target is None:
            raise AssertionError("a fixture reversal needs its exact target row")
        delta = CorporateActionLedgerDelta(
            cash=-reversal_target.cash_delta,
            cash_receivable=-reversal_target.cash_receivable_delta,
            shares=-reversal_target.share_delta,
            share_receivable=-reversal_target.share_receivable_delta,
            available_shares=-reversal_target.available_share_delta,
        )
    else:
        delta = calculate_corporate_action_delta(request)
    return cast(
        CorporateActionPostingModel,
        SimpleNamespace(
            pk=entry_id,
            account_revision=account_revision,
            source_revision_id=request.source_revision_id,
            cash_delta=delta.cash,
            cash_receivable_delta=delta.cash_receivable,
            share_delta=delta.shares,
            share_receivable_delta=delta.share_receivable,
            available_share_delta=delta.available_shares,
        ),
    )


def _grant(
    *,
    version: str = "grant-v1",
    recorded_at: datetime = _SOURCE_OBSERVED,
    predecessor_hash: str | None = None,
) -> SimulatedCorporateActionWriteGrant:
    """Build one exact historical V1 cash grant for Audit restoration tests."""

    binding = SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id="canonical-account-7",
        owner_user_id=11,
        tenant_id="tenant-7",
        owner_id="owner-11",
        account_source_id="account-source-7",
        account_source_version="source-v1",
        account_source_content_hash="a" * 64,
        policy_id="cash-policy-1",
        policy_version="policy-v1",
        policy_content_hash="b" * 64,
    )
    return SimulatedCorporateActionWriteGrant(
        grant_id="cash-grant-7",
        grant_version=version,
        binding=binding,
        consent_evidence_id=f"consent-{version}",
        consent_evidence_version="consent-v1",
        consent_evidence_hash="c" * 64,
        issuer_evidence_id="issuer-7",
        issuer_evidence_version="issuer-v1",
        issuer_evidence_hash="d" * 64,
        consented_at=recorded_at - timedelta(minutes=2),
        issued_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
        supersedes_content_hash=predecessor_hash,
    )


def _grant_event(grant: SimulatedCorporateActionWriteGrant) -> SimpleNamespace:
    """Build one exact Audit evidence link to a historical owner grant."""

    return SimpleNamespace(
        evidence_refs=(
            AuditEvidenceRef(
                owner="account",
                artifact_type="simulated_corporate_action_write_grant",
                artifact_id=grant.grant_id,
                artifact_version=grant.grant_version,
                content_hash=grant.content_hash,
            ),
        ),
        recorded_at=_AUDIT_RECORDED,
    )


def test_current_cash_revision_has_one_active_entitlement_and_payment() -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    payment = _request(CorporateActionStage.CASH_PAYMENT)
    rows = (_row(101, 4, entitlement), _row(102, 5, payment))
    requests = {101: entitlement, 102: payment}

    active, head = reader._verify_event_revision_chain(
        rows,
        requests,
        expected_head_revision_id="revision-1",
    )

    assert set(active) == {101, 102}
    assert head == "revision-1"


def test_cash_revision_rejects_duplicate_stage_and_wrong_source_head() -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    duplicate = _request(CorporateActionStage.CASH_ENTITLEMENT)
    rows = (_row(101, 4, entitlement), _row(102, 5, duplicate))

    with pytest.raises(BusinessLogicError, match="repeats a cash stage"):
        reader._verify_event_revision_chain(
            rows,
            {101: entitlement, 102: duplicate},
            expected_head_revision_id="revision-1",
        )

    payment = _request(CorporateActionStage.CASH_PAYMENT)
    with pytest.raises(BusinessLogicError, match="historical event head"):
        reader._verify_event_revision_chain(
            (_row(101, 4, entitlement), _row(102, 5, payment)),
            {101: entitlement, 102: payment},
            expected_head_revision_id="different-revision",
        )


def test_cash_revision_requires_every_active_row_to_be_reversed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    payment = _request(CorporateActionStage.CASH_PAYMENT)
    reverse_entitlement = _request(
        CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=101,
    )
    successor_entitlement = replace(
        entitlement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    successor_payment = replace(
        payment,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    monkeypatch.setattr(reader, "_ledger_row_matches_request", lambda *args, **kwargs: True)
    entitlement_row = _row(101, 4, entitlement)
    rows = (
        entitlement_row,
        _row(102, 5, payment),
        _row(103, 6, reverse_entitlement, reversal_target=entitlement_row),
        _row(104, 7, successor_entitlement),
        _row(105, 8, successor_payment),
    )

    with pytest.raises(BusinessLogicError, match="reverse every active stage exactly once"):
        reader._verify_event_revision_chain(
            rows,
            {
                101: entitlement,
                102: payment,
                103: reverse_entitlement,
                104: successor_entitlement,
                105: successor_payment,
            },
            expected_head_revision_id="revision-2",
        )


def test_complete_cash_correction_leaves_only_successor_stages_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    payment = _request(CorporateActionStage.CASH_PAYMENT)
    reverse_entitlement = _request(
        CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=101,
    )
    reverse_payment = _request(
        CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=102,
    )
    successor_entitlement = replace(
        entitlement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    successor_payment = replace(
        payment,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    monkeypatch.setattr(reader, "_ledger_row_matches_request", lambda *args, **kwargs: True)
    entitlement_row = _row(101, 4, entitlement)
    payment_row = _row(102, 5, payment)
    rows = (
        entitlement_row,
        payment_row,
        _row(103, 6, reverse_payment, reversal_target=payment_row),
        _row(104, 7, reverse_entitlement, reversal_target=entitlement_row),
        _row(105, 8, successor_entitlement),
        _row(106, 9, successor_payment),
    )

    active, head = reader._verify_event_revision_chain(
        rows,
        {
            101: entitlement,
            102: payment,
            103: reverse_payment,
            104: reverse_entitlement,
            105: successor_entitlement,
            106: successor_payment,
        },
        expected_head_revision_id="revision-2",
    )

    assert set(active) == {105, 106}
    assert head == "revision-2"


def test_cash_event_history_rejects_asset_identity_change_in_a_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    reversal = _request(
        CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=101,
    )
    successor = replace(
        entitlement,
        asset_code="000001.SZ",
        security_id="000001.SZ",
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    monkeypatch.setattr(reader, "_ledger_row_matches_request", lambda *args, **kwargs: True)
    entitlement_row = _row(101, 1, entitlement)
    rows = (
        entitlement_row,
        _row(102, 2, reversal, reversal_target=entitlement_row),
        _row(103, 3, successor),
    )

    with pytest.raises(BusinessLogicError, match="asset identity changed across source revisions"):
        reader._verify_event_revision_chain(
            rows,
            {101: entitlement, 102: reversal, 103: successor},
            expected_head_revision_id="revision-2",
        )


@pytest.mark.parametrize("payment_account_revision", (4, 5))
def test_corrected_head_accepts_later_posting_payment_across_account_revision_gap(
    monkeypatch: pytest.MonkeyPatch,
    payment_account_revision: int,
) -> None:
    """A corrected entitlement may be followed by its payment on the same head."""

    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    correction_common = {
        "source_record_id": "source-record-2",
        "source_revision_id": "revision-2",
        "supersedes_revision_id": "revision-1",
        "source_payload_sha256": "f" * 64,
        "qualification_sha256": "e" * 64,
        "source_observed_at": datetime(2026, 11, 12, 3, 3, tzinfo=UTC),
        "qualified_at": datetime(2026, 11, 12, 3, 4, tzinfo=UTC),
        "posted_at": datetime(2026, 11, 12, 3, 5, tzinfo=UTC),
    }
    reversal = replace(
        entitlement,
        **correction_common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        tax_treatment=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        reversal_of_entry_id=101,
    )
    successor = replace(
        entitlement,
        **correction_common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
    )
    payment = replace(
        successor,
        stage=CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage_date=_PAYMENT_DATE,
        payment_date=_PAYMENT_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        supersedes_revision_id=None,
    )
    monkeypatch.setattr(reader, "_ledger_row_matches_request", lambda *args, **kwargs: True)
    entitlement_row = _row(101, 1, entitlement)
    rows = (
        entitlement_row,
        _row(102, 2, reversal, reversal_target=entitlement_row),
        _row(103, 3, successor),
        # Account revision 4 is another action when payment_account_revision is 5.
        _row(104, payment_account_revision, payment),
    )

    active, head = reader._verify_event_revision_chain(
        rows,
        {101: entitlement, 102: reversal, 103: successor, 104: payment},
        expected_head_revision_id="revision-2",
    )

    assert set(active) == {103, 104}
    assert head == "revision-2"


def test_corrected_head_rejects_incomplete_or_mixed_correction_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entitlement = _request(CorporateActionStage.CASH_ENTITLEMENT)
    reversal = _request(
        CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        reversal_of_entry_id=101,
    )
    successor = replace(
        entitlement,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        source_revision_id="revision-2",
        supersedes_revision_id="revision-3",
    )
    monkeypatch.setattr(reader, "_ledger_row_matches_request", lambda *args, **kwargs: True)

    with pytest.raises(BusinessLogicError, match="reverse every active stage exactly once"):
        entitlement_row = _row(101, 1, entitlement)
        reversal_row = _row(102, 2, reversal, reversal_target=entitlement_row)
        reader._verify_event_revision_chain(
            (entitlement_row, reversal_row),
            {101: entitlement, 102: reversal},
            expected_head_revision_id="revision-2",
        )

    with pytest.raises(BusinessLogicError, match="mixed or stale predecessor"):
        entitlement_row = _row(101, 1, entitlement)
        reversal_row = _row(102, 2, reversal, reversal_target=entitlement_row)
        reader._verify_event_revision_chain(
            (entitlement_row, reversal_row, _row(103, 3, successor)),
            {101: entitlement, 102: reversal, 103: successor},
            expected_head_revision_id="revision-2",
        )


def test_current_pair_rejects_an_already_active_tax_withholding_stage() -> None:
    def verified(stage: CorporateActionStage) -> reader._VerifiedPosting:
        return cast(
            reader._VerifiedPosting,
            SimpleNamespace(request=SimpleNamespace(stage=stage)),
        )

    active_rows = {entry_id: cast(CorporateActionPostingModel, object()) for entry_id in (1, 2, 3)}
    verified_rows = {
        1: verified(CorporateActionStage.CASH_ENTITLEMENT),
        2: verified(CorporateActionStage.CASH_PAYMENT),
        3: verified(CorporateActionStage.TAX_WITHHOLDING),
    }

    with pytest.raises(BusinessLogicError, match="already contains an active tax-withholding"):
        reader._current_paid_pair(active_rows=active_rows, verified=verified_rows)


def test_row_reconstruction_requires_entitlement_proof_but_allows_payment_null() -> None:
    def row_for(request: CorporateActionStageRequest) -> SimpleNamespace:
        values = {field.name: getattr(request, field.name) for field in fields(request)}
        values.pop("owner_user_id")
        values["reversal_of_id"] = values.pop("reversal_of_entry_id")
        return SimpleNamespace(**values)

    entitlement_row = row_for(_request(CorporateActionStage.CASH_ENTITLEMENT))
    entitlement_row.entitlement_calculation_sha256 = None
    with pytest.raises(BusinessLogicError, match="valid complete request"):
        reader._request_from_row(entitlement_row, owner_user_id=11)

    payment_row = row_for(_request(CorporateActionStage.CASH_PAYMENT))
    payment = reader._request_from_row(payment_row, owner_user_id=11)

    assert payment.stage is CorporateActionStage.CASH_PAYMENT
    assert payment.entitlement_calculation_sha256 is None


def test_historical_v1_cash_grant_remains_valid_after_later_withdrawal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant = _grant()
    later_withdrawal = SimpleNamespace(recorded_at=_AUDIT_RECORDED + timedelta(days=1))
    record = SimpleNamespace(grant=grant, revocation=later_withdrawal)
    monkeypatch.setattr(
        reader,
        "read_simulated_corporate_action_grant_scope_records",
        lambda **kwargs: (record,),
    )

    restored = reader._historical_grant(
        event=_grant_event(grant),
        using="qa",
        account_namespace="simulated",
        account_id="canonical-account-7",
        owner_user_id=11,
        audit_scope=AuditScopeRef(tenant_id="tenant-7", owner_id="owner-11"),
    )

    assert restored == grant
    assert restored.supports_capability(SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE)
    assert not restored.supports_capability(SimulatedCorporateActionWriteCapability.TAX_WITHHOLD)


def test_historical_grant_rejects_withdrawal_at_audit_time_and_prior_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant = _grant()
    scope = AuditScopeRef(tenant_id="tenant-7", owner_id="owner-11")
    event = _grant_event(grant)
    monkeypatch.setattr(
        reader,
        "read_simulated_corporate_action_grant_scope_records",
        lambda **kwargs: (SimpleNamespace(grant=grant, revocation=event),),
    )

    with pytest.raises(BusinessLogicError, match="was not active"):
        reader._historical_grant(
            event=event,
            using="qa",
            account_namespace="simulated",
            account_id="canonical-account-7",
            owner_user_id=11,
            audit_scope=scope,
        )

    successor = _grant(
        version="grant-v2",
        recorded_at=_AUDIT_RECORDED,
        predecessor_hash=grant.content_hash,
    )
    monkeypatch.setattr(
        reader,
        "read_simulated_corporate_action_grant_scope_records",
        lambda **kwargs: (
            SimpleNamespace(grant=grant, revocation=None),
            SimpleNamespace(grant=successor, revocation=None),
        ),
    )

    with pytest.raises(BusinessLogicError, match="superseded"):
        reader._historical_grant(
            event=event,
            using="qa",
            account_namespace="simulated",
            account_id="canonical-account-7",
            owner_user_id=11,
            audit_scope=scope,
        )
