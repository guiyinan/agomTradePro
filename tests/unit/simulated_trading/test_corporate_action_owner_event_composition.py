"""Synthetic, read-only tests for the owner official-action preparation boundary."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
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
from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms
from apps.simulated_trading import corporate_action_owner_event_composition as composition
from apps.simulated_trading import corporate_action_owner_event_requests as event_requests
from apps.simulated_trading import corporate_action_owner_event_support as event_support
from apps.simulated_trading.application.corporate_action_owner_posting_read import (
    OwnerCorporateActionActivePostingHead,
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
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from tests.unit.simulated_trading.test_corporate_action_owner_revision_domain import (
    _entry as _revision_entry,
)
from tests.unit.simulated_trading.test_corporate_action_owner_revision_domain import (
    _request as _revision_request,
)

_ASSET = "000001.SZ"
_ACCOUNT = 4101
_OWNER = 8101
_EVENT_ID = "fca1e323-1c2e-44c8-8c5c-1b73c1699001"
_SOURCE_URL = (
    "https://disc.static.szse.cn/disc/disk03/finalpage/2026-10-15/"
    "fca1e323-1c2e-44c8-8c5c-1b73c1699001.PDF"
)
_AS_OF = datetime(2026, 11, 14, 3, 0, tzinfo=ZoneInfo("UTC"))
_RECORD = date(2026, 10, 30)
_EX = date(2026, 10, 31)


class _Reader:
    def __init__(self, rows: tuple[PersistedSecurityDisclosureEvent, ...]) -> None:
        self.rows = rows
        self.scopes: list[object] = []

    def execute(self, scope: object) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        self.scopes.append(scope)
        return self.rows


class _Ownership:
    def __init__(self, proof: RecordDateOwnershipProof) -> None:
        self.proof = proof
        self.requests: list[dict[str, object]] = []

    def read_verified_zero_origin_calendar(self, **kwargs: object) -> object:
        return SimpleNamespace(
            origin_on=date(2026, 1, 1),
            decision_on=date(2026, 11, 14),
            as_of=_AS_OF,
            timezone_policy=SimpleNamespace(
                exchange="SZSE",
                timezone_name="Asia/Shanghai",
                policy_id="synthetic-timezone-policy",
                policy_sha256="a" * 64,
            ),
        )

    def read_record_date_ownership_proof(self, **kwargs: object) -> RecordDateOwnershipProof:
        self.requests.append(dict(kwargs))
        return self.proof


class _ActionQualifier:
    def __init__(self, **kwargs: object) -> None:
        self.requests: list[object] = []
        self.tax_actions: list[object] = []
        self.result = True

    def verify_source(self, request: object) -> bool:
        self.requests.append(request)
        return self.result

    def verify_tax_action(self, action: object, *, as_of: datetime) -> bool:
        self.tax_actions.append((action, as_of))
        return self.result


class _RightsQualifier:
    def __init__(self, **kwargs: object) -> None:
        self.requests: list[object] = []

    def verify_source(self, request: object) -> bool:
        self.requests.append(request)
        return True


def _event(
    *,
    event_id: str = _EVENT_ID,
    event_type: SecurityDisclosureEventType = SecurityDisclosureEventType.CASH_DIVIDEND,
    effective_at: date = _EX,
    first_seen_at: datetime | None = None,
    prior: SecurityDisclosureEvent | None = None,
) -> SecurityDisclosureEvent:
    body = b"synthetic-only, never official acceptance:" + event_id.encode("ascii")
    return SecurityDisclosureEvent.from_source_document(
        source=SecurityDisclosureSource.SZSE_OFFICIAL,
        exchange=SecurityDisclosureExchange.SZSE,
        asset_code=_ASSET,
        source_security_code=_ASSET[:6],
        source_event_id=event_id,
        source_revision_id=f"sha256:{hashlib.sha256(body).hexdigest()}",
        raw_event_type=event_type.value,
        event_type=event_type,
        source_url=_SOURCE_URL,
        source_document_body=body,
        first_seen_at=first_seen_at or _AS_OF - timedelta(days=1),
        effective_at=effective_at,
        supersedes_source_event_id=prior.source_event_id if prior else None,
        supersedes_source_revision_id=prior.source_revision_id if prior else None,
    )


def _proof(quantity: Decimal = Decimal("100.000000")) -> RecordDateOwnershipProof:
    return RecordDateOwnershipProof(
        account_id=_ACCOUNT,
        owner_user_id=_OWNER,
        security_id=_ASSET,
        asset_code=_ASSET,
        record_date=_RECORD,
        ownership_snapshot_as_of_date=_RECORD,
        record_date_end_exclusive=datetime(2026, 10, 31, tzinfo=ZoneInfo("Asia/Shanghai")),
        exchange="SZSE",
        exchange_timezone_name="Asia/Shanghai",
        cutoff_policy_id="synthetic-timezone-policy",
        cutoff_policy_sha256="a" * 64,
        eligible_quantity=quantity,
        ownership_snapshot_id="synthetic-owner-proof",
        ownership_snapshot_sha256="b" * 64,
        ownership_snapshot_observed_at=_AS_OF,
    )


def _terms(cash_per_ten: Decimal = Decimal("1.00")) -> SzseDistributionTerms:
    return SzseDistributionTerms(
        record_date=_RECORD,
        ex_date=_EX,
        payment_date=date(2026, 11, 5),
        cash_per_ten=cash_per_ten,
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )


def _share_terms(shares_per_ten: Decimal = Decimal("1.00")) -> SzseDistributionTerms:
    """Return synthetic source-only share terms with distinct delivery and sellable dates."""

    return SzseDistributionTerms(
        record_date=_RECORD,
        ex_date=_EX,
        payment_date=None,
        cash_per_ten=None,
        shares_per_ten=shares_per_ten,
        tax_treatment="not_applicable",
        share_delivery_date=date(2026, 11, 10),
        share_sellable_date=date(2026, 11, 12),
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    event: SecurityDisclosureEvent | None = None,
    proof: RecordDateOwnershipProof | None = None,
    terms: SzseDistributionTerms | None = None,
    rights_terms: SzseRightsCompletionTerms | None = None,
    ledger_rows: tuple[object, ...] = (),
    tax_ids: tuple[object, ...] = (),
) -> tuple[_Reader, _Ownership, _ActionQualifier, _RightsQualifier]:
    selected = event or _event()
    persisted = PersistedSecurityDisclosureEvent(
        selected,
        recorded_at=_AS_OF - timedelta(hours=1),
    )
    reader = _Reader((persisted,))
    ownership = _Ownership(proof or _proof())
    action_qualifier = _ActionQualifier()
    rights_qualifier = _RightsQualifier()

    class _PolicyReader:
        def __init__(self, *, runtime_environment: str) -> None:
            assert runtime_environment == "synthetic-test"

        def read_policy(self, **kwargs: object) -> object:
            return SimpleNamespace(
                body_store_root=Path(__file__).resolve().parent / "synthetic-window-root",
                runtime_environment="synthetic-test",
                source_id="szse_official",
                start_on=date(2026, 1, 1),
                end_on=date(2026, 11, 14),
            )

    monkeypatch.setattr(
        composition, "make_security_disclosure_event_reader", lambda *, using: reader
    )
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
        event_support, "ConfiguredTransitionPlanDisclosureRuntimePolicyReader", _PolicyReader
    )
    monkeypatch.setattr(
        event_support,
        "resolve_asset_payload",
        lambda asset_code: {"code": asset_code, "name": "Synthetic test security"},
    )
    monkeypatch.setattr(
        composition,
        "read_verified_szse_distribution",
        lambda source_event, *, body_store_root: terms,
    )
    monkeypatch.setattr(
        event_requests,
        "read_verified_szse_rights_completion",
        lambda source_event, *, body_store_root: rights_terms,
    )
    monkeypatch.setattr(
        event_requests,
        "security_disclosure_window_pdf_store_root",
        lambda root: root,
    )
    monkeypatch.setattr(
        composition,
        "VerifiedSzseActionSourceQualifier",
        lambda **kwargs: action_qualifier,
    )
    monkeypatch.setattr(
        event_requests,
        "VerifiedSzseRightsSourceQualifier",
        lambda **kwargs: rights_qualifier,
    )
    monkeypatch.setattr(composition, "_read_event_postings", lambda **kwargs: ledger_rows)
    monkeypatch.setattr(event_requests, "_read_event_postings", lambda **kwargs: ledger_rows)
    monkeypatch.setattr(
        event_requests, "_read_existing_tax_action_identities", lambda **kwargs: tax_ids
    )
    return reader, ownership, action_qualifier, rights_qualifier


def _prepare(
    action: str,
    *,
    event_id: str = _EVENT_ID,
    settlement_date: date | None = None,
    canonical_account_id: str | None = None,
):
    return composition.prepare_owner_official_corporate_action(
        account_id=_ACCOUNT,
        owner_user_id=_OWNER,
        asset_code=_ASSET,
        event_id=event_id,
        action=cast(Any, action),
        settlement_date=settlement_date,
        as_of=_AS_OF,
        runtime_environment="synthetic-test",
        using="default",
        canonical_account_id=canonical_account_id,
    )


def _active_head(
    *,
    current_event: SecurityDisclosureEvent,
    logical_event_id: str,
    action_kind: CorporateActionKind,
    stages: tuple[CorporateActionStage, ...],
    amount: Decimal,
) -> OwnerCorporateActionActivePostingHead:
    """Build only the active current revision for a mocked fully verified reader."""

    entries: list[OwnerCorporateActionRevisionEntry] = []
    for index, stage in enumerate(stages):
        request = _revision_request(
            action_kind=action_kind,
            stage=stage,
            revision=current_event.source_revision_id,
            record_id=current_event.source_event_id,
            amount=amount,
            payment_date=date(2026, 11, 5) if stage is CorporateActionStage.CASH_PAYMENT else None,
            delivery_date=(
                date(2026, 11, 10) if stage is CorporateActionStage.SHARE_DELIVERY else None
            ),
            sellable_date=(
                date(2026, 11, 12)
                if stage
                in {
                    CorporateActionStage.SHARE_DELIVERY,
                    CorporateActionStage.SHARE_SELLABLE_RELEASE,
                }
                else None
            ),
            source_event=logical_event_id,
            account_id=_ACCOUNT,
            owner_user_id=_OWNER,
            asset_code=_ASSET,
            security_id=_ASSET,
        )
        entries.append(_revision_entry(701 + index, index + 1, request))
    return OwnerCorporateActionActivePostingHead(
        account_id=_ACCOUNT,
        owner_user_id=_OWNER,
        canonical_account_id="canonical-owner-account",
        source_namespace="exchange_official_disclosure",
        source_event_id=logical_event_id,
        source_record_id=current_event.source_event_id,
        source_revision_id=current_event.source_revision_id,
        security_id=_ASSET,
        asset_code=_ASSET,
        action_kind=action_kind,
        record_date=_RECORD,
        effective_date=_EX,
        active_entries=tuple(entries),
    )


def test_rule_market_proof_requires_actual_current_source_exchange_crosswalk(monkeypatch):
    from tests.unit.simulated_trading.test_published_price_initial_position_mark_reader import (
        _classification,
    )

    evidence = _classification(_AS_OF)
    item = replace(evidence.selector.items[0], security_id=_ASSET, asset_code=_ASSET)
    selector = replace(evidence.selector, items=(item,))
    identity = replace(
        evidence.identity_evidence,
        source_evidence=replace(
            evidence.identity_evidence.source_evidence,
            security_id=_ASSET,
            asset_code=_ASSET,
            source_exchange="SZSE",
            rule_market="SZ",
        ),
        selection=replace(
            evidence.identity_evidence.selection, selector_content_hash=selector.content_hash
        ),
    )
    evidence = replace(evidence, selector=selector, identity_evidence=identity)
    monkeypatch.setattr(
        event_support,
        "build_current_reference_classification_reader",
        lambda **kwargs: SimpleNamespace(
            resolve_simulated_instrument_classification=lambda **kwargs: evidence
        ),
    )
    ownership = _Ownership(replace(_proof(), exchange="SZ"))
    query = {
        "reader": ownership,
        "account_id": _ACCOUNT,
        "owner_user_id": _OWNER,
        "asset_code": _ASSET,
        "record_date": _RECORD,
        "as_of": _AS_OF,
        "runtime_environment": "synthetic-test",
    }
    assert event_support._read_record_date_proof(**query).exchange == "SZ"
    ownership.proof = replace(ownership.proof, exchange="UNMAPPED")
    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked):
        event_support._read_record_date_proof(**query)


def test_policy_earliest_date_uses_verified_nondefault_calendar_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source coverage follows the verified timezone rather than a Shanghai fallback."""
    as_of = datetime(2026, 11, 14, 20, 0, tzinfo=ZoneInfo("UTC"))
    policy_calls: list[dict[str, object]] = []

    class _PolicyReader:
        def __init__(self, *, runtime_environment: str) -> None:
            assert runtime_environment == "synthetic-test"

        def read_policy(self, **kwargs: object) -> object:
            policy_calls.append(dict(kwargs))
            return SimpleNamespace(
                body_store_root=Path(__file__).resolve().parent / "synthetic-window-root",
                runtime_environment="synthetic-test",
                source_id="szse_official",
                start_on=date(2026, 1, 1),
                end_on=kwargs["decision_on"],
            )

    monkeypatch.setattr(
        event_support, "ConfiguredTransitionPlanDisclosureRuntimePolicyReader", _PolicyReader
    )
    calendar = SimpleNamespace(
        origin_on=date(2026, 1, 1),
        decision_on=date(2026, 11, 14),
        as_of=as_of,
        timezone_policy=SimpleNamespace(
            exchange="SZSE",
            timezone_name="UTC",
            policy_id="synthetic-utc-policy",
            policy_sha256="c" * 64,
        ),
    )
    decision_on, exchange_timezone = event_support._validate_calendar(calendar, as_of=as_of)
    event = _event(first_seen_at=datetime(2026, 11, 14, 19, 0, tzinfo=ZoneInfo("UTC")))

    event_support._read_policy(
        runtime_environment="synthetic-test",
        decision_on=decision_on,
        exchange_timezone=exchange_timezone,
        event=event,
        as_of=as_of,
    )

    assert policy_calls[0]["decision_on"] == date(2026, 11, 14)
    assert policy_calls[0]["earliest_required_on"] == date(2026, 11, 14)


def test_invalid_verified_calendar_timezone_blocks_without_fallback() -> None:
    """An unknown configured zone cannot silently fall back to Shanghai."""
    calendar = SimpleNamespace(
        origin_on=date(2026, 1, 1),
        decision_on=date(2026, 11, 14),
        as_of=_AS_OF,
        timezone_policy=SimpleNamespace(
            exchange="SZSE",
            timezone_name="Not/A-Configured-Timezone",
            policy_id="synthetic-invalid-policy",
            policy_sha256="d" * 64,
        ),
    )

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        event_support._validate_calendar(calendar, as_of=_AS_OF)

    assert error.value.code == "CORPORATE_ACTION_OWNER_CALENDAR_UNAVAILABLE"


def test_synthetic_cash_entitlement_uses_record_date_proof_and_exact_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request derives gross cash solely from source terms and the full historical proof."""
    reader, ownership, qualifier, _ = _install(monkeypatch, terms=_terms())

    result = _prepare("cash_entitlement")

    assert result.source_reference.cash_amount == Decimal("10.00")
    assert result.source_reference.eligible_quantity == Decimal("100.000000")
    assert result.source_reference.ownership_snapshot_observed_at == _AS_OF
    assert result.source_reference.source_observed_at == result.event.first_seen_at
    assert result.requests == (result.source_reference,)
    assert result.tax_action is None
    assert reader.scopes
    assert ownership.requests[0]["record_date"] == _RECORD
    assert qualifier.requests == [result.source_reference]


def test_unrepresentable_fractional_cent_cash_blocks_without_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source gross not exact to cents never reaches a ledger request."""
    _install(
        monkeypatch,
        proof=_proof(Decimal("1.000000")),
        terms=_terms(Decimal("0.03")),
    )

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED"


def test_cash_payment_uses_full_outstanding_receivable_after_source_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payment amount comes from the actual immutable receivable ledger rows."""
    _, _, qualifier, _ = _install(
        monkeypatch,
        terms=_terms(),
        ledger_rows=(
            _posting_row(stage="cash_entitlement", revision=1, receivable=Decimal("10.00")),
        ),
    )

    result = _prepare("cash_payment")

    assert result.source_reference.stage is CorporateActionStage.CASH_PAYMENT
    assert result.source_reference.cash_amount == Decimal("10.00")
    assert result.source_reference.payment_date == date(2026, 11, 5)
    assert qualifier.requests == [result.source_reference]


def test_cash_payment_before_source_payment_date_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Future payment dates remain a block even with a genuine entitlement row."""
    future_terms = SzseDistributionTerms(
        record_date=_RECORD,
        ex_date=_EX,
        payment_date=date(2026, 11, 30),
        cash_per_ten=Decimal("1.00"),
        shares_per_ten=None,
        tax_treatment="deferred_withholding",
    )
    _, _, qualifier, _ = _install(
        monkeypatch,
        terms=future_terms,
        ledger_rows=(
            _posting_row(stage="cash_entitlement", revision=1, receivable=Decimal("10.00")),
        ),
    )

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("cash_payment")

    assert error.value.code == "CORPORATE_ACTION_OWNER_PAYMENT_DATE_NOT_REACHED"
    assert qualifier.requests == []


def test_share_entitlement_uses_only_exact_whole_share_arithmetic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source-proven integral allotment is never rounded from the owner position."""
    event = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    _, ownership, qualifier, _ = _install(
        monkeypatch,
        event=event,
        terms=_share_terms(Decimal("1.00")),
    )

    result = _prepare("share_entitlement")

    assert result.source_reference.share_amount == Decimal("10.000000")
    assert result.source_reference.eligible_quantity == Decimal("100.000000")
    assert ownership.requests[0]["record_date"] == _RECORD
    assert qualifier.requests == [result.source_reference]


def test_fractional_share_entitlement_blocks_without_flooring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unregistered fractional entitlements never become a guessed integer delivery."""
    event = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    _install(
        monkeypatch,
        event=event,
        proof=_proof(Decimal("1.000000")),
        terms=_share_terms(Decimal("3.00")),
    )

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("share_entitlement")

    assert error.value.code == "CORPORATE_ACTION_OWNER_ODD_LOT_UNSUPPORTED"


@pytest.mark.parametrize(
    ("action", "stage", "share_receivable", "share"),
    (
        ("share_delivery", "share_entitlement", Decimal("10.000000"), Decimal("0")),
        ("share_sellable_release", "share_delivery", Decimal("0"), Decimal("10.000000")),
    ),
)
def test_share_source_proposal_remains_separate_from_holder_model_and_financial_authority(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    stage: str,
    share_receivable: Decimal,
    share: Decimal,
) -> None:
    """A source-only proposal supplies no independent model or financial authority."""
    event = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    _, _, qualifier, _ = _install(
        monkeypatch,
        event=event,
        terms=_share_terms(),
        ledger_rows=(
            _share_posting_row(
                stage=stage,
                revision=1,
                share_receivable=share_receivable,
                share=share,
            ),
        ),
    )

    prepared = _prepare(action)
    assert len(prepared.requests) == 1
    assert prepared.requests[0].stage.value == action
    assert prepared.requests[0].tax_rule_id is None
    assert prepared.requests[0].tax_rule_sha256 is None
    assert len(qualifier.requests) == 1


@pytest.mark.parametrize(
    ("event_type", "action", "terms"),
    (
        (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            "cash_entitlement",
            SzseDistributionTerms(
                record_date=date(2026, 11, 1),
                ex_date=_EX,
                payment_date=date(2026, 11, 5),
                cash_per_ten=Decimal("1.00"),
                shares_per_ten=None,
                tax_treatment="deferred_withholding",
            ),
        ),
        (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            "cash_entitlement",
            SzseDistributionTerms(
                record_date=_RECORD,
                ex_date=_EX,
                payment_date=_RECORD,
                cash_per_ten=Decimal("1.00"),
                shares_per_ten=None,
                tax_treatment="deferred_withholding",
            ),
        ),
        (
            SecurityDisclosureEventType.CASH_DIVIDEND,
            "cash_entitlement",
            SzseDistributionTerms(
                record_date=_RECORD,
                ex_date=_EX,
                payment_date=datetime(2026, 11, 5),
                cash_per_ten=Decimal("1.00"),
                shares_per_ten=None,
                tax_treatment="deferred_withholding",
            ),
        ),
        (
            SecurityDisclosureEventType.STOCK_DIVIDEND,
            "share_entitlement",
            SzseDistributionTerms(
                record_date=_RECORD,
                ex_date=_EX,
                payment_date=None,
                cash_per_ten=None,
                shares_per_ten=Decimal("1.00"),
                tax_treatment="not_applicable",
                share_delivery_date=_RECORD,
                share_sellable_date=date(2026, 11, 12),
            ),
        ),
        (
            SecurityDisclosureEventType.STOCK_DIVIDEND,
            "share_entitlement",
            SzseDistributionTerms(
                record_date=_RECORD,
                ex_date=_EX,
                payment_date=None,
                cash_per_ten=None,
                shares_per_ten=Decimal("1.00"),
                tax_treatment="not_applicable",
                share_delivery_date=date(2026, 11, 10),
                share_sellable_date=_EX,
            ),
        ),
        (
            SecurityDisclosureEventType.STOCK_DIVIDEND,
            "share_entitlement",
            SzseDistributionTerms(
                record_date=_RECORD,
                ex_date=_EX,
                payment_date=None,
                cash_per_ten=None,
                shares_per_ten=Decimal("1.00"),
                tax_treatment="not_applicable",
                share_delivery_date=datetime(2026, 11, 10),
                share_sellable_date=date(2026, 11, 12),
            ),
        ),
    ),
)
def test_distribution_event_rejects_impossible_source_date_order(
    monkeypatch: pytest.MonkeyPatch,
    event_type: SecurityDisclosureEventType,
    action: str,
    terms: SzseDistributionTerms,
) -> None:
    """Record, effective, payment and share dates must retain source chronology."""
    event = _event(event_type=event_type)
    _install(monkeypatch, event=event, terms=terms)

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare(action)

    assert error.value.code == "CORPORATE_ACTION_OWNER_SOURCE_TERMS_INVALID"


def test_synthetic_tax_actions_preserve_event_hash_and_existing_logical_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assessment, recognition and collection receive one native fact identity."""
    existing_id = "existing-logical-action-id"
    tax_identity = SimpleNamespace(
        corporate_action_id=existing_id,
        asset_code=_ASSET,
        security_id=_ASSET,
        source_namespace="exchange_official_disclosure",
        source_event_id=_EVENT_ID,
    )
    paid_rows = (
        _posting_row(stage="cash_entitlement", revision=1, receivable=Decimal("10.00")),
        _posting_row(
            stage="cash_payment",
            revision=2,
            cash=Decimal("10.00"),
            receivable=Decimal("-10.00"),
        ),
    )
    _, _, qualifier, _ = _install(
        monkeypatch,
        terms=_terms(),
        ledger_rows=paid_rows,
        tax_ids=(tax_identity,),
    )

    for action in ("tax_assess", "tax_recognize", "tax_collect"):
        result = _prepare(action, settlement_date=date(2026, 11, 5))
        assert result.requests == ()
        assert isinstance(result.tax_action, QualifiedCorporateActionTaxFacts)
        assert result.tax_action.corporate_action_id == existing_id
        assert result.tax_action.source_revision_sha256 == result.event.content_hash
        assert result.tax_action.source_payload_sha256 == result.event.source_body_sha256
    assert len(qualifier.tax_actions) == 3


def test_each_tax_operation_requires_an_explicit_disposition_settlement_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The builder never chooses a latest sale date for the caller."""
    _install(monkeypatch, terms=_terms())

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("tax_assess")

    assert error.value.code == "CORPORATE_ACTION_OWNER_INPUT_INVALID"


def test_conflicting_tax_action_ids_block_instead_of_forking_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two retained IDs for one owner/event cannot create a third tax chain."""
    ids = tuple(
        SimpleNamespace(
            corporate_action_id=value,
            asset_code=_ASSET,
            security_id=_ASSET,
            source_namespace="exchange_official_disclosure",
            source_event_id=_EVENT_ID,
        )
        for value in ("logical-a", "logical-b")
    )
    _install(monkeypatch, terms=_terms(), tax_ids=ids)

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        _prepare("tax_assess", settlement_date=date(2026, 11, 5))

    assert error.value.code == "CORPORATE_ACTION_OWNER_TAX_IDENTITY_CONFLICT"


def _posting_row(
    *,
    stage: str,
    revision: int,
    cash: Decimal = Decimal("0.00"),
    receivable: Decimal = Decimal("0.00"),
) -> SimpleNamespace:
    """Build synthetic immutable row-shape input for read-only ledger derivation tests."""

    event = _event()
    return SimpleNamespace(
        pk=revision,
        account_id=_ACCOUNT,
        account_revision=revision,
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=_EVENT_ID,
        source_revision_id=event.source_revision_id,
        asset_code=_ASSET,
        security_id=_ASSET,
        action_kind="cash_dividend",
        stage=stage,
        entry_kind="posting",
        record_date=_RECORD,
        effective_date=_EX,
        created_at=_AS_OF - timedelta(minutes=10),
        posted_at=_AS_OF - timedelta(minutes=10),
        cash_delta=cash,
        cash_receivable_delta=receivable,
        share_delta=Decimal("0.000000"),
        share_receivable_delta=Decimal("0.000000"),
        available_share_delta=Decimal("0.000000"),
    )


def _share_posting_row(
    *,
    stage: str,
    revision: int,
    share: Decimal = Decimal("0.000000"),
    share_receivable: Decimal = Decimal("0.000000"),
    available: Decimal = Decimal("0.000000"),
) -> SimpleNamespace:
    """Build synthetic immutable row-shape input for share settlement tests."""

    event = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    return SimpleNamespace(
        pk=revision,
        account_id=_ACCOUNT,
        account_revision=revision,
        source_namespace="exchange_official_disclosure",
        source_record_id=event.source_event_id,
        source_event_id=_EVENT_ID,
        source_revision_id=event.source_revision_id,
        asset_code=_ASSET,
        security_id=_ASSET,
        action_kind="share_distribution",
        stage=stage,
        entry_kind="posting",
        record_date=_RECORD,
        effective_date=_EX,
        created_at=_AS_OF - timedelta(minutes=10),
        posted_at=_AS_OF - timedelta(minutes=10),
        cash_delta=Decimal("0.00"),
        cash_receivable_delta=Decimal("0.00"),
        share_delta=share,
        share_receivable_delta=share_receivable,
        available_share_delta=available,
    )


def test_rights_no_effect_requires_confirmed_result_and_emits_no_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The only rights operation is zero-effect after the source ex-rights date."""
    event = _event(
        event_type=SecurityDisclosureEventType.RIGHTS_ISSUE,
        effective_at=date(2026, 11, 12),
    )
    terms = SzseRightsCompletionTerms(
        source_security_code=_ASSET[:6],
        record_date=_RECORD,
        subscription_end_date=date(2026, 11, 10),
        offered_rights_per_ten=Decimal("3.00"),
        subscription_price_cny_per_share=Decimal("2.00"),
        actual_aggregate_rights_per_ten=Decimal("2.50"),
        actual_ex_rights_date=date(2026, 11, 12),
    )
    _, _, _, qualifier = _install(monkeypatch, event=event, rights_terms=terms)

    result = _prepare("rights_not_exercised")

    request = result.requests[0]
    assert request.entry_kind is CorporateActionEntryKind.NO_EFFECT
    assert request.stage is CorporateActionStage.RIGHTS_NOT_EXERCISED
    assert request.rights_election == "not_exercised"
    assert request.cash_amount is None
    assert request.share_amount is None
    assert qualifier.requests == [request]


def test_existing_old_revision_ledger_rows_block_partial_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source correction is blocked until a complete reversal/successor batch is available."""
    previous = _event()
    new_id = "fca1e323-1c2e-44c8-8c5c-1b73c1699002"
    corrected = _event(event_id=new_id, prior=previous)
    reader = _Reader(
        (
            PersistedSecurityDisclosureEvent(previous, _AS_OF - timedelta(hours=23)),
            PersistedSecurityDisclosureEvent(corrected, _AS_OF - timedelta(hours=1)),
        )
    )
    old_row = SimpleNamespace(
        account_id=_ACCOUNT,
        account_revision=1,
        asset_code=_ASSET,
        security_id=_ASSET,
        source_event_id=previous.source_event_id,
        source_revision_id=previous.source_revision_id,
        action_kind="cash_dividend",
        stage="cash_entitlement",
        entry_kind="posting",
        created_at=_AS_OF - timedelta(hours=2),
        posted_at=_AS_OF - timedelta(hours=2),
    )
    _install(monkeypatch, terms=_terms())
    monkeypatch.setattr(
        composition, "make_security_disclosure_event_reader", lambda *, using: reader
    )
    monkeypatch.setattr(composition, "_read_event_postings", lambda **kwargs: (old_row,))

    with pytest.raises(composition.CorporateActionOwnerEventPreparationBlocked) as error:
        composition.prepare_owner_official_corporate_action(
            account_id=_ACCOUNT,
            owner_user_id=_OWNER,
            asset_code=_ASSET,
            event_id=new_id,
            action="cash_payment",
            as_of=_AS_OF,
            runtime_environment="synthetic-test",
            using="default",
        )

    assert error.value.code == "CORPORATE_ACTION_OWNER_CORRECTION_REQUIRED", repr(
        error.value.__cause__
    )


def test_cash_payment_continues_from_a_verified_corrected_entitlement_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _event()
    current = _event(
        event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699002",
        prior=previous,
    )
    reader = _Reader(
        (
            PersistedSecurityDisclosureEvent(previous, _AS_OF - timedelta(hours=23)),
            PersistedSecurityDisclosureEvent(current, _AS_OF - timedelta(hours=1)),
        )
    )
    head = _active_head(
        current_event=current,
        logical_event_id=previous.source_event_id,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stages=(CorporateActionStage.CASH_ENTITLEMENT,),
        amount=Decimal("10.00"),
    )
    calls: list[dict[str, object]] = []
    old_row = _posting_row(
        stage="cash_entitlement",
        revision=1,
        receivable=Decimal("10.00"),
    )
    _, _, qualifier, _ = _install(
        monkeypatch,
        event=previous,
        terms=_terms(),
        ledger_rows=(old_row,),
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_reader",
        lambda *, using: reader,
    )
    monkeypatch.setattr(
        composition,
        "read_current_owner_corporate_action_active_postings",
        lambda **kwargs: (calls.append(dict(kwargs)) or head),
    )
    monkeypatch.setattr(
        composition,
        "_validate_ledger_rows",
        lambda **kwargs: pytest.fail("corrected history must use the complete readback path"),
    )

    result = _prepare(
        "cash_payment",
        event_id=current.source_event_id,
        canonical_account_id="canonical-owner-account",
    )

    assert result.source_reference.stage is CorporateActionStage.CASH_PAYMENT
    assert result.source_reference.cash_amount == Decimal("10.00")
    assert calls[0]["source_revision_id"] == current.source_revision_id
    assert calls[0]["canonical_account_id"] == "canonical-owner-account"
    assert qualifier.requests == [result.source_reference]


def test_share_delivery_continues_from_a_verified_corrected_entitlement_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    current = _event(
        event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699003",
        event_type=SecurityDisclosureEventType.STOCK_DIVIDEND,
        prior=previous,
    )
    reader = _Reader(
        (
            PersistedSecurityDisclosureEvent(previous, _AS_OF - timedelta(hours=23)),
            PersistedSecurityDisclosureEvent(current, _AS_OF - timedelta(hours=1)),
        )
    )
    head = _active_head(
        current_event=current,
        logical_event_id=previous.source_event_id,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stages=(CorporateActionStage.SHARE_ENTITLEMENT,),
        amount=Decimal("10.000000"),
    )
    _, _, qualifier, _ = _install(
        monkeypatch,
        event=previous,
        terms=_share_terms(),
        ledger_rows=(
            _share_posting_row(
                stage="share_entitlement",
                revision=1,
                share_receivable=Decimal("10.000000"),
            ),
        ),
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_reader",
        lambda *, using: reader,
    )
    monkeypatch.setattr(
        composition,
        "read_current_owner_corporate_action_active_postings",
        lambda **kwargs: head,
    )
    monkeypatch.setattr(
        composition,
        "_validate_ledger_rows",
        lambda **kwargs: pytest.fail("corrected history must use the complete readback path"),
    )

    result = _prepare(
        "share_delivery",
        event_id=current.source_event_id,
        canonical_account_id="canonical-owner-account",
    )

    assert result.source_reference.stage is CorporateActionStage.SHARE_DELIVERY
    assert result.source_reference.share_amount == Decimal("10.000000")
    assert qualifier.requests == [result.source_reference]


def test_share_release_continues_from_corrected_entitlement_and_delivery_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _event(event_type=SecurityDisclosureEventType.STOCK_DIVIDEND)
    current = _event(
        event_id="fca1e323-1c2e-44c8-8c5c-1b73c1699004",
        event_type=SecurityDisclosureEventType.STOCK_DIVIDEND,
        prior=previous,
    )
    reader = _Reader(
        (
            PersistedSecurityDisclosureEvent(previous, _AS_OF - timedelta(hours=23)),
            PersistedSecurityDisclosureEvent(current, _AS_OF - timedelta(hours=1)),
        )
    )
    head = _active_head(
        current_event=current,
        logical_event_id=previous.source_event_id,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stages=(
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
        ),
        amount=Decimal("10.000000"),
    )
    _, _, qualifier, _ = _install(
        monkeypatch,
        event=previous,
        terms=_share_terms(),
        ledger_rows=(
            _share_posting_row(
                stage="share_entitlement",
                revision=1,
                share_receivable=Decimal("10.000000"),
            ),
            _share_posting_row(
                stage="share_delivery",
                revision=2,
                share=Decimal("10.000000"),
            ),
        ),
    )
    monkeypatch.setattr(
        composition,
        "make_security_disclosure_event_reader",
        lambda *, using: reader,
    )
    monkeypatch.setattr(
        composition,
        "read_current_owner_corporate_action_active_postings",
        lambda **kwargs: head,
    )
    monkeypatch.setattr(
        composition,
        "_validate_ledger_rows",
        lambda **kwargs: pytest.fail("corrected history must use the complete readback path"),
    )

    result = _prepare(
        "share_sellable_release",
        event_id=current.source_event_id,
        canonical_account_id="canonical-owner-account",
    )

    assert result.source_reference.stage is CorporateActionStage.SHARE_SELLABLE_RELEASE
    assert result.source_reference.share_amount == Decimal("10.000000")
    assert qualifier.requests == [result.source_reference]
