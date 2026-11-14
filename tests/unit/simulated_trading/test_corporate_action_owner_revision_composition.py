"""Synthetic source tests for full-current-source owner revision preparation."""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureSource,
    SzseDistributionTerms,
)
from apps.simulated_trading import corporate_action_owner_event_requests as event_requests
from apps.simulated_trading import corporate_action_owner_revision_composition as composition
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionOperation,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionOwnershipProofVerifier,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    CorporateActionOwnerEventPreparationBlocked,
    PreparedOwnerOfficialAction,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    OwnerCorporateActionRevisionEntry,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
    calculate_corporate_action_delta,
)
from core.exceptions import BusinessLogicError

_ASSET = "000001.SZ"
_ACCOUNT = 4101
_CANONICAL_ACCOUNT = "account-4101"
_OWNER = 8101
_EVENT_ID = "fca1e323-1c2e-44c8-8c5c-1b73c1699001"
_SOURCE_URL = (
    "https://disc.static.szse.cn/disc/disk03/finalpage/2026-10-15/"
    "fca1e323-1c2e-44c8-8c5c-1b73c1699001.PDF"
)
_AS_OF = datetime(2026, 11, 14, 3, 0, tzinfo=UTC)
_RECORD = date(2026, 10, 30)
_EX = date(2026, 10, 31)
_PAYMENT = date(2026, 11, 5)
_DELIVERY = date(2026, 11, 6)
_SELLABLE = date(2026, 11, 10)
_SOURCE_NAMESPACE = "exchange_official_disclosure"


class _EventReader:
    def __init__(self, rows: tuple[PersistedSecurityDisclosureEvent, ...]) -> None:
        self.rows = rows

    def execute(self, scope: object) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        del scope
        return self.rows


class _OwnershipReader:
    def __init__(self, proof: RecordDateOwnershipProof) -> None:
        self.proof = proof

    def read_verified_zero_origin_calendar(self, **kwargs: object) -> object:
        assert kwargs["account_id"] == _ACCOUNT
        assert kwargs["owner_user_id"] == _OWNER
        assert kwargs["exchange"] == SecurityDisclosureExchange.SZSE.value
        assert kwargs["as_of"] == _AS_OF
        return SimpleNamespace(
            origin_on=date(2026, 1, 1),
            decision_on=date(2026, 11, 14),
            as_of=_AS_OF,
            timezone_policy=SimpleNamespace(
                exchange=SecurityDisclosureExchange.SZSE.value,
                timezone_name="Asia/Shanghai",
            ),
        )

    def read_record_date_ownership_proof(self, **kwargs: object) -> RecordDateOwnershipProof:
        assert kwargs["account_id"] == _ACCOUNT
        assert kwargs["owner_user_id"] == _OWNER
        assert kwargs["security_id"] == _ASSET
        assert kwargs["asset_code"] == _ASSET
        assert kwargs["record_date"] == _RECORD
        assert kwargs["evidence_cutoff_at"] == _AS_OF
        return self.proof


class _ActionQualifier:
    def __init__(self, **kwargs: object) -> None:
        assert kwargs["using"] == "default"
        self.requests: list[CorporateActionStageRequest] = []
        self.accept = True

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        self.requests.append(request)
        return self.accept


def _event(
    *,
    event_type: SecurityDisclosureEventType,
    first_seen_at: datetime,
    prior: SecurityDisclosureEvent | None = None,
) -> SecurityDisclosureEvent:
    """Build explicitly synthetic, non-official-acceptance source facts."""
    body = b"synthetic-only revision test source " + first_seen_at.isoformat().encode("ascii")
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=_ASSET,
        source_security_code=_ASSET[:6],
        source_event_id=_EVENT_ID,
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type=event_type.value,
        event_type=event_type,
        source_url=_SOURCE_URL,
        source_document_body=body,
        first_seen_at=first_seen_at,
        effective_at=_EX,
        supersedes_source_event_id=prior.source_event_id if prior is not None else None,
        supersedes_source_revision_id=prior.source_revision_id if prior is not None else None,
    )


def _proof(
    *,
    account_id: int = _ACCOUNT,
    quantity: Decimal = Decimal("100.000000"),
    observed_at: datetime = _AS_OF,
) -> RecordDateOwnershipProof:
    digest = hashlib.sha256(
        f"synthetic-proof:{account_id}:{_ASSET}:{_RECORD}:{quantity}:{observed_at.isoformat()}".encode(
            "ascii"
        )
    ).hexdigest()
    return RecordDateOwnershipProof(
        account_id=account_id,
        owner_user_id=_OWNER,
        security_id=_ASSET,
        asset_code=_ASSET,
        record_date=_RECORD,
        ownership_snapshot_as_of_date=_RECORD,
        record_date_end_exclusive=datetime(2026, 10, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
        exchange=SecurityDisclosureExchange.SZSE.value,
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-owner-calendar",
        cutoff_policy_sha256="a" * 64,
        eligible_quantity=quantity,
        ownership_snapshot_id=f"synthetic-record-date-proof:{digest}",
        ownership_snapshot_sha256=digest,
        ownership_snapshot_observed_at=observed_at,
    )


def _terms(
    *,
    shares: bool,
    payment_date: date | None = _PAYMENT,
    delivery_date: date = _DELIVERY,
    sellable_date: date = _SELLABLE,
) -> SzseDistributionTerms:
    if shares:
        return SzseDistributionTerms(
            record_date=_RECORD,
            ex_date=_EX,
            payment_date=None,
            cash_per_ten=None,
            shares_per_ten=Decimal("2.00"),
            tax_treatment="not_applicable",
            share_delivery_date=delivery_date,
            share_sellable_date=sellable_date,
        )
    return SzseDistributionTerms(
        record_date=_RECORD,
        ex_date=_EX,
        payment_date=payment_date,
        cash_per_ten=Decimal("2.00"),
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )


def _old_request(
    *,
    event: SecurityDisclosureEvent,
    kind: CorporateActionKind,
    stage: CorporateActionStage,
    amount: Decimal,
    record_date: date = _RECORD,
    effective_date: date = _EX,
) -> CorporateActionStageRequest:
    """Create one retained original stage with exact synthetic economics."""
    stage_date = {
        CorporateActionStage.CASH_ENTITLEMENT: record_date,
        CorporateActionStage.CASH_PAYMENT: _PAYMENT,
        CorporateActionStage.SHARE_ENTITLEMENT: record_date,
        CorporateActionStage.SHARE_DELIVERY: _DELIVERY,
        CorporateActionStage.SHARE_SELLABLE_RELEASE: _SELLABLE,
    }[stage]
    qualified_at = datetime.combine(stage_date, time(9, 0), tzinfo=ZoneInfo("Asia/Shanghai"))
    is_cash = kind is CorporateActionKind.CASH_DIVIDEND
    is_entitlement = stage in {
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.SHARE_ENTITLEMENT,
    }
    return CorporateActionStageRequest(
        account_id=_ACCOUNT,
        owner_user_id=_OWNER,
        security_id=_ASSET,
        asset_code=_ASSET,
        asset_name="Synthetic test security",
        source_namespace=_SOURCE_NAMESPACE,
        source_record_id=event.source_event_id,
        source_event_id=_EVENT_ID,
        source_revision_id=event.source_revision_id,
        source_payload_sha256=event.source_body_sha256,
        qualification_sha256="c" * 64,
        qualifier_identity="szse_official_pdf.v1",
        source_observed_at=event.first_seen_at,
        qualified_at=qualified_at,
        posted_at=qualified_at + timedelta(minutes=5),
        action_kind=kind,
        stage=stage,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=record_date,
        effective_date=effective_date,
        stage_date=stage_date,
        cash_amount=amount if is_cash else None,
        share_amount=None if is_cash else amount,
        payment_date=_PAYMENT if stage is CorporateActionStage.CASH_PAYMENT else None,
        sellable_date=(
            _SELLABLE
            if stage
            in {
                CorporateActionStage.SHARE_DELIVERY,
                CorporateActionStage.SHARE_SELLABLE_RELEASE,
            }
            else None
        ),
        tax_treatment="deferred_withholding" if is_cash else "not_applicable",
        ownership_snapshot_id="synthetic-record-date-proof" if is_entitlement else None,
        ownership_snapshot_sha256="b" * 64 if is_entitlement else None,
        ownership_snapshot_as_of_date=record_date if is_entitlement else None,
        ownership_snapshot_observed_at=event.first_seen_at if is_entitlement else None,
        eligible_quantity=Decimal("100.000000") if is_entitlement else None,
        entitlement_calculation_sha256="d" * 64 if is_entitlement else None,
        odd_lot_policy=None if is_cash else "whole_shares",
    )


def _history(
    event: SecurityDisclosureEvent,
    *,
    kind: CorporateActionKind,
    stages: tuple[CorporateActionStage, ...],
    amount: Decimal,
    payment_date: date = _PAYMENT,
) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
    """Build one fully retained synthetic head with ordered ledger deltas."""
    entries: list[OwnerCorporateActionRevisionEntry] = []
    for index, stage in enumerate(stages, start=1):
        request = _old_request(event=event, kind=kind, stage=stage, amount=amount)
        if stage is CorporateActionStage.CASH_PAYMENT and payment_date != _PAYMENT:
            request = replace(
                request,
                payment_date=payment_date,
                stage_date=payment_date,
                qualified_at=datetime.combine(
                    payment_date, time(9, 0), tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                posted_at=datetime.combine(
                    payment_date, time(9, 5), tzinfo=ZoneInfo("Asia/Shanghai")
                ),
            )
        entries.append(
            OwnerCorporateActionRevisionEntry(
                entry_id=5010 + index,
                account_revision=index,
                request=request,
                delta=calculate_corporate_action_delta(request),
            )
        )
    return tuple(entries)


def _events(
    event_type: SecurityDisclosureEventType,
) -> tuple[PersistedSecurityDisclosureEvent, ...]:
    prior = _event(
        event_type=event_type,
        first_seen_at=_AS_OF - timedelta(days=20),
    )
    current = _event(
        event_type=event_type,
        first_seen_at=_AS_OF - timedelta(days=5),
        prior=prior,
    )
    return (
        PersistedSecurityDisclosureEvent(prior, _AS_OF - timedelta(days=19)),
        PersistedSecurityDisclosureEvent(current, _AS_OF - timedelta(days=4)),
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shares: bool,
    history: tuple[OwnerCorporateActionRevisionEntry, ...],
    payment_date: date | None = _PAYMENT,
    delivery_date: date = _DELIVERY,
    sellable_date: date = _SELLABLE,
    proof: RecordDateOwnershipProof | None = None,
    tax_headers: tuple[object, ...] = (),
    event_records: tuple[PersistedSecurityDisclosureEvent, ...] | None = None,
) -> tuple[_ActionQualifier, RecordDateOwnershipProof]:
    event_type = (
        SecurityDisclosureEventType.STOCK_DIVIDEND
        if shares
        else SecurityDisclosureEventType.CASH_DIVIDEND
    )
    records = event_records if event_records is not None else _events(event_type)
    selected_proof = proof or _proof()
    ownership = _OwnershipReader(selected_proof)
    qualifier = _ActionQualifier(using="default")
    monkeypatch.setattr(composition.transaction, "atomic", lambda *, using: nullcontext())
    monkeypatch.setattr(
        composition,
        "_read_owned_account",
        lambda **kwargs: SimpleNamespace(
            pk=_ACCOUNT,
            user_id=_OWNER,
            account_type="simulated",
            is_active=True,
            cash_known=True,
            cash_reconciliation_status="simulated_ledger",
        ),
    )
    monkeypatch.setattr(
        composition,
        "build_corporate_action_ownership_history_repository",
        lambda **kwargs: ownership,
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_reader",
        lambda *, using: _EventReader(records),
    )
    monkeypatch.setattr(
        composition,
        "_read_policy",
        lambda **kwargs: SimpleNamespace(
            body_store_root=Path("C:/synthetic-source-root"),
        ),
    )
    monkeypatch.setattr(
        composition,
        "security_disclosure_window_pdf_store_root",
        lambda root: root,
    )
    monkeypatch.setattr(
        composition,
        "read_verified_szse_distribution",
        lambda event, *, body_store_root: _terms(
            shares=shares,
            payment_date=payment_date,
            delivery_date=delivery_date,
            sellable_date=sellable_date,
        ),
    )
    monkeypatch.setattr(event_requests, "_asset_name", lambda asset_code: "Synthetic test security")
    monkeypatch.setattr(
        composition, "VerifiedSzseActionSourceQualifier", lambda **kwargs: qualifier
    )

    def readback(**kwargs: object) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
        assert kwargs["canonical_account_id"] == _CANONICAL_ACCOUNT
        assert kwargs["source_namespace"] == _SOURCE_NAMESPACE
        assert kwargs["source_event_id"] == _EVENT_ID
        assert kwargs["as_of"] == _AS_OF
        assert kwargs["using"] == "default"
        return history

    monkeypatch.setattr(
        composition, "read_locked_owner_corporate_action_revision_history", readback
    )
    monkeypatch.setattr(
        composition,
        "_read_existing_tax_action_identities",
        lambda **kwargs: tax_headers,
    )
    return qualifier, selected_proof


def _prepare(
    action: OwnerCorporateActionOperation,
) -> PreparedOwnerOfficialAction:
    return composition.prepare_owner_official_corporate_action_revision(
        account_id=_ACCOUNT,
        canonical_account_id=_CANONICAL_ACCOUNT,
        owner_user_id=_OWNER,
        asset_code=_ASSET,
        event_id=_EVENT_ID,
        action=action,
        as_of=_AS_OF,
        runtime_environment="synthetic-test",
        using="default",
    )


@pytest.mark.parametrize("action", ("cash_entitlement", "cash_payment"))
def test_paid_cash_revision_rebuilds_full_gross_for_both_active_stages(
    monkeypatch: pytest.MonkeyPatch,
    action: OwnerCorporateActionOperation,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT),
        amount=Decimal("10.00"),
    )
    assert sum((entry.delta.cash_receivable for entry in history), Decimal("0")) == 0
    qualifier, _ = _install(monkeypatch, shares=False, history=history)

    result = _prepare(action)

    assert type(result) is PreparedOwnerOfficialAction
    assert result.action == action
    assert result.tax_action is None
    assert result.settlement_date is None
    assert len(result.requests) == 4
    assert tuple(request.stage for request in result.requests) == (
        CorporateActionStage.CASH_PAYMENT,
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.CASH_ENTITLEMENT,
        CorporateActionStage.CASH_PAYMENT,
    )
    assert tuple(request.entry_kind for request in result.requests) == (
        CorporateActionEntryKind.REVERSAL,
        CorporateActionEntryKind.REVERSAL,
        CorporateActionEntryKind.SUCCESSOR,
        CorporateActionEntryKind.SUCCESSOR,
    )
    successors = result.requests[2:]
    assert tuple(request.cash_amount for request in successors) == (
        Decimal("20.00"),
        Decimal("20.00"),
    )
    assert result.source_reference is successors[0]
    assert result.source_reference.stage is CorporateActionStage.CASH_ENTITLEMENT
    assert result.source_reference.source_revision_id == result.event.source_revision_id
    assert len(qualifier.requests) == 2
    assert all(
        request.entry_kind is CorporateActionEntryKind.POSTING for request in qualifier.requests
    )
    assert all(request.qualified_at == _AS_OF for request in qualifier.requests)


def test_actual_ownership_verifier_accepts_fresh_anchor_and_rejects_older_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _, fresh_proof = _install(monkeypatch, shares=False, history=history)
    prepared = _prepare("cash_entitlement")
    fresh_verifier = CorporateActionOwnershipProofVerifier(_OwnershipReader(fresh_proof))

    assert prepared.source_reference.entry_kind is CorporateActionEntryKind.SUCCESSOR
    assert prepared.source_reference.stage is CorporateActionStage.CASH_ENTITLEMENT
    assert prepared.source_reference.ownership_snapshot_observed_at == _AS_OF
    assert prepared.source_reference.qualified_at == _AS_OF
    assert fresh_verifier.verify_ownership(prepared.source_reference) is True

    older_proof = _proof(observed_at=_AS_OF - timedelta(hours=2))
    stale_reference = replace(
        prepared.source_reference,
        ownership_snapshot_id=older_proof.ownership_snapshot_id,
        ownership_snapshot_sha256=older_proof.ownership_snapshot_sha256,
    )
    older_verifier = CorporateActionOwnershipProofVerifier(_OwnershipReader(older_proof))
    assert older_verifier.verify_ownership(stale_reference) is False


def test_older_record_date_proof_blocks_revision_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(
        monkeypatch,
        shares=False,
        history=history,
        proof=_proof(observed_at=_AS_OF - timedelta(hours=2)),
    )

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID"


@pytest.mark.parametrize(
    "action",
    ("share_entitlement", "share_delivery", "share_sellable_release"),
)
def test_fully_delivered_share_revision_rebuilds_full_quantity_and_dates(
    monkeypatch: pytest.MonkeyPatch,
    action: OwnerCorporateActionOperation,
) -> None:
    prior = _events(SecurityDisclosureEventType.STOCK_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stages=(
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        ),
        amount=Decimal("10.000000"),
    )
    assert sum((entry.delta.share_receivable for entry in history), Decimal("0")) == 0
    assert sum((entry.delta.shares for entry in history), Decimal("0")) == sum(
        (entry.delta.available_shares for entry in history), Decimal("0")
    )
    qualifier, proof = _install(monkeypatch, shares=True, history=history)

    result = _prepare(action)

    assert len(result.requests) == 6
    assert tuple(request.stage for request in result.requests) == (
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
    )
    assert all(
        request.entry_kind is CorporateActionEntryKind.REVERSAL for request in result.requests[:3]
    )
    assert all(
        request.entry_kind is CorporateActionEntryKind.SUCCESSOR for request in result.requests[3:]
    )
    successors = result.requests[3:]
    assert tuple(request.share_amount for request in successors) == (
        Decimal("20.000000"),
        Decimal("20.000000"),
        Decimal("20.000000"),
    )
    assert successors[1].stage_date == _DELIVERY
    assert successors[2].stage_date == date(2026, 11, 14)
    assert successors[2].sellable_date == _SELLABLE
    assert result.source_reference is successors[0]
    assert len(qualifier.requests) == 3
    assert (
        CorporateActionOwnershipProofVerifier(_OwnershipReader(proof)).verify_ownership(
            result.source_reference
        )
        is True
    )


def test_non_direct_public_source_successor_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    history = tuple(
        replace(
            entry,
            request=replace(
                entry.request,
                source_revision_id=f"sha256:{'f' * 64}",
                source_payload_sha256="f" * 64,
            ),
        )
        for entry in history
    )
    _install(monkeypatch, shares=False, history=history)

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_PREDECESSOR_INVALID"


def test_branched_public_source_lineage_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    prior, current = (item.event for item in _events(SecurityDisclosureEventType.CASH_DIVIDEND))
    branch = _event(
        event_type=SecurityDisclosureEventType.CASH_DIVIDEND,
        first_seen_at=_AS_OF - timedelta(days=3),
        prior=prior,
    )
    records = (
        PersistedSecurityDisclosureEvent(prior, _AS_OF - timedelta(days=19)),
        PersistedSecurityDisclosureEvent(current, _AS_OF - timedelta(days=4)),
        PersistedSecurityDisclosureEvent(branch, _AS_OF - timedelta(days=2)),
    )
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(
        monkeypatch,
        shares=False,
        history=history,
        event_records=records,
    )

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_SOURCE_LINEAGE_INVALID"


@pytest.mark.parametrize("action", ("tax_collect", "rights_not_exercised"))
def test_tax_and_rights_operations_are_outside_revision_service(
    monkeypatch: pytest.MonkeyPatch,
    action: OwnerCorporateActionOperation,
) -> None:
    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare(action)
    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_OPERATION_UNSUPPORTED"


def test_operation_must_name_an_active_stage_of_the_current_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(monkeypatch, shares=False, history=history)

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_payment")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_STAGE_SET_UNSUPPORTED"


def test_current_source_family_must_match_requested_revision_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(monkeypatch, shares=False, history=history)

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("share_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH"


def test_future_replacement_payment_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT),
        amount=Decimal("10.00"),
    )
    _install(
        monkeypatch,
        shares=False,
        history=history,
        payment_date=date(2026, 11, 20),
    )

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_payment")

    assert error.value.code == "CORPORATE_ACTION_OWNER_PAYMENT_DATE_NOT_REACHED"


@pytest.mark.parametrize(
    ("action", "delivery_date", "sellable_date", "expected_code"),
    (
        (
            "share_delivery",
            date(2026, 11, 20),
            date(2026, 11, 25),
            "CORPORATE_ACTION_OWNER_DELIVERY_DATE_NOT_REACHED",
        ),
        (
            "share_sellable_release",
            _DELIVERY,
            date(2026, 11, 20),
            "CORPORATE_ACTION_OWNER_SELLABLE_DATE_NOT_REACHED",
        ),
    ),
)
def test_future_share_stage_dates_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
    action: OwnerCorporateActionOperation,
    delivery_date: date,
    sellable_date: date,
    expected_code: str,
) -> None:
    prior = _events(SecurityDisclosureEventType.STOCK_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stages=(
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        ),
        amount=Decimal("10.000000"),
    )
    _install(
        monkeypatch,
        shares=True,
        history=history,
        delivery_date=delivery_date,
        sellable_date=sellable_date,
    )

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare(action)

    assert error.value.code == expected_code


def test_record_date_proof_must_match_the_locked_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(monkeypatch, shares=False, history=history, proof=_proof(account_id=_ACCOUNT + 1))

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID"


def test_mixed_history_scope_is_blocked_by_domain_head_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT),
        amount=Decimal("10.00"),
    )
    foreign_payment = replace(
        history[1].request,
        owner_user_id=_OWNER + 1,
    )
    history = (history[0], replace(history[1], request=foreign_payment))
    _install(monkeypatch, shares=False, history=history)

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_payment")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE"


def test_current_cash_tax_header_blocks_unmodeled_tax_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(monkeypatch, shares=False, history=history, tax_headers=(object(),))

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_TAX_REVISION_UNSUPPORTED"


def test_every_replacement_template_must_pass_current_source_qualification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT, CorporateActionStage.CASH_PAYMENT),
        amount=Decimal("10.00"),
    )
    qualifier, _ = _install(monkeypatch, shares=False, history=history)
    qualifier.accept = False

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_payment")

    assert error.value.code == "CORPORATE_ACTION_OWNER_SOURCE_QUALIFICATION_FAILED"
    assert len(qualifier.requests) == 1


def test_locked_readback_failure_is_not_treated_as_empty_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    history = _history(
        prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    _install(monkeypatch, shares=False, history=history)

    def fail_readback(**kwargs: object) -> tuple[OwnerCorporateActionRevisionEntry, ...]:
        del kwargs
        raise BusinessLogicError("synthetic full Audit readback unavailable")

    monkeypatch.setattr(
        composition, "read_locked_owner_corporate_action_revision_history", fail_readback
    )

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE"


def test_empty_readback_is_not_treated_as_a_new_initial_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, shares=False, history=())

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE"


def test_legacy_withholding_stage_is_rejected_without_refund_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _events(SecurityDisclosureEventType.CASH_DIVIDEND)[0].event
    entitlement = _old_request(
        event=prior,
        kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        amount=Decimal("10.00"),
    )
    withholding = replace(
        entitlement,
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=_PAYMENT,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        tax_rule_id="synthetic-legacy-rule",
        tax_rule_sha256="e" * 64,
        tax_basis_record_id="synthetic-legacy-basis",
        tax_basis_sha256="f" * 64,
    )
    history = (
        OwnerCorporateActionRevisionEntry(
            5011, 1, entitlement, calculate_corporate_action_delta(entitlement)
        ),
        OwnerCorporateActionRevisionEntry(
            5012, 2, withholding, calculate_corporate_action_delta(withholding)
        ),
    )
    _install(monkeypatch, shares=False, history=history)

    with pytest.raises(CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE"
