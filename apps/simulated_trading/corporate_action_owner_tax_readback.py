"""Read original owner tax assessment and financial receipts without current permission."""

from __future__ import annotations

from datetime import datetime

from django.db import connections

from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.audit.domain.system_audit_event import JSONValue
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    _event_id,
    _stream_id,
)
from apps.simulated_trading.audited_corporate_action_tax_liability_composition import (
    DjangoRetainedTaxAssessmentAuditVerifier,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_balance_repository import (
    _head,
    _scope,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_readback import (
    DjangoTaxLiabilityReadback,
    VerifiedTaxLiabilityOperation,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError

_MAX_ROWS = 10_000


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "原始税务评估或财务审计回执无法完整核对。",
        code="CORPORATE_ACTION_ORIGINAL_TAX_RECEIPTS_UNVERIFIED",
    )


def owner_tax_operation_row(
    operation: VerifiedTaxLiabilityOperation, *, asset_code: str
) -> dict[str, JSONValue]:
    """Present the independently verified operation's original clock and exact delta only."""
    receipt = operation.receipt
    return {
        "receipt_id": operation.event.event_id,
        "recorded_at": operation.material.recorded_at.isoformat(),
        "asset_code": asset_code,
        "stage_label": "模拟税务财务回执",
        "cash_delta": format(receipt.cash_delta, "f"),
        "share_delta": "0",
        "summary": (
            "本步骤没有扣款；以原始应付税款与财务回执为准。"
            if receipt.cash_delta == 0
            else f"原始模拟现金变化 {receipt.cash_delta} 元；本次扣缴变化 {receipt.collected_delta} 元。"
        ),
    }


def read_locked_owner_tax_receipts(
    *,
    account: SimulatedAccountModel,
    canonical_account_id: str,
    using: str,
    as_of: datetime,
) -> tuple[dict[str, JSONValue], ...]:
    """Verify every retained assessment, journal, Audit/Outbox and exact chain head.

    The caller already authenticated and locked the active physical owner row.
    These immutable historical receipts neither establish current statutory
    qualification nor imply complete coverage of yet-unassessed dispositions.
    """
    connection = connections[using]
    if (
        not connection.in_atomic_block
        or connection.get_autocommit()
        or type(account.pk) is not int
        or type(account.user_id) is not int
        or account.account_type != "simulated"
        or account.is_active is not True
        or account._state.db != using
        or type(canonical_account_id) is not str
        or not canonical_account_id
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise _blocked()
    actual = SimulatedAccountModel._base_manager.using(using).select_for_update().get(pk=account.pk)
    if (
        actual.user_id != account.user_id
        or actual.account_type != account.account_type
        or actual.updated_at != account.updated_at
        or actual.updated_at > as_of
        or actual.is_active is not True
    ):
        raise _blocked()
    headers = tuple(
        Header._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account.pk)
        .order_by("pk")[: _MAX_ROWS + 1]
    )
    operations = tuple(
        Operation._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account.pk)
        .order_by("scope_sha256", "sequence")[: _MAX_ROWS + 1]
    )
    if len(headers) > _MAX_ROWS or len(operations) > _MAX_ROWS:
        raise _blocked()
    audit = build_tax_assessment_audit_coordinator(using=using)
    readback = DjangoTaxLiabilityReadback(
        using=using,
        audit=audit,
        assessment_audit=DjangoRetainedTaxAssessmentAuditVerifier(audit=audit),
    )
    groups: dict[str, list[Header]] = {}
    retained: dict[str, list[Operation]] = {}
    for header in headers:
        if header.owner_user_id != account.user_id or header.recorded_at > as_of:
            raise _blocked()
        groups.setdefault(tax_liability_scope_sha256(_scope(header)), []).append(header)
    for operation in operations:
        if (
            operation.owner_user_id != account.user_id
            or operation.scope_sha256 not in groups
            or operation.canonical_account_namespace != "account"
            or operation.canonical_account_id != canonical_account_id
        ):
            raise _blocked()
        retained.setdefault(operation.scope_sha256, []).append(operation)
    rows: list[dict[str, JSONValue]] = []
    with audit.caller_owned_readonly():
        for key, members in sorted(groups.items()):
            head = _head(members)
            for header in members:
                readback.verify_assessment(header, as_of=as_of)
                rows.append(
                    {
                        "receipt_id": _event_id(header),
                        "recorded_at": header.recorded_at.isoformat(),
                        "asset_code": header.asset_code,
                        "stage_label": "模拟税务评估",
                        "cash_delta": "0",
                        "share_delta": "0",
                        "summary": "原始评估与审计回执已核对；评估本身没有扣款。",
                    }
                )
            expected = audit.get_winner_targeted(
                event_id=_event_id(head), event_version="1", as_of=as_of, lock=True
            )
            if (
                expected is None
                or audit.get_current_head_targeted(
                    stream_id=_stream_id(head), scope=expected.scope, as_of=as_of, lock=True
                )
                != expected
            ):
                raise _blocked()
            if key not in retained:
                continue
            chain = readback.read_chain(
                scope=_scope(head),
                canonical_account_namespace="account",
                canonical_account_id=canonical_account_id,
                currency=SimulatedDividendTaxCurrency.CNY,
                as_of=as_of,
            )
            if not chain or len(chain) != len(retained[key]):
                raise _blocked()
            last = chain[-1]
            if (
                audit.get_current_head_targeted(
                    stream_id=last.event.stream_id, scope=last.event.scope, as_of=as_of, lock=True
                )
                != last.event
            ):
                raise _blocked()
            rows.extend(
                owner_tax_operation_row(operation, asset_code=head.asset_code)
                for operation in chain
            )
    # ISO strings may have different offsets. Sort by original instants, never
    # their lexical representation or this read's current query clock.
    return tuple(sorted(rows, key=_original_receipt_clock, reverse=True))


def _original_receipt_clock(row: dict[str, JSONValue]) -> datetime:
    raw = row["recorded_at"]
    if type(raw) is not str:
        raise _blocked()
    return datetime.fromisoformat(raw)
