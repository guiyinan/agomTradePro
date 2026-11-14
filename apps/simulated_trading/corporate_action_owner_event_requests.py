"""Build exact corporate-action posting requests from retained source facts."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from zoneinfo import ZoneInfo

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SzseDistributionTerms,
)
from apps.data_center.domain.szse_rights_terms import SzseRightsCompletionTerms
from apps.data_center.security_disclosure_body_composition import (
    read_verified_szse_rights_completion,
    security_disclosure_window_pdf_store_root,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionOperation,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    _OFFICIAL_NAMESPACE,
    PreparedOwnerOfficialAction,
    _asset_name,
    _blocked,
    _CurrentEventChain,
    _OwnerHistoryReader,
    _read_event_postings,
    _read_existing_tax_action_identities,
    _read_policy,
    _read_record_date_proof,
    _source_values,
    _supported_share_quantity,
    _validate_ledger_rows,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    QualifiedCorporateActionTaxFacts,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    szse_action_qualification_sha256,
)
from apps.simulated_trading.official_rights_action_composition import (
    SZSE_RIGHTS_QUALIFIER_ID,
    VerifiedSzseRightsSourceQualifier,
    szse_rights_qualification_sha256,
    szse_rights_terms_sha256,
)


def _make_cash_entitlement_request(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    as_of: datetime,
    stage_date: date,
) -> CorporateActionStageRequest:
    """Calculate exact cash entitlement from source ratio and historical ownership."""

    if terms.cash_per_ten is None:
        _blocked(
            "cash amount per ten shares is unavailable",
            "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
        )
    if stage_date < terms.record_date:
        _blocked(
            "cash entitlement record date has not been reached",
            "CORPORATE_ACTION_OWNER_RECORD_DATE_NOT_REACHED",
        )
    gross = _cash_gross(proof.eligible_quantity, terms.cash_per_ten)
    source = _source_values(
        event=event,
        chain=chain,
        as_of=as_of,
        qualified_at=proof.ownership_snapshot_observed_at,
    )
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        asset_name=_asset_name(asset_code),
        **source,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=stage_date,
        cash_amount=gross,
        tax_treatment=terms.tax_treatment,
        ownership_snapshot_id=proof.ownership_snapshot_id,
        ownership_snapshot_sha256=proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=proof.ownership_snapshot_observed_at,
        eligible_quantity=proof.eligible_quantity,
        entitlement_calculation_sha256=_entitlement_sha256(
            event=event,
            terms_sha256=szse_action_qualification_sha256(event, terms),
            proof=proof,
            gross=gross,
        ),
    )


def _make_cash_payment_request(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    amount: Decimal,
    as_of: datetime,
    stage_date: date,
) -> CorporateActionStageRequest:
    """Prepare full payment of the verified unpaid event receivable."""

    if terms.payment_date is None or terms.cash_per_ten is None:
        _blocked(
            "cash payment date or source economics are unavailable",
            "CORPORATE_ACTION_OWNER_PAYMENT_TERMS_UNSUPPORTED",
        )
    source = _source_values(event=event, chain=chain, as_of=as_of)
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        asset_name=_asset_name(asset_code),
        **source,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_PAYMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=stage_date,
        cash_amount=amount,
        payment_date=terms.payment_date,
        tax_treatment=terms.tax_treatment,
    )


def _make_share_entitlement_request(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    as_of: datetime,
    stage_date: date,
) -> CorporateActionStageRequest:
    """Calculate a whole-share entitlement without registry rounding or tax inference."""

    if (
        terms.shares_per_ten is None
        or terms.tax_treatment != "not_applicable"
        or terms.share_delivery_date is None
        or terms.share_sellable_date is None
    ):
        _blocked(
            "share ratio, tax treatment, delivery date, or sellable date is unsupported",
            "CORPORATE_ACTION_OWNER_SHARE_TERMS_UNSUPPORTED",
        )
    if stage_date < terms.record_date:
        _blocked(
            "share entitlement record date has not been reached",
            "CORPORATE_ACTION_OWNER_RECORD_DATE_NOT_REACHED",
        )
    amount = _whole_share_gross(proof.eligible_quantity, terms.shares_per_ten)
    source = _source_values(
        event=event,
        chain=chain,
        as_of=as_of,
        qualified_at=proof.ownership_snapshot_observed_at,
    )
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        asset_name=_asset_name(asset_code),
        **source,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=stage_date,
        share_amount=amount,
        sellable_date=None,
        tax_treatment=terms.tax_treatment,
        ownership_snapshot_id=proof.ownership_snapshot_id,
        ownership_snapshot_sha256=proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=proof.ownership_snapshot_observed_at,
        eligible_quantity=proof.eligible_quantity,
        entitlement_calculation_sha256=_entitlement_sha256(
            event=event,
            terms_sha256=szse_action_qualification_sha256(event, terms),
            proof=proof,
            gross=amount,
        ),
        odd_lot_policy="whole_shares",
    )


def _make_share_settlement_request(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    amount: Decimal,
    stage: CorporateActionStage,
    stage_date: date,
    as_of: datetime,
) -> CorporateActionStageRequest:
    """Prepare complete delivery or sellable release from retained account receipts."""

    if (
        terms.tax_treatment != "not_applicable"
        or terms.share_delivery_date is None
        or terms.share_sellable_date is None
    ):
        _blocked(
            "share distribution is not fully source-qualified",
            "CORPORATE_ACTION_OWNER_SHARE_TERMS_UNSUPPORTED",
        )
    source = _source_values(event=event, chain=chain, as_of=as_of)
    return CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        asset_name=_asset_name(asset_code),
        **source,
        qualification_sha256=szse_action_qualification_sha256(event, terms),
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=stage,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=terms.record_date,
        effective_date=terms.ex_date,
        stage_date=stage_date,
        share_amount=amount,
        sellable_date=terms.share_sellable_date,
        tax_treatment=terms.tax_treatment,
        odd_lot_policy="whole_shares",
    )


def _prepare_rights_no_effect(
    *,
    action: OwnerCorporateActionOperation,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    as_of: datetime,
    decision_on: date,
    exchange_timezone: ZoneInfo,
    runtime_environment: str,
    using: str,
    ownership_reader: _OwnerHistoryReader,
) -> PreparedOwnerOfficialAction:
    """Build only a confirmed, reached, no-exercise rights entry."""

    if action != "rights_not_exercised":
        _blocked(
            "rights exercise and financial actions are outside this workflow",
            "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
        )
    policy = _read_policy(
        runtime_environment=runtime_environment,
        decision_on=decision_on,
        exchange_timezone=exchange_timezone,
        event=event,
        as_of=as_of,
    )
    terms = read_verified_szse_rights_completion(
        event,
        body_store_root=security_disclosure_window_pdf_store_root(policy.body_store_root),
    )
    if type(terms) is not SzseRightsCompletionTerms:
        _blocked(
            "a confirmed successful rights result is unavailable",
            "CORPORATE_ACTION_OWNER_RIGHTS_RESULT_UNAVAILABLE",
        )
    if (
        terms.source_security_code != event.source_security_code
        or type(event.effective_at) is not date
        or event.effective_at != terms.actual_ex_rights_date
        or terms.subscription_end_date >= terms.actual_ex_rights_date
        or decision_on < terms.actual_ex_rights_date
    ):
        _blocked(
            "rights subscription close or actual ex-rights date is not reached and confirmed",
            "CORPORATE_ACTION_OWNER_RIGHTS_DATE_NOT_REACHED",
        )
    proof = _read_record_date_proof(
        reader=ownership_reader,
        account_id=account_id,
        owner_user_id=owner_user_id,
        asset_code=asset_code,
        record_date=terms.record_date,
        as_of=as_of,
        runtime_environment=runtime_environment,
    )
    ledger_rows = _read_event_postings(
        account_id=account_id,
        source_event_id=chain.root.event.source_event_id,
        using=using,
    )
    _validate_ledger_rows(
        rows=ledger_rows,
        chain=chain,
        account_id=account_id,
        asset_code=asset_code,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        record_date=terms.record_date,
        effective_date=terms.actual_ex_rights_date,
        as_of=as_of,
    )
    if ledger_rows:
        _blocked(
            "the rights no-effect stage is already retained for this disclosure",
            "CORPORATE_ACTION_OWNER_STAGE_ALREADY_RECORDED",
        )
    source = _source_values(
        event=event,
        chain=chain,
        as_of=as_of,
        qualified_at=proof.ownership_snapshot_observed_at,
    )
    source["qualifier_identity"] = SZSE_RIGHTS_QUALIFIER_ID
    request = CorporateActionStageRequest(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=asset_code,
        asset_code=asset_code,
        asset_name=_asset_name(asset_code),
        **source,
        qualification_sha256=szse_rights_qualification_sha256(event, terms),
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        record_date=terms.record_date,
        effective_date=terms.actual_ex_rights_date,
        stage_date=decision_on,
        ownership_snapshot_id=proof.ownership_snapshot_id,
        ownership_snapshot_sha256=proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=proof.ownership_snapshot_observed_at,
        eligible_quantity=proof.eligible_quantity,
        entitlement_calculation_sha256=_entitlement_sha256(
            event=event,
            terms_sha256=szse_rights_terms_sha256(terms),
            proof=proof,
            gross=proof.eligible_quantity,
        ),
        rights_terms_sha256=szse_rights_terms_sha256(terms),
        rights_election="not_exercised",
    )
    qualifier = VerifiedSzseRightsSourceQualifier(
        body_store_root=security_disclosure_window_pdf_store_root(policy.body_store_root),
        runtime_environment=runtime_environment,
        using=using,
    )
    if qualifier.verify_source(request) is not True:
        _blocked(
            "the rights no-effect request does not match the retained confirmed source",
            "CORPORATE_ACTION_OWNER_SOURCE_QUALIFICATION_FAILED",
        )
    return PreparedOwnerOfficialAction(
        action=action,
        event=event,
        source_reference=request,
        requests=(request,),
        tax_action=None,
    )


def _cash_gross(quantity: Decimal, cash_per_ten: Decimal) -> Decimal:
    """Compute cents exactly and reject fractional-cash results rather than rounding."""

    if not _supported_share_quantity(quantity) or not _bounded_positive_decimal(cash_per_ten):
        _blocked(
            "cash entitlement inputs exceed supported exact precision",
            "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
        )
    with localcontext() as context:
        context.prec = 80
        gross = quantity * cash_per_ten / Decimal("10")
        try:
            exact_cents = gross.quantize(Decimal("0.01"))
        except InvalidOperation:
            _blocked(
                "cash entitlement exceeds the exact ledger range",
                "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
            )
        if gross != exact_cents or exact_cents <= 0 or exact_cents.adjusted() >= 13:
            _blocked(
                "cash entitlement is not an exact supported cent amount",
                "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
            )
        return exact_cents


def _whole_share_gross(quantity: Decimal, shares_per_ten: Decimal) -> Decimal:
    """Calculate an exact integral allotment without a guessed registry rounding rule."""

    if not _supported_share_quantity(quantity) or not _bounded_positive_decimal(shares_per_ten):
        _blocked(
            "share entitlement inputs exceed supported exact precision",
            "CORPORATE_ACTION_OWNER_SHARE_TERMS_UNSUPPORTED",
        )
    exact = Fraction(quantity) * Fraction(shares_per_ten) / 10
    if exact.denominator != 1 or exact.numerator <= 0 or exact.numerator >= 10**14:
        _blocked(
            "fractional or oversized share allocation requires final registry facts",
            "CORPORATE_ACTION_OWNER_ODD_LOT_UNSUPPORTED",
        )
    return Decimal(exact.numerator).quantize(Decimal("0.000001"))


def _bounded_positive_decimal(value: object) -> bool:
    """Reject nonpositive, extreme, or overlong source ratios before exact arithmetic."""

    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        return False
    parts = value.as_tuple()
    exponent = parts.exponent
    return (
        type(exponent) is int
        and len(parts.digits) <= 24
        and abs(exponent) <= 18
        and -18 <= value.adjusted() <= 18
    )


def _entitlement_sha256(
    *,
    event: SecurityDisclosureEvent,
    terms_sha256: str,
    proof: RecordDateOwnershipProof,
    gross: Decimal,
) -> str:
    """Hash the exact event, qualification, owner snapshot, and unrounded result."""

    payload = (
        f"{event.content_hash}|{terms_sha256}|{proof.account_id}|{proof.owner_user_id}|"
        f"{proof.security_id}|{proof.asset_code}|{proof.record_date.isoformat()}|"
        f"{proof.ownership_snapshot_id}|{proof.ownership_snapshot_sha256}|"
        f"{proof.ownership_snapshot_observed_at.isoformat()}|{proof.eligible_quantity}|{gross}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_tax_action(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    using: str,
) -> QualifiedCorporateActionTaxFacts:
    """Build source facts while preserving an existing logical tax action identity."""

    identities = _read_existing_tax_action_identities(
        account_id=account_id,
        source_event_id=chain.root.event.source_event_id,
        using=using,
    )
    corporate_action_ids: set[str] = set()
    for item in identities:
        if (
            getattr(item, "asset_code", None) != asset_code
            or getattr(item, "security_id", None) != asset_code
            or getattr(item, "source_namespace", None) != _OFFICIAL_NAMESPACE
            or getattr(item, "source_event_id", None) != chain.root.event.source_event_id
            or type(getattr(item, "corporate_action_id", None)) is not str
            or not item.corporate_action_id
        ):
            _blocked(
                "retained tax assessment identity conflicts with this official event",
                "CORPORATE_ACTION_OWNER_TAX_IDENTITY_CONFLICT",
            )
        corporate_action_ids.add(item.corporate_action_id)
    if len(corporate_action_ids) > 1:
        _blocked(
            "one logical disclosure has multiple retained tax action IDs",
            "CORPORATE_ACTION_OWNER_TAX_IDENTITY_CONFLICT",
        )
    if corporate_action_ids:
        corporate_action_id = next(iter(corporate_action_ids))
    else:
        identity = hashlib.sha256(
            f"simulated-corporate-action:{account_id}:{chain.root.event.source_event_id}".encode()
        ).hexdigest()
        corporate_action_id = f"szse:{identity}"
    if terms.cash_per_ten is None:
        _blocked(
            "cash dividend amount per ten shares is unavailable",
            "CORPORATE_ACTION_OWNER_TAX_TERMS_UNSUPPORTED",
        )
    with localcontext() as context:
        context.prec = 80
        dividend_per_share = terms.cash_per_ten / Decimal("10")
    try:
        return QualifiedCorporateActionTaxFacts(
            account_id=account_id,
            owner_user_id=owner_user_id,
            security_id=asset_code,
            asset_code=asset_code,
            corporate_action_id=corporate_action_id,
            source_namespace=_OFFICIAL_NAMESPACE,
            source_record_id=event.source_event_id,
            source_event_id=chain.root.event.source_event_id,
            source_revision_id=event.source_revision_id,
            source_revision_sha256=event.content_hash,
            source_payload_sha256=event.source_body_sha256,
            record_date=terms.record_date,
            effective_date=terms.ex_date,
            dividend_per_share=dividend_per_share,
        )
    except ValueError as error:
        _blocked(
            "qualified tax action facts exceed supported exact bounds",
            "CORPORATE_ACTION_OWNER_TAX_TERMS_UNSUPPORTED",
            cause=error,
        )
