"""Prepare owner-scoped corporate-action requests from retained official evidence."""

from __future__ import annotations

from datetime import date, datetime
from decimal import InvalidOperation
from zoneinfo import ZoneInfoNotFoundError

from django.db import DEFAULT_DB_ALIAS, DatabaseError

from apps.data_center.domain.security_disclosure_event import (
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
from apps.simulated_trading.application.corporate_action_owner_posting_read import (
    OwnerCorporateActionActivePostingHead,
)
from apps.simulated_trading.corporate_action_owner_event_history_composition import (
    read_current_owner_corporate_action_active_postings,
)
from apps.simulated_trading.corporate_action_owner_event_requests import (
    _build_tax_action,
    _make_cash_entitlement_request,
    _make_cash_payment_request,
    _make_share_entitlement_request,
    _make_share_settlement_request,
    _prepare_rights_no_effect,
)
from apps.simulated_trading.corporate_action_owner_event_support import (
    _OFFICIAL_NAMESPACE,
    _TAX_OPERATIONS,
    CorporateActionOwnerEventPreparationBlocked,
    PreparedOwnerOfficialAction,
    _blocked,
    _outstanding_cash_receivable,
    _outstanding_cash_receivable_from_revision_head,
    _outstanding_locked_shares,
    _outstanding_locked_shares_from_revision_head,
    _outstanding_share_receivable,
    _outstanding_share_receivable_from_revision_head,
    _read_event_postings,
    _read_owned_account,
    _read_policy,
    _read_record_date_proof,
    _require_paid_cash_receivable,
    _require_paid_cash_receivable_from_revision_head,
    _select_current_event_chain,
    _validate_calendar,
    _validate_distribution_event,
    _validate_input,
    _validate_ledger_rows,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
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
    VerifiedSzseActionSourceQualifier,
)
from core.exceptions import AgomTradeProException

_OPERATION_TO_STAGE: dict[str, tuple[CorporateActionKind, CorporateActionStage]] = {
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
    "rights_not_exercised": (
        CorporateActionKind.RIGHTS_ISSUE,
        CorporateActionStage.RIGHTS_NOT_EXERCISED,
    ),
}


def prepare_owner_official_corporate_action(
    *,
    account_id: int,
    owner_user_id: int,
    asset_code: str,
    event_id: str,
    action: OwnerCorporateActionOperation,
    settlement_date: date | None = None,
    as_of: datetime,
    runtime_environment: str,
    using: str = DEFAULT_DB_ALIAS,
    canonical_account_id: str | None = None,
) -> PreparedOwnerOfficialAction:
    """Build exact read-only requests from the current official event and account history.

    This composition does not post stages, issue grants, write Audit evidence, infer
    registry allocations, or establish current-window authority. Its caller must keep
    the independent current-window, owner-consent, audited-posting, and tax fences.
    """

    _validate_input(
        account_id=account_id,
        owner_user_id=owner_user_id,
        asset_code=asset_code,
        event_id=event_id,
        action=action,
        settlement_date=settlement_date,
        as_of=as_of,
        runtime_environment=runtime_environment,
        using=using,
    )
    try:
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
        reader = make_security_disclosure_event_reader(using=using)
        records = reader.execute(
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
        if event.event_type is SecurityDisclosureEventType.RIGHTS_ISSUE:
            return _prepare_rights_no_effect(
                action=action,
                event=event,
                chain=chain,
                account_id=account_id,
                owner_user_id=owner_user_id,
                asset_code=asset_code,
                as_of=as_of,
                decision_on=decision_on,
                exchange_timezone=exchange_timezone,
                runtime_environment=runtime_environment,
                using=using,
                ownership_reader=ownership_reader,
            )

        if event.event_type not in {
            SecurityDisclosureEventType.CASH_DIVIDEND,
            SecurityDisclosureEventType.STOCK_DIVIDEND,
        }:
            _blocked(
                "the current disclosure is not a supported cash or stock distribution",
                "CORPORATE_ACTION_OWNER_SOURCE_TYPE_UNSUPPORTED",
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
        ledger_rows = _read_event_postings(
            account_id=account_id,
            source_event_id=chain.root.event.source_event_id,
            using=using,
        )
        action_kind = (
            CorporateActionKind.CASH_DIVIDEND
            if event.event_type is SecurityDisclosureEventType.CASH_DIVIDEND
            else CorporateActionKind.SHARE_DISTRIBUTION
        )
        active_head: OwnerCorporateActionActivePostingHead | None = None
        needs_revision_read = any(
            row.entry_kind
            in {CorporateActionEntryKind.REVERSAL.value, CorporateActionEntryKind.SUCCESSOR.value}
            or row.source_revision_id != event.source_revision_id
            for row in ledger_rows
        )
        if needs_revision_read:
            active_head = read_current_owner_corporate_action_active_postings(
                account_id=account_id,
                owner_user_id=owner_user_id,
                canonical_account_id=canonical_account_id,
                source_namespace=_OFFICIAL_NAMESPACE,
                source_event_id=chain.root.event.source_event_id,
                source_record_id=event.source_event_id,
                source_revision_id=event.source_revision_id,
                security_id=asset_code,
                asset_code=asset_code,
                action_kind=action_kind,
                record_date=terms.record_date,
                effective_date=terms.ex_date,
                as_of=as_of,
                using=using,
            )
            if (
                type(active_head) is not OwnerCorporateActionActivePostingHead
                or active_head.account_id != account_id
                or active_head.owner_user_id != owner_user_id
                or active_head.canonical_account_id != canonical_account_id
                or active_head.source_namespace != _OFFICIAL_NAMESPACE
                or active_head.source_event_id != chain.root.event.source_event_id
                or active_head.source_record_id != event.source_event_id
                or active_head.source_revision_id != event.source_revision_id
                or active_head.security_id != asset_code
                or active_head.asset_code != asset_code
                or active_head.action_kind is not action_kind
                or active_head.record_date != terms.record_date
                or active_head.effective_date != terms.ex_date
            ):
                _blocked(
                    "the verified active posting head differs from the selected official source",
                    "CORPORATE_ACTION_OWNER_CORRECTION_HISTORY_INVALID",
                )
        else:
            _validate_ledger_rows(
                rows=ledger_rows,
                chain=chain,
                account_id=account_id,
                asset_code=asset_code,
                action_kind=action_kind,
                record_date=terms.record_date,
                effective_date=terms.ex_date,
                as_of=as_of,
            )
        target_stage = _OPERATION_TO_STAGE.get(action)
        if target_stage is not None and (
            any(entry.request.stage is target_stage[1] for entry in active_head.active_entries)
            if active_head is not None
            else any(row.stage == target_stage[1].value for row in ledger_rows)
        ):
            _blocked(
                "this source revision already contains the requested stage",
                "CORPORATE_ACTION_OWNER_STAGE_ALREADY_RECORDED",
            )
        source_qualifier = VerifiedSzseActionSourceQualifier(
            body_store_root=body_root,
            using=using,
        )
        source_reference: CorporateActionStageRequest
        requests: tuple[CorporateActionStageRequest, ...]
        tax_action: QualifiedCorporateActionTaxFacts | None = None

        if action in _TAX_OPERATIONS:
            if event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND:
                _blocked(
                    "tax actions are supported only for an explicitly qualified cash dividend",
                    "CORPORATE_ACTION_OWNER_TAX_SOURCE_UNSUPPORTED",
                )
            if terms.tax_treatment != "deferred_withholding" or terms.cash_per_ten is None:
                _blocked(
                    "cash dividend tax treatment or gross amount is not explicitly supported",
                    "CORPORATE_ACTION_OWNER_TAX_TERMS_UNSUPPORTED",
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
            source_reference = _make_cash_entitlement_request(
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
            if source_qualifier.verify_source(source_reference) is not True:
                _blocked(
                    "the prospective cash entitlement does not match current retained source facts",
                    "CORPORATE_ACTION_OWNER_SOURCE_QUALIFICATION_FAILED",
                )
            tax_action = _build_tax_action(
                account_id=account_id,
                owner_user_id=owner_user_id,
                asset_code=asset_code,
                event=event,
                chain=chain,
                terms=terms,
                using=using,
            )
            if source_qualifier.verify_tax_action(tax_action, as_of=as_of) is not True:
                _blocked(
                    "tax source facts do not match the retained current disclosure",
                    "CORPORATE_ACTION_OWNER_TAX_QUALIFICATION_FAILED",
                )
            if action == "tax_collect":
                if active_head is not None:
                    _require_paid_cash_receivable_from_revision_head(active_head.active_entries)
                else:
                    _require_paid_cash_receivable(ledger_rows)
            requests = ()
        elif action == "cash_entitlement":
            if event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND:
                _blocked(
                    "cash entitlement conflicts with source type",
                    "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
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
            source_reference = _make_cash_entitlement_request(
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
            requests = (source_reference,)
        elif action == "cash_payment":
            if event.event_type is not SecurityDisclosureEventType.CASH_DIVIDEND:
                _blocked(
                    "cash payment conflicts with source type",
                    "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
                )
            amount = (
                _outstanding_cash_receivable_from_revision_head(active_head.active_entries)
                if active_head is not None
                else _outstanding_cash_receivable(ledger_rows)
            )
            if terms.payment_date is None or decision_on < terms.payment_date:
                _blocked(
                    "the source-stated cash payment date has not been reached",
                    "CORPORATE_ACTION_OWNER_PAYMENT_DATE_NOT_REACHED",
                )
            source_reference = _make_cash_payment_request(
                account_id=account_id,
                owner_user_id=owner_user_id,
                asset_code=asset_code,
                event=event,
                chain=chain,
                terms=terms,
                amount=amount,
                as_of=as_of,
                stage_date=decision_on,
            )
            requests = (source_reference,)
        elif action == "share_entitlement":
            if event.event_type is not SecurityDisclosureEventType.STOCK_DIVIDEND:
                _blocked(
                    "share entitlement conflicts with source type",
                    "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
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
            source_reference = _make_share_entitlement_request(
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
            requests = (source_reference,)
        elif action == "share_delivery":
            if event.event_type is not SecurityDisclosureEventType.STOCK_DIVIDEND:
                _blocked(
                    "share delivery conflicts with source type",
                    "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
                )
            amount = (
                _outstanding_share_receivable_from_revision_head(active_head.active_entries)
                if active_head is not None
                else _outstanding_share_receivable(ledger_rows)
            )
            delivery_date = terms.share_delivery_date
            if delivery_date is None or decision_on < delivery_date:
                _blocked(
                    "the source-stated share delivery date has not been reached",
                    "CORPORATE_ACTION_OWNER_DELIVERY_DATE_NOT_REACHED",
                )
            source_reference = _make_share_settlement_request(
                account_id=account_id,
                owner_user_id=owner_user_id,
                asset_code=asset_code,
                event=event,
                chain=chain,
                terms=terms,
                amount=amount,
                stage=CorporateActionStage.SHARE_DELIVERY,
                stage_date=delivery_date,
                as_of=as_of,
            )
            requests = (source_reference,)
        elif action == "share_sellable_release":
            if event.event_type is not SecurityDisclosureEventType.STOCK_DIVIDEND:
                _blocked(
                    "share release conflicts with source type",
                    "CORPORATE_ACTION_OWNER_ACTION_SOURCE_MISMATCH",
                )
            sellable_date = terms.share_sellable_date
            if sellable_date is None or decision_on < sellable_date:
                _blocked(
                    "the source-stated first sellable date has not been reached",
                    "CORPORATE_ACTION_OWNER_SELLABLE_DATE_NOT_REACHED",
                )
            amount = (
                _outstanding_locked_shares_from_revision_head(active_head.active_entries)
                if active_head is not None
                else _outstanding_locked_shares(ledger_rows)
            )
            source_reference = _make_share_settlement_request(
                account_id=account_id,
                owner_user_id=owner_user_id,
                asset_code=asset_code,
                event=event,
                chain=chain,
                terms=terms,
                amount=amount,
                stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
                stage_date=decision_on,
                as_of=as_of,
            )
            requests = (source_reference,)
        else:
            _blocked(
                "the requested company-action operation is unsupported",
                "CORPORATE_ACTION_OWNER_OPERATION_INVALID",
            )

        if requests and source_qualifier.verify_source(source_reference) is not True:
            _blocked(
                "the prepared stage does not match current retained source facts",
                "CORPORATE_ACTION_OWNER_SOURCE_QUALIFICATION_FAILED",
            )
        return PreparedOwnerOfficialAction(
            action=action,
            event=event,
            source_reference=source_reference,
            requests=requests,
            tax_action=tax_action,
            settlement_date=settlement_date,
            source_terms=terms,
        )
    except CorporateActionOwnerEventPreparationBlocked:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        DatabaseError,
        InvalidOperation,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        ZoneInfoNotFoundError,
    ) as error:
        _blocked(
            "current official source or owner account evidence is unavailable",
            "CORPORATE_ACTION_OWNER_EVIDENCE_UNAVAILABLE",
            cause=error,
        )


__all__ = (
    "CorporateActionOwnerEventPreparationBlocked",
    "OwnerCorporateActionOperation",
    "PreparedOwnerOfficialAction",
    "prepare_owner_official_corporate_action",
)
