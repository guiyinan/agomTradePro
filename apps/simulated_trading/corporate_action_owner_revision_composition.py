"""Prepare complete current-source owner corrections without financial writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import InvalidOperation
from zoneinfo import ZoneInfoNotFoundError

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, DatabaseError, transaction

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SzseDistributionTerms,
)
from apps.data_center.security_disclosure_body_composition import (
    security_disclosure_window_pdf_store_root,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
    read_verified_szse_distribution,
)
from apps.simulated_trading.application.corporate_action_owner_intent import (
    OwnerCorporateActionOperation,
)
from apps.simulated_trading.application.corporate_action_owner_revision_preview import (
    build_owner_corporate_action_revision_preview,
)
from apps.simulated_trading.corporate_action_owner_event_requests import (
    _make_cash_entitlement_request,
    _make_cash_payment_request,
    _make_share_entitlement_request,
    _make_share_settlement_request,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    CorporateActionOwnerEventPreparationBlocked,
    PreparedOwnerOfficialAction,
    _blocked,
    _CurrentEventChain,
    _read_existing_tax_action_identities,
    _read_owned_account,
    _read_policy,
    _read_record_date_proof,
    _select_current_event_chain,
    _validate_calendar,
    _validate_distribution_event,
    _validate_input,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    read_locked_owner_corporate_action_revision_history,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    prepare_owner_corporate_action_revision as prepare_revision_batch,
)
from apps.simulated_trading.domain.corporate_action_owner_revision import (
    read_owner_corporate_action_revision_head,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
)
from core.exceptions import AgomTradeProException

_REVISION_OPERATIONS: dict[str, tuple[CorporateActionKind, CorporateActionStage]] = {
    "cash_entitlement": (
        CorporateActionKind.CASH_DIVIDEND,
        CorporateActionStage.CASH_ENTITLEMENT,
    ),
    "cash_payment": (CorporateActionKind.CASH_DIVIDEND, CorporateActionStage.CASH_PAYMENT),
    "share_entitlement": (
        CorporateActionKind.SHARE_DISTRIBUTION,
        CorporateActionStage.SHARE_ENTITLEMENT,
    ),
    "share_delivery": (
        CorporateActionKind.SHARE_DISTRIBUTION,
        CorporateActionStage.SHARE_DELIVERY,
    ),
    "share_sellable_release": (
        CorporateActionKind.SHARE_DISTRIBUTION,
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
    ),
}
_OFFICIAL_NAMESPACE = "exchange_official_disclosure"


def _canonical_account(value: object) -> bool:
    """Accept one explicit server-resolved canonical simulated-account identity."""
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= 192
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )


def _replacement_requests(
    *,
    action_kind: CorporateActionKind,
    stages: frozenset[CorporateActionStage],
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event: SecurityDisclosureEvent,
    chain: _CurrentEventChain,
    terms: SzseDistributionTerms,
    proof: RecordDateOwnershipProof,
    decision_on: date,
    as_of: datetime,
) -> tuple[CorporateActionStageRequest, ...]:
    """Build full current-source ordinary postings for exactly the active stage set."""
    if action_kind is CorporateActionKind.CASH_DIVIDEND:
        entitlement = _make_cash_entitlement_request(
            account_id=account_id,
            owner_user_id=owner_user_id,
            asset_code=asset_code,
            event=event,
            chain=chain,
            terms=terms,
            proof=proof,
            as_of=as_of,
            stage_date=decision_on,
        )
        requests = [entitlement]
        if CorporateActionStage.CASH_PAYMENT in stages:
            if terms.payment_date is None or decision_on < terms.payment_date:
                _blocked(
                    "the corrected cash payment date has not been reached",
                    "CORPORATE_ACTION_OWNER_PAYMENT_DATE_NOT_REACHED",
                )
            if entitlement.cash_amount is None:
                _blocked(
                    "the current full cash entitlement is unavailable",
                    "CORPORATE_ACTION_OWNER_CASH_TERMS_UNSUPPORTED",
                )
            requests.append(
                _make_cash_payment_request(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    asset_code=asset_code,
                    event=event,
                    chain=chain,
                    terms=terms,
                    amount=entitlement.cash_amount,
                    as_of=as_of,
                    stage_date=decision_on,
                )
            )
    else:
        entitlement = _make_share_entitlement_request(
            account_id=account_id,
            owner_user_id=owner_user_id,
            asset_code=asset_code,
            event=event,
            chain=chain,
            terms=terms,
            proof=proof,
            as_of=as_of,
            stage_date=decision_on,
        )
        requests = [entitlement]
        if entitlement.share_amount is None:
            _blocked(
                "the current full share entitlement is unavailable",
                "CORPORATE_ACTION_OWNER_SHARE_TERMS_UNSUPPORTED",
            )
        if CorporateActionStage.SHARE_DELIVERY in stages:
            if terms.share_delivery_date is None or decision_on < terms.share_delivery_date:
                _blocked(
                    "the corrected share delivery date has not been reached",
                    "CORPORATE_ACTION_OWNER_DELIVERY_DATE_NOT_REACHED",
                )
            requests.append(
                _make_share_settlement_request(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    asset_code=asset_code,
                    event=event,
                    chain=chain,
                    terms=terms,
                    amount=entitlement.share_amount,
                    stage=CorporateActionStage.SHARE_DELIVERY,
                    stage_date=terms.share_delivery_date,
                    as_of=as_of,
                )
            )
        if CorporateActionStage.SHARE_SELLABLE_RELEASE in stages:
            if terms.share_sellable_date is None or decision_on < terms.share_sellable_date:
                _blocked(
                    "the corrected first sellable date has not been reached",
                    "CORPORATE_ACTION_OWNER_SELLABLE_DATE_NOT_REACHED",
                )
            requests.append(
                _make_share_settlement_request(
                    account_id=account_id,
                    owner_user_id=owner_user_id,
                    asset_code=asset_code,
                    event=event,
                    chain=chain,
                    terms=terms,
                    amount=entitlement.share_amount,
                    stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
                    stage_date=decision_on,
                    as_of=as_of,
                )
            )
    if {request.stage for request in requests} != set(stages):
        _blocked(
            "the complete current stage set cannot be rebuilt from qualified source facts",
            "CORPORATE_ACTION_OWNER_REVISION_STAGE_SET_UNSUPPORTED",
        )
    # One qualification clock identifies this complete source/proof read. Preserve
    # each request's original source_observed_at and record-date observation fields.
    return tuple(replace(request, qualified_at=as_of) for request in requests)


def prepare_owner_official_corporate_action_revision(
    *,
    account_id: int,
    canonical_account_id: str,
    owner_user_id: int,
    asset_code: str,
    event_id: str,
    action: OwnerCorporateActionOperation,
    as_of: datetime,
    runtime_environment: str,
    using: str = DEFAULT_DB_ALIAS,
) -> PreparedOwnerOfficialAction:
    """Prepare a full verified correction for an immediate official-source successor.

    The returned ``source_reference`` is the Domain correction gate anchor, and
    ``requests`` contains every canonical reversal followed by every full-gross or
    full-quantity successor. This read-only service never authorizes or writes a
    posting; current owner consent, source window, spend, grant, and Audit gates
    remain the audited writer's responsibility. Modern tax journal rows and legacy
    withholding corrections are blocked because this service has no tax-revision
    or refund contract.
    """
    if type(action) is not str or action not in _REVISION_OPERATIONS:
        _blocked(
            "tax and rights operations are outside owner source correction preparation",
            "CORPORATE_ACTION_OWNER_REVISION_OPERATION_UNSUPPORTED",
        )
    if not _canonical_account(canonical_account_id):
        _blocked(
            "canonical account scope is invalid",
            "CORPORATE_ACTION_OWNER_INPUT_INVALID",
        )
    try:
        _validate_input(
            account_id=account_id,
            owner_user_id=owner_user_id,
            asset_code=asset_code,
            event_id=event_id,
            action=action,
            settlement_date=None,
            as_of=as_of,
            runtime_environment=runtime_environment,
            using=using,
        )
        account = _read_owned_account(
            account_id=account_id,
            owner_user_id=owner_user_id,
            using=using,
            as_of=as_of,
        )
        if account is None:
            _blocked(
                "active simulated account does not match the signed owner scope",
                "CORPORATE_ACTION_OWNER_ACCOUNT_SCOPE_INVALID",
            )
        if not account.cash_known or account.cash_reconciliation_status != "simulated_ledger":
            _blocked(
                "simulated account cash basis is unavailable",
                "CORPORATE_ACTION_OWNER_ACCOUNT_CASH_UNKNOWN",
            )

        ownership_reader = build_corporate_action_ownership_history_repository(
            runtime_environment=runtime_environment,
            using=using,
        )
        calendar = ownership_reader.read_verified_zero_origin_calendar(
            account_id=account_id,
            owner_user_id=owner_user_id,
            exchange=SecurityDisclosureExchange.SZSE.value,
            as_of=as_of,
        )
        decision_on, exchange_timezone = _validate_calendar(calendar, as_of=as_of)
        source_reader = make_security_disclosure_event_reader(using=using)
        records = source_reader.execute(
            SecurityDisclosureEventReadScope(
                as_of=as_of,
                exchange=SecurityDisclosureExchange.SZSE,
                asset_code=asset_code,
            )
        )
        chain = _select_current_event_chain(
            records,
            event_id=event_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        event = chain.current.event
        action_kind, selected_stage = _REVISION_OPERATIONS[action]
        expected_event_type = (
            SecurityDisclosureEventType.CASH_DIVIDEND
            if action_kind is CorporateActionKind.CASH_DIVIDEND
            else SecurityDisclosureEventType.STOCK_DIVIDEND
        )
        if event.event_type is not expected_event_type:
            _blocked(
                "the current source event does not match the requested correction family",
                "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
            )
        policy = _read_policy(
            runtime_environment=runtime_environment,
            decision_on=decision_on,
            exchange_timezone=exchange_timezone,
            event=event,
            as_of=as_of,
        )
        body_root = security_disclosure_window_pdf_store_root(policy.body_store_root)
        terms = read_verified_szse_distribution(event, body_store_root=body_root)
        if type(terms) is not SzseDistributionTerms:
            _blocked(
                "the exact original distribution terms are unavailable",
                "CORPORATE_ACTION_OWNER_SOURCE_TERMS_UNAVAILABLE",
            )
        _validate_distribution_event(event=event, terms=terms)
        proof = _read_record_date_proof(
            reader=ownership_reader,
            account_id=account_id,
            owner_user_id=owner_user_id,
            asset_code=asset_code,
            record_date=terms.record_date,
            as_of=as_of,
            runtime_environment=runtime_environment,
        )
        if proof.ownership_snapshot_observed_at != as_of:
            _blocked(
                "record-date ownership replay is not observed at the trusted preparation cutoff",
                "CORPORATE_ACTION_OWNER_OWNERSHIP_PROOF_INVALID",
            )
        qualifier = VerifiedSzseActionSourceQualifier(body_store_root=body_root, using=using)

        with transaction.atomic(using=using):
            history = read_locked_owner_corporate_action_revision_history(
                account=account,
                canonical_account_id=canonical_account_id,
                source_namespace=_OFFICIAL_NAMESPACE,
                source_event_id=chain.root.event.source_event_id,
                as_of=as_of,
                using=using,
            )
            if type(history) is not tuple or not history:
                _blocked(
                    "complete retained owner action history is unavailable",
                    "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE",
                )
            expected_head_revision_id = history[-1].request.source_revision_id
            active = read_owner_corporate_action_revision_head(
                history,
                expected_head_revision_id=expected_head_revision_id,
            )
            if not active:
                _blocked(
                    "retained owner action history has no active stage set",
                    "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE",
                )
            old_head = active[0].request
            if (
                any(
                    entry.request.source_revision_id != old_head.source_revision_id
                    or entry.request.source_record_id != old_head.source_record_id
                    for entry in active
                )
                or event.source_revision_id == old_head.source_revision_id
                or event.supersedes_source_event_id != old_head.source_record_id
                or event.supersedes_source_revision_id != old_head.source_revision_id
            ):
                _blocked(
                    "the current disclosure is not the direct successor of the active ledger source",
                    "CORPORATE_ACTION_OWNER_REVISION_PREDECESSOR_INVALID",
                )
            stages = frozenset(entry.request.stage for entry in active)
            if (
                any(entry.request.action_kind is not action_kind for entry in active)
                or selected_stage not in stages
            ):
                _blocked(
                    "the requested operation does not name an active stage in this event family",
                    "CORPORATE_ACTION_OWNER_REVISION_STAGE_SET_UNSUPPORTED",
                )
            if action_kind is CorporateActionKind.CASH_DIVIDEND and (
                _read_existing_tax_action_identities(
                    account_id=account_id,
                    source_event_id=chain.root.event.source_event_id,
                    using=using,
                )
            ):
                _blocked(
                    "cash correction needs an explicit modern tax journal revision contract",
                    "CORPORATE_ACTION_OWNER_TAX_REVISION_UNSUPPORTED",
                )
        replacements = _replacement_requests(
            action_kind=action_kind,
            stages=stages,
            account_id=account_id,
            owner_user_id=owner_user_id,
            asset_code=asset_code,
            event=event,
            chain=chain,
            terms=terms,
            proof=proof,
            decision_on=decision_on,
            as_of=as_of,
        )
        if any(qualifier.verify_source(request) is not True for request in replacements):
            _blocked(
                "one or more full replacement stages fail current source qualification",
                "CORPORATE_ACTION_OWNER_SOURCE_QUALIFICATION_FAILED",
            )
        prepared = prepare_revision_batch(
            history=history,
            expected_head_revision_id=expected_head_revision_id,
            replacement_requests=replacements,
            as_of_date=decision_on,
        )
        revision_preview = build_owner_corporate_action_revision_preview(
            prepared_batch=prepared,
            active_entries=active,
        )
        return PreparedOwnerOfficialAction(
            action=action,
            event=event,
            source_reference=prepared.gate_anchor,
            requests=prepared.requests,
            tax_action=None,
            settlement_date=None,
            source_terms=terms,
            revision_preview=revision_preview,
        )
    except CorporateActionOwnerEventPreparationBlocked:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        DatabaseError,
        InvalidOperation,
        ObjectDoesNotExist,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ZoneInfoNotFoundError,
    ) as error:
        _blocked(
            "current source or complete original owner history is unavailable",
            "CORPORATE_ACTION_OWNER_REVISION_EVIDENCE_UNAVAILABLE",
            cause=error,
        )


__all__ = ("prepare_owner_official_corporate_action_revision",)
