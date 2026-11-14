"""Owner-only retained event discovery and original financial readback."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.audit.domain.system_audit_event import JSONValue
from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureExchange,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.simulated_trading.corporate_action_owner_account_composition import (
    OwnerCorporateActionAccount,
)
from apps.simulated_trading.corporate_action_owner_balance_composition import (
    read_locked_owner_corporate_action_balance,
)
from apps.simulated_trading.corporate_action_owner_event_support import _select_current_event_chain
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    read_locked_owner_corporate_action_posting_state,
)
from apps.simulated_trading.corporate_action_owner_tax_readback import (
    _original_receipt_clock,
    read_locked_owner_tax_receipts,
)
from apps.simulated_trading.execution_current_reference_composition import (
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import AuthorizationError, BusinessLogicError

_MAX_ASSETS = 2_000
_MAX_EVENTS = 10_000


def empty_owner_workflow_payload(account_id: int) -> dict[str, JSONValue]:
    """Publish explicit unknown balances without manufacturing financial observations."""
    return {
        "account_id": account_id,
        "outcome": "blocked",
        "summary": "请核对本人模拟账户、分项授权与官方资料后再办理。",
        "blocking_reason": "CORPORATE_ACTION_CURRENT_FACTS_UNVERIFIED",
        "source_observed_at": None,
        "checked_at": None,
        "freshness_status": "unknown",
        "reliability_status": "unverified",
        "must_not_use_for_decision": True,
        "book_cash": None,
        "spendable_cash": None,
        "net_asset_value": None,
        "dividend_receivable": None,
        "share_receivable": None,
        "tax_payable": None,
        "tax_coverage_status": "unknown",
        "valuation_trade_dates": [],
        "valuation_source_observed_at": None,
        "events": [],
        "audit_receipts": [],
    }


def read_owner_workflow_events(
    account: OwnerCorporateActionAccount,
    *,
    as_of: datetime,
) -> tuple[PersistedSecurityDisclosureEvent, ...]:
    """Read only retained SZSE events within the actual owned account's asset scope."""
    if len(account.asset_codes) > _MAX_ASSETS:
        raise BusinessLogicError(
            "账户证券范围过大，请联系管理员核对。", code="CORPORATE_ACTION_EVENT_SCOPE_TOO_LARGE"
        )
    reader = make_security_disclosure_event_reader(using=DEFAULT_DB_ALIAS)
    result: list[PersistedSecurityDisclosureEvent] = []
    for code in account.asset_codes:
        if len(code) != 9 or not code[:6].isdigit() or not code.endswith(".SZ"):
            continue
        records = reader.execute(
            SecurityDisclosureEventReadScope(
                as_of=as_of, exchange=SecurityDisclosureExchange.SZSE, asset_code=code
            )
        )
        if len(result) + len(records) > _MAX_EVENTS:
            raise BusinessLogicError(
                "事件数量超过本次核对范围。", code="CORPORATE_ACTION_EVENT_SCOPE_TOO_LARGE"
            )
        for record in records:
            if type(record) is not PersistedSecurityDisclosureEvent:
                raise BusinessLogicError(
                    "公告留存记录不可核对。", code="CORPORATE_ACTION_SOURCE_RECORD_INVALID"
                )
            record.__post_init__()
            if record.event.asset_code != code or record.recorded_at > as_of:
                raise BusinessLogicError(
                    "公告留存范围已变化。", code="CORPORATE_ACTION_SOURCE_RECORD_INVALID"
                )
            result.append(record)
    return tuple(result)


def select_owner_workflow_event(
    account: OwnerCorporateActionAccount,
    *,
    event_id: str,
    as_of: datetime,
) -> SecurityDisclosureEvent:
    """Resolve a native source event ID only after owner and held/traded scope checks."""
    if (
        type(event_id) is not str
        or not event_id
        or len(event_id) > 200
        or event_id != event_id.strip()
    ):
        raise BusinessLogicError(
            "请选择当前列表中的事件。", code="CORPORATE_ACTION_EVENT_SELECTION_INVALID"
        )
    records = read_owner_workflow_events(account, as_of=as_of)
    candidates = {row.event.asset_code for row in records if row.event.source_event_id == event_id}
    if len(candidates) != 1:
        raise BusinessLogicError(
            "所选事件不属于本账户证券范围或身份不唯一。",
            code="CORPORATE_ACTION_EVENT_SELECTION_INVALID",
        )
    code = next(iter(candidates))
    return _select_current_event_chain(
        tuple(row for row in records if row.event.asset_code == code),
        event_id=event_id,
        asset_code=code,
        as_of=as_of,
    ).current.event


def _source_day(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    # Preserve a source date as a date and a full timestamp as a full timestamp.
    return value.isoformat()


def owner_workflow_event_rows(
    account: OwnerCorporateActionAccount,
    records: tuple[PersistedSecurityDisclosureEvent, ...],
) -> list[JSONValue]:
    """Present retained source facts without claiming current-window completeness."""
    replaced = {
        (
            row.event.asset_code,
            row.event.supersedes_source_event_id,
            row.event.supersedes_source_revision_id,
        )
        for row in records
    }
    rows: list[JSONValue] = []
    for record in sorted(
        records, key=lambda row: (row.recorded_at, row.event.identity_key), reverse=True
    ):
        event = record.event
        if (event.asset_code, event.source_event_id, event.source_revision_id) in replaced:
            continue
        rows.append(
            {
                "account_id": account.account_id,
                "event_id": event.source_event_id,
                "asset_code": event.asset_code,
                "title": event.raw_event_type,
                "event_type": event.event_type.value,
                "announced_on": _source_day(event.announced_at),
                "record_date": None,
                "effective_date": _source_day(event.effective_at),
                "source_observed_at": event.first_seen_at.isoformat(),
                "status": "待核对原文与当前窗口",
                "blocking_reason": "CORPORATE_ACTION_EVENT_PREPARATION_REQUIRED",
            }
        )
    return rows


def read_owner_workflow_source_payload(
    account: OwnerCorporateActionAccount,
) -> dict[str, JSONValue]:
    """Read retained event choices without spending the source lease on balance reconstruction.

    This discovery result grants no current-window or financial qualification.
    Complete balances and original financial receipts remain an independent read.
    """
    cutoff = timezone.now()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        owned = (
            SimulatedAccountModel._base_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(
                pk=account.account_id,
                user_id=account.owner_user_id,
                account_type="simulated",
                is_active=True,
            )
            .first()
        )
        if owned is None:
            raise AuthorizationError("仅可读取本人启用中的模拟账户。")
        records = read_owner_workflow_events(account, as_of=cutoff)
        checked = timezone.now()
        if checked < cutoff:
            raise BusinessLogicError(
                "读取时钟无法核对。", code="CORPORATE_ACTION_READ_CLOCK_INVALID"
            )
    source_clocks = tuple(row.event.first_seen_at for row in records)
    payload = empty_owner_workflow_payload(account.account_id)
    payload.update(
        {
            "outcome": "success",
            "summary": "公告资料已留存，请选择一项操作核对；余额与原始财务回执请单独读取。",
            "blocking_reason": "CORPORATE_ACTION_BALANCE_READBACK_PENDING",
            "checked_at": checked.isoformat(),
            "source_observed_at": max(source_clocks).isoformat() if source_clocks else None,
            "freshness_status": "not_qualified",
            "reliability_status": "retained_sources_only",
            "events": owner_workflow_event_rows(account, records),
        }
    )
    return payload


def read_owner_workflow_payload(account: OwnerCorporateActionAccount) -> dict[str, JSONValue]:
    """Read original book evidence; unresolved marks and tax coverage remain unknown.

    No legacy position price has an observation clock, so it cannot establish
    qualified NAV. A local empty tax ledger does not prove no unassessed tax.
    """
    result = empty_owner_workflow_payload(account.account_id)
    using = DEFAULT_DB_ALIAS
    with transaction.atomic(using=using):
        row = (
            SimulatedAccountModel._base_manager.using(using)
            .select_for_update()
            .filter(
                pk=account.account_id,
                user_id=account.owner_user_id,
                account_type="simulated",
                is_active=True,
            )
            .first()
        )
        if row is None:
            raise AuthorizationError("仅可读取本人启用中的模拟账户。")
        cutoff = timezone.now()
        ledger = read_locked_owner_corporate_action_posting_state(
            account=row, canonical_account_id=account.source.account_id, as_of=cutoff, using=using
        )
        if row.cash_known is True and row.cash_reconciliation_status == "simulated_ledger":
            if (
                type(row.current_cash) is not Decimal
                or not row.current_cash.is_finite()
                or row.current_cash < 0
            ):
                raise BusinessLogicError(
                    "模拟账面现金需要核对。", code="CORPORATE_ACTION_CASH_INVALID"
                )
            result["book_cash"] = format(row.current_cash, "f")
        result["dividend_receivable"] = format(ledger.dividend_receivable, "f")
        positive_shares = tuple(value for _, value in ledger.share_receivables if value != 0)
        if len(positive_shares) <= 1:
            result["share_receivable"] = format(
                positive_shares[0] if positive_shares else Decimal(0), "f"
            )
        tax_receipts = read_locked_owner_tax_receipts(
            account=row, canonical_account_id=account.source.account_id, using=using, as_of=cutoff
        )
        receipts = (*ledger.audit_receipts, *tax_receipts)
        sorted_receipts: list[dict[str, JSONValue]] = sorted(
            receipts, key=_original_receipt_clock, reverse=True
        )
        result["audit_receipts"] = sorted_receipts
        balance_read = read_locked_owner_corporate_action_balance(
            account=row,
            canonical_account_id=account.source.account_id,
            ledger=ledger,
            environment=get_simulated_execution_runtime_environment(),
            using=using,
        )
        balance = balance_read.balance
        result["dividend_receivable"] = (
            format(balance.dividend_receivable, "f")
            if balance.dividend_receivable is not None
            else None
        )
        if balance_read.entitlements is None or not all(
            item.shares_complete for item in balance_read.entitlements
        ):
            result["share_receivable"] = None
        result["tax_payable"] = (
            format(balance.tax_payable, "f") if balance.tax_payable is not None else None
        )
        result["spendable_cash"] = (
            format(balance.spendable_cash, "f") if balance.spendable_cash is not None else None
        )
        result["net_asset_value"] = (
            format(balance.net_asset_value, "f") if balance.net_asset_value is not None else None
        )
        result["tax_coverage_status"] = (
            balance_read.tax_coverage.coverage_status.value
            if balance_read.tax_coverage is not None
            else "unknown"
        )
        result["valuation_trade_dates"] = [
            mark.trade_date.isoformat() for mark in balance_read.marks
        ]
        cutoff = balance_read.checked_at
    records = read_owner_workflow_events(account, as_of=cutoff)
    result["events"] = owner_workflow_event_rows(account, records)
    result["source_observed_at"] = (
        max(row.event.first_seen_at for row in records).isoformat() if records else None
    )
    result["checked_at"] = cutoff.isoformat()
    result["outcome"] = "partial"
    result["freshness_status"] = "retained_history"
    result["reliability_status"] = "original_ledger_verified"
    result["summary"] = (
        "已核对原始模拟账本与审计回执；办理前还需核对当前官方窗口和所选分项授权。净值与可用资金待完整估值及税务覆盖核对。"
    )
    result["blocking_reason"] = "CORPORATE_ACTION_VALUATION_AND_TAX_COVERAGE_REQUIRED"
    if result["net_asset_value"] is not None and result["spendable_cash"] is not None:
        result["blocking_reason"] = None
        result["freshness_status"] = "qualified_closed_session_valuation"
        result["reliability_status"] = "original_ledger_and_current_sources_verified"
        result["summary"] = (
            "已核对本人模拟账本、完整模拟税款覆盖及独立未复权收盘估值；办理新事项仍需核对所选分项授权。"
        )
    return result
