"""Read original balances with independent raw marks and complete simulated tax coverage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, localcontext

from django.db import DEFAULT_DB_ALIAS, connections, models
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkProof,
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_current_entitlement_coverage import (
    CurrentAssetEntitlementCoverage,
)
from apps.simulated_trading.corporate_action_nav_mark_composition import (
    build_corporate_action_nav_raw_mark_reader,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    OwnerCorporateActionPostingState,
)
from apps.simulated_trading.corporate_action_owner_runtime_composition import (
    read_owner_corporate_action_workflow_runtime,
)
from apps.simulated_trading.corporate_action_tax_cash_coverage_composition import (
    DjangoCorporateActionTaxCashCoverageReader,
)
from apps.simulated_trading.domain.corporate_action_tax_balance import CorporateActionTaxBalance
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.order_reservation_repository_support import (
    validate_reservation_owner_row,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
)
from core.exceptions import AgomTradeProException, BusinessLogicError

_MAX_POSITIONS = 2_000


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "账户净值与可用现金需要完整证据核对。", code="CORPORATE_ACTION_BALANCE_UNVERIFIED"
    )


def _exact_amount(value: Decimal, *, quantum: Decimal) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise _blocked()
    with localcontext() as context:
        context.prec = 96
        if value.quantize(quantum) != value:
            # A raw mark supplies no monetary rounding rule. Never silently
            # choose one for a sub-quantum valuation.
            raise _blocked()
    return value


def _mark_selection(
    proof: SimulatedCorporateActionNavRawMarkProof,
    *,
    original: SimulatedCorporateActionNavRawMarkProof,
) -> str:
    """Retain every original source pin while excluding only three local read cutoffs."""
    normalized = replace(
        proof.classification,
        read_at=original.classification.read_at,
        identity_evidence=replace(
            proof.classification.identity_evidence,
            selection=replace(
                proof.classification.identity_evidence.selection,
                selected_at=original.classification.identity_evidence.selection.selected_at,
            ),
        ),
    )
    payload = proof.to_payload()
    for field in ("reading_started_at", "checked_at", "knowledge_cutoff"):
        del payload[field]
    payload["classification_sha256"] = normalized.content_hash
    payload["policy_binding_sha256"] = proof.policy_binding.selection_sha256
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionBalanceReadback:
    """Exact local simulation projections with separate original mark clocks."""

    balance: CorporateActionTaxBalance
    tax_coverage: TaxCashCoverageSnapshot | None
    marks: tuple[SimulatedCorporateActionNavRawMarkProof, ...]
    checked_at: datetime
    entitlements: tuple[CurrentAssetEntitlementCoverage, ...] | None = None


def read_locked_owner_corporate_action_balance(
    *,
    account: SimulatedAccountModel,
    canonical_account_id: str,
    ledger: OwnerCorporateActionPostingState,
    environment: str,
    using: str = DEFAULT_DB_ALIAS,
) -> OwnerCorporateActionBalanceReadback:
    """Value actual quantities and undelivered share rights, without legacy price authority.

    Source completeness and accepted tax debt are independent of price marks.
    A missing mark leaves NAV unknown while completely covered spendable cash
    may remain known. No current permission is required for historical receipts.
    """
    if (
        using != DEFAULT_DB_ALIAS
        or account._state.db != using
        or not connections[using].in_atomic_block
        or connections[using].get_autocommit()
        or type(account.user_id) is not int
    ):
        raise _blocked()
    owner_user_id = account.user_id
    locked = SimulatedAccountModel._base_manager.using(using).select_for_update().get(pk=account.pk)
    if (
        locked.user_id != owner_user_id
        or locked.account_type != "simulated"
        or locked.is_active is not True
        or locked.updated_at != account.updated_at
        or locked.current_cash != account.current_cash
    ):
        raise _blocked()
    field = SimulatedAccountModel._meta.get_field("current_cash")
    if not isinstance(field, models.DecimalField) or field.decimal_places is None:
        raise _blocked()
    quantum = Decimal(1).scaleb(-field.decimal_places)
    cash = (
        _exact_amount(account.current_cash, quantum=quantum)
        if account.cash_known is True and account.cash_reconciliation_status == "simulated_ledger"
        else None
    )
    holds = Decimal("0")
    with localcontext() as context:
        context.prec = 96
        for row in lock_active_order_reservations(account_id=account.pk, using=using):
            validate_reservation_owner_row(row=row, account=account, user_id=owner_user_id)
            validated_plan_snapshot(row)
            holds += decode_order_reservation(row).remaining_cash
    _exact_amount(holds, quantum=quantum)
    coverage_reader = DjangoCorporateActionTaxCashCoverageReader(
        runtime_environment=environment, using=using
    )
    coverage: TaxCashCoverageSnapshot | None = None
    try:
        coverage = coverage_reader.read_locked(
            physical_account_id=account.pk, owner_user_id=owner_user_id, using=using
        )
        if (
            coverage.query.canonical_account_id != canonical_account_id
            or coverage.currency_quantum != quantum
        ):
            raise _blocked()
    except (AgomTradeProException, ArithmeticError, AttributeError, OSError, TypeError, ValueError):
        coverage = None
    complete = (
        coverage is not None
        and coverage.coverage_status is TaxCashCoverageStatus.COMPLETE
        and coverage.modeled_unapplied_tax_reserve == 0
    )
    debt = coverage.accepted_unpaid_tax if complete and coverage is not None else None
    cash_rights_complete = False
    share_rights_complete = False
    entitlements: tuple[CurrentAssetEntitlementCoverage, ...] | None = None
    mark_floors: dict[str, date] = {}
    if complete and coverage is not None:
        try:
            entitlements = coverage_reader.read_current_entitlement_coverage(coverage, using=using)
            cash_rights_complete = all(item.cash_complete for item in entitlements)
            share_rights_complete = all(item.shares_complete for item in entitlements)
            mark_floors = {
                item.asset_code: item.minimum_mark_date
                for item in entitlements
                if item.minimum_mark_date is not None
            }
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            TypeError,
            ValueError,
        ):
            pass
    marks: list[SimulatedCorporateActionNavRawMarkProof] = []
    marked_assets: Decimal | None = None
    if complete and share_rights_complete:
        try:
            rows = tuple(
                PositionModel._base_manager.using(using)
                .select_for_update()
                .filter(account_id=account.pk)
                .order_by("asset_code")[: _MAX_POSITIONS + 1]
            )
            if len(rows) > _MAX_POSITIONS or len({row.asset_code for row in rows}) != len(rows):
                raise _blocked()
            quantities: dict[str, Decimal] = {}
            types: dict[str, str] = {}
            with localcontext() as context:
                context.prec = 96
                for position_row in rows:
                    if (
                        type(position_row.quantity) is not Decimal
                        or not position_row.quantity.is_finite()
                        or position_row.quantity < 0
                    ):
                        raise _blocked()
                    quantities[position_row.asset_code] = position_row.quantity
                    types[position_row.asset_code] = position_row.asset_type
                for code, quantity in ledger.share_receivables:
                    if type(quantity) is not Decimal or not quantity.is_finite() or quantity < 0:
                        raise _blocked()
                    quantities[code] = quantities.get(code, Decimal("0")) + quantity
            active = {code: quantity for code, quantity in quantities.items() if quantity > 0}
            if len(active) > _MAX_POSITIONS:
                raise _blocked()
            if active:
                runtime = read_owner_corporate_action_workflow_runtime(
                    environment=environment, as_of=timezone.now()
                )
                reader = build_corporate_action_nav_raw_mark_reader(
                    runtime_environment=environment,
                    calendar_dataset_key=runtime.calendar_dataset_key,
                    using=using,
                )
                identities = build_current_reference_classification_reader(
                    runtime_environment=environment
                )
                for code in sorted(active):
                    classification = identities.resolve_simulated_instrument_classification(
                        security_id=code, asset_code=code, as_of=timezone.now()
                    )
                    if classification is None:
                        raise _blocked()
                    asset_type = classification.simulated_asset_type
                    if code in types and types[code] != asset_type:
                        raise _blocked()
                    query = SimulatedCorporateActionNavRawMarkQuery(
                        account.pk, canonical_account_id, owner_user_id, code, code, asset_type
                    )
                    proof = reader.read_current_mark(query)
                    if type(proof) is not SimulatedCorporateActionNavRawMarkProof:
                        raise _blocked()
                    proof.verify_for(query, as_of=timezone.now())
                    floor = mark_floors.get(code)
                    if floor is not None and proof.trade_date < floor:
                        raise _blocked()
                    marks.append(proof)
                for original in marks:
                    current = reader.read_current_mark(original.query)
                    if type(
                        current
                    ) is not SimulatedCorporateActionNavRawMarkProof or _mark_selection(
                        current, original=original
                    ) != _mark_selection(
                        original, original=original
                    ):
                        raise _blocked()
            total = Decimal("0")
            with localcontext() as context:
                context.prec = 96
                for mark in marks:
                    total += active[mark.query.asset_code] * mark.price
            marked_assets = _exact_amount(total, quantum=quantum)
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            TypeError,
            ValueError,
        ):
            marked_assets = None
            marks = []
    if complete and coverage is not None:
        try:
            coverage_reader.assert_still_current(coverage, using=using)
        except (
            AgomTradeProException,
            ArithmeticError,
            AttributeError,
            OSError,
            TypeError,
            ValueError,
        ):
            complete = False
            debt = None
    checked = timezone.now()
    if complete and coverage is not None:
        try:
            coverage.verify_for(coverage.query, as_of=checked)
        except AgomTradeProException:
            complete = False
            debt = None
    if not complete:
        marked_assets = None
        marks = []
    try:
        for mark in marks:
            mark.verify_for(mark.query, as_of=checked)
    except (ArithmeticError, AttributeError, TypeError, ValueError):
        marked_assets = None
        marks = []
    balance = CorporateActionTaxBalance(
        currency=SimulatedDividendTaxCurrency.CNY,
        currency_quantum=quantum,
        book_cash=cash,
        marked_assets=marked_assets,
        dividend_receivable=(
            ledger.dividend_receivable if complete and cash_rights_complete else None
        ),
        tax_payable=debt,
        order_cash_reserved=holds,
        source_complete=complete,
        declared_blockers=(),
    )
    return OwnerCorporateActionBalanceReadback(
        balance, coverage, tuple(marks), checked, entitlements if complete else None
    )
