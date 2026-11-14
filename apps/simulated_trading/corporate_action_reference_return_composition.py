"""Owner-scoped gross reference-holding comparisons from independently verified facts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS, connections, models
from django.utils import timezone

from apps.audit.domain.system_audit_event import JSONValue
from apps.data_center.application.public_published_queries import (
    get_retained_historical_price_for_session,
)
from apps.simulated_trading.application.corporate_action_reference_return import (
    CorporateActionReferenceReturnInputs,
    CorporateActionReferenceReturnReport,
    build_corporate_action_reference_return,
)
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_owner_balance_composition import (
    OwnerCorporateActionBalanceReadback,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    OwnerCorporateActionPostingState,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionKind
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
)
from core.exceptions import AgomTradeProException, BusinessLogicError


@dataclass(frozen=True, slots=True)
class OwnerReferenceReturnReadback:
    """A separate reference basket, never an account cash-flow-adjusted return."""

    summary: str
    rows: tuple[dict[str, JSONValue], ...]
    checked_at: datetime


def _unknown(account_id: int, asset_code: str | None, reason: str) -> OwnerReferenceReturnReadback:
    return OwnerReferenceReturnReadback(
        "登记日参考持仓的税前、未再投资权益回报尚待核对；需要完整当前权益及除权日前后两日的原始收盘资料。",
        (
            {
                "account_id": account_id,
                "asset_code": asset_code,
                "status": "unknown",
                "reason_code": reason,
                "knowledge_semantics": "currently_known_reference_holding",
                "return_basis": "gross_unreinvested_record_date_holding",
                "must_not_use_for_decision": True,
            },
        ),
        timezone.now(),
    )


def _report_row(
    account_id: int, report: CorporateActionReferenceReturnReport
) -> dict[str, JSONValue]:
    before, after = report.comparison.opening, report.comparison.closing
    opening, closing = report.opening_source.price, report.closing_source.price
    return {
        "account_id": account_id,
        "asset_code": report.asset_code,
        "status": "complete",
        "reason_code": None,
        "record_date": report.record_date.isoformat(),
        "reference_quantity": format(report.comparison.reference_quantity, "f"),
        "ex_date": after.day.isoformat(),
        "opening_date": before.day.isoformat(),
        "closing_date": after.day.isoformat(),
        "opening_price": format(opening.values.close, "f"),
        "closing_price": format(closing.values.close, "f"),
        "opening_value": format(before.total_value, "f"),
        "closing_value": format(after.total_value, "f"),
        "wealth_change": format(report.comparison.wealth_change, "f"),
        "closing_cash": format(after.cash, "f"),
        "closing_dividend_receivable": format(after.dividend_receivable, "f"),
        "closing_physical_shares": format(after.physical_shares, "f"),
        "closing_share_receivable": format(after.share_receivable, "f"),
        "currency": opening.amount_unit,
        "quantity_unit": opening.volume_unit,
        "knowledge_cutoff": report.knowledge_cutoff.isoformat(),
        "valid_until": report.valid_until.isoformat(),
        "knowledge_semantics": report.knowledge_semantics,
        "return_basis": report.return_basis,
        "must_not_use_for_decision": True,
        "source_observed_at": None,
        "price_publication_ids": [opening.publication_id, closing.publication_id],
        "price_interval_end_ats": [
            opening.interval_end_at.isoformat(),
            closing.interval_end_at.isoformat(),
        ],
        "price_source_available_ats": [
            opening.source_available_at.isoformat(),
            closing.source_available_at.isoformat(),
        ],
    }


def read_locked_owner_reference_returns(
    *,
    account: SimulatedAccountModel,
    asset_codes: tuple[str, ...],
    ledger: OwnerCorporateActionPostingState,
    balance_read: OwnerCorporateActionBalanceReadback,
    environment: str,
    using: str = DEFAULT_DB_ALIAS,
) -> OwnerReferenceReturnReadback:
    """Read one asset/event's fixed record-date basket using original raw price proofs.

    The owner read already verifies the complete original ledger and its Audit
    pairs. Current entitlement references retain those actual transfer dates.
    Account cash, later ordinary trades and accepted tax debt are deliberately
    absent from this declared before-tax reference basket.
    """
    code = asset_codes[0] if len(asset_codes) == 1 else None
    reason = "REFERENCE_CURRENT_ENTITLEMENT_UNVERIFIED"
    try:
        connection = connections[using]
        if (
            using != DEFAULT_DB_ALIAS
            or account._state.db != using
            or not connection.in_atomic_block
            or connection.get_autocommit()
            or len(connection.atomic_blocks) != 1
        ):
            raise BusinessLogicError(
                "参考权益核对需要唯一账户事务。", code="REFERENCE_RETURN_TRANSACTION_INVALID"
            )
        if code is None:
            return _unknown(account.pk, None, "REFERENCE_ONE_ASSET_REQUIRED")
        if any(
            entry.request.asset_code == code
            and entry.request.action_kind is CorporateActionKind.RIGHTS_ISSUE
            for entry in ledger.revision_entries
        ):
            return _unknown(account.pk, code, "REFERENCE_RIGHTS_COMPARISON_UNSUPPORTED")
        coverage = balance_read.tax_coverage
        if (
            coverage is None
            or coverage.coverage_status is not TaxCashCoverageStatus.COMPLETE
            or balance_read.entitlements is None
        ):
            return _unknown(account.pk, code, reason)
        selected = tuple(item for item in balance_read.entitlements if item.asset_code == code)
        if len(selected) != 1 or not selected[0].cash_complete or not selected[0].shares_complete:
            return _unknown(account.pk, code, reason)
        references = selected[0].current_entitlement_references
        if references is None:
            return _unknown(account.pk, code, reason)
        if len(references) != 1:
            return _unknown(account.pk, code, "REFERENCE_ONE_EVENT_FAMILY_REQUIRED")
        reference = references[0]
        reference.__post_init__()
        marks = tuple(mark for mark in balance_read.marks if mark.query.asset_code == code)
        if len(marks) != 1:
            return _unknown(account.pk, code, "REFERENCE_CURRENT_RAW_MARK_UNVERIFIED")
        mark = marks[0]
        # Keep every included component at the owner read's original snapshot.
        # Final checks below still use the actual completion time and original lease.
        cutoff = balance_read.checked_at
        coverage.verify_for(coverage.query, as_of=cutoff)
        if (
            coverage.valid_until is None
            or coverage.query.physical_account_id != account.pk
            or coverage.query.owner_user_id != account.user_id
        ):
            return _unknown(account.pk, code, reason)
        mark.verify_for(mark.query, as_of=cutoff)
        action = reference.restatement_entitlement
        before_dates = tuple(
            day.calendar_date
            for day in mark.calendar.snapshot.days
            if day.is_open and day.calendar_date < action.effective_on
        )
        if not before_dates or action.effective_on > mark.trade_date:
            return _unknown(account.pk, code, "REFERENCE_EX_DATE_NOT_CLOSED")
        field = PositionModel._meta.get_field("quantity")
        if not isinstance(field, models.DecimalField) or field.decimal_places is None:
            return _unknown(account.pk, code, "REFERENCE_QUANTITY_SCALE_UNVERIFIED")
        sources = tuple(
            get_retained_historical_price_for_session(
                code,
                trade_date=day,
                expected_publication_key=mark.policy_binding.policy.publication_key,
                knowledge_cutoff=cutoff,
                environment=environment,
                using=using,
            )
            for day in (max(before_dates), action.effective_on)
        )
        opening_source = sources[0].evidence
        closing_source = sources[1].evidence
        if opening_source is None or closing_source is None:
            return _unknown(account.pk, code, "REFERENCE_ARCHIVED_RAW_CLOSE_UNVERIFIED")
        report = build_corporate_action_reference_return(
            CorporateActionReferenceReturnInputs(
                record_date=reference.record_date,
                reference_quantity=reference.reference_quantity,
                entitlement=action,
                current_mark=mark,
                opening_source=opening_source,
                closing_source=closing_source,
                currency_quantum=balance_read.balance.currency_quantum,
                quantity_quantum=Decimal(1).scaleb(-field.decimal_places),
                knowledge_cutoff=cutoff,
                source_scope_valid_until=coverage.valid_until,
            )
        )
        checked = timezone.now()
        coverage.verify_for(coverage.query, as_of=checked)
        mark.verify_for(mark.query, as_of=checked)
        if checked < cutoff or not checked < report.valid_until:
            return _unknown(account.pk, code, "REFERENCE_SOURCE_SCOPE_EXPIRED")
        comparison = report.comparison
        summary = (
            f"{code}：按当前已知资料回看，登记日参考持仓数量 {comparison.reference_quantity:f}；"
            f"税前、未再投资。{comparison.opening.day.isoformat()} 至 {comparison.closing.day.isoformat()}，"
            f"未复权收盘 {report.opening_source.price.values.close:f} → {report.closing_source.price.values.close:f}，"
            f"连同现金及股份权益的参考价值 {comparison.opening.total_value:f} → {comparison.closing.total_value:f} 元，"
            f"变动 {comparison.wealth_change:f} 元。到账和交付按原实际日期计入；限模拟核对。"
        )
        row = _report_row(account.pk, report)
        row.update(
            {
                "source_event_id": reference.source_event_id,
                "logical_source_event_id": reference.logical_source_event_id,
                "source_revision_id": reference.source_revision_id,
                "source_body_sha256": reference.source_body_sha256,
                "event_content_sha256": reference.event_content_sha256,
            }
        )
        return OwnerReferenceReturnReadback(summary, (row,), checked)
    except (AgomTradeProException, ArithmeticError, AttributeError, OSError, TypeError, ValueError):
        return _unknown(account.pk, code, "REFERENCE_RETURN_EVIDENCE_UNVERIFIED")


__all__ = ("OwnerReferenceReturnReadback", "read_locked_owner_reference_returns")
