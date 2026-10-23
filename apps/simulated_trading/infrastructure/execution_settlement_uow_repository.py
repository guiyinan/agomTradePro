"""Same-database implementation of the settlement-bound simulated ledger UoW."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TypeAlias

from django.db import transaction

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_trading_constraints import ExecutionDenyCode
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeIdempotencyConflict,
    _validate_plan_bundle_binding,
)
from apps.simulated_trading.domain.execution_current_reference import (
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import SimulatedFeePolicyV2
from apps.simulated_trading.domain.execution_settlement_identity import (
    PendingSettlementScopeV1,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SettlementExecutionPlan,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    _execution_quantity_deny_code,
    validate_ledger_money,
    validate_ledger_quantity,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

from .execution_settlement_accounting_math import (
    _allocate_sale_cost_basis,
    _average_cost,
    _money_difference,
    _money_sum,
    _multiply_money,
    _net_sell_proceeds,
    _percentage,
    _position_available_after_holds,
    _quantity_difference,
    _rebased_account_market_value,
    _require_known_simulated_cash,
    _require_unreserved_sell_quantity,
    _signed_money,
    _spendable_cash_after_holds,
)
from .execution_settlement_plan_binding_repository import (
    build_settlement_plan_binding_for_execution as _build_settlement_plan_binding_for_execution,
)
from .execution_settlement_plan_binding_repository import (
    build_simulated_trade_execution_receipt as _build_simulated_trade_execution_receipt,
)
from .execution_settlement_position_validation import (
    validate_execution_position as _validate_execution_position,
)
from .execution_settlement_uow_clock import _aware_time
from .order_reservation_fill_account_history import (
    validate_account_v4_fill_history,
)
from .order_reservation_fill_release_codec import (
    EncodedOrderFillSettlementReleaseProof,
)
from .order_reservation_fill_release_storage import (
    _get_pending_settlement_scope as _get_pending_settlement_scope_from_storage,
)
from .order_reservation_fill_release_storage import (
    _locked_pending_rows as _locked_pending_rows_from_storage,
)
from .order_reservation_fill_release_storage import (
    _pending_candidates as _pending_candidates_from_storage,
)
from .order_reservation_fill_release_storage import (
    _pending_scope_for_rows as _pending_scope_for_rows_from_storage,
)
from .order_reservation_fill_release_storage import (
    _release_pending_rows as _release_pending_rows_from_storage,
)
from .order_reservation_fill_release_storage import (
    _set_release_evidence as _set_release_evidence_from_storage,
)
from .order_reservation_fill_release_storage import (
    encode_due_v4_release_proofs,
    lock_v4_pending_fill_chains,
    require_v4_pending_chain_match,
)
from .order_reservation_guard import (
    active_order_reservation_holds,
    lock_active_order_reservations,
    lock_legacy_execution_order_resources,
)
from .trade_fee_storage_guard import require_trade_fee_storage_range

SettlementPlan: TypeAlias = (
    SettlementExecutionPlan | SettlementExecutionPlanV2 | SettlementExecutionPlanV3
)


class DjangoSimulatedTradeExecutionRepository:
    """Apply simulated settlement, cash, position, fee, and trade changes atomically.

    This repository only handles new normal simulated orders. Existing trade
    imports and corrected actual-fill facts continue to use their own fee-neutral
    paths and leave all UoW metadata NULL.
    """

    def __init__(self, *, using: str) -> None:
        """Bind the complete ledger operation to one explicit Django database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using
        self._fee_policy_repository = DjangoFeePolicyV2Repository(using=using)

    def _validate_rule_quantity(
        self,
        *,
        intent: SimulatedTradeIntent,
        bundle: ExecutionSettlementBundleV3,
        locked_position: tuple[Decimal, Decimal] | None = None,
    ) -> None:
        """Enforce one V3 quantity rule, using locked balance only for SELL exceptions."""

        rule = bundle.execution_submission_v2.execution_rule_v1
        quantity_rule = (
            rule.buy_quantity if intent.side is SimulatedTradeSide.BUY else rule.sell_quantity
        )
        deny_code = _execution_quantity_deny_code(
            side=intent.side,
            quantity=intent.quantity,
            minimum=quantity_rule.minimum,
            step=quantity_rule.step,
            maximum=quantity_rule.maximum,
            sell_odd_lot_mode=rule.sell_odd_lot_mode.value,
            locked_position=locked_position,
        )
        if deny_code is not None:
            raise SimulatedTradeExecutionBlocked(
                "trade quantity violates the exact Risk V3 quantity rule",
                code=deny_code,
            )

    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> SimulatedFeePolicyV2 | None:
        """Read a strict V2 exact-case policy for the exact account and cutoff."""

        return self._fee_policy_repository.get_execution_fee_policy(
            account_id=account_id,
            user_id=user_id,
            asset_type=asset_type,
            market=market,
            board=board,
            side=side,
            as_of=as_of,
        )

    def find_idempotent_result(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> SimulatedTradeExecutionReceipt | None:
        """Read an exact owner/account-scoped result without touching ledger rows."""

        model = (
            SimulatedTradeModel._default_manager.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                account__user_id=user_id,
                idempotency_key=idempotency_key,
            )
            .first()
        )
        return self._receipt(model) if model is not None else None

    def get_pending_settlement_start(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> date | None:
        """Read and validate the earliest original session before external IO."""

        scope = self.get_pending_settlement_scope(
            account_id=account_id,
            user_id=user_id,
            asset_code=asset_code,
        )
        return scope.earliest_session if scope is not None else None

    def get_pending_settlement_scope(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> PendingSettlementScopeV1 | None:
        """Return the validated earliest session and original source exchange."""
        return _get_pending_settlement_scope_from_storage(
            using=self._using,
            account_id=account_id,
            user_id=user_id,
            asset_code=asset_code,
        )

    def execute_trade(
        self,
        *,
        plan: SettlementPlan,
        execution_bundle: ExecutionSettlementBundleV3,
        clock: SimulatedTradeExecutionClock,
    ) -> SimulatedTradeExecutionReceipt:
        """Lock an owned simulated account and ledger rows, then commit one UoW."""

        if type(plan) not in (
            SettlementExecutionPlan,
            SettlementExecutionPlanV2,
            SettlementExecutionPlanV3,
        ):
            raise SimulatedTradeExecutionBlocked(
                "repository requires an exact V1, V2, or V3 settlement plan"
            )
        fee_policy_value: object = plan.fee_policy_v2
        if type(fee_policy_value) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked(
                "repository requires an exact V2 fee snapshot before ledger writes"
            )
        fee_policy = fee_policy_value
        try:
            plan.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("settlement plan failed revalidation") from error
        intent = plan.intent
        try:
            with transaction.atomic(using=self._using):
                account = self._locked_account(
                    account_id=intent.account_id,
                    user_id=intent.user_id,
                    require_active=True,
                )
                existing = (
                    SimulatedTradeModel._default_manager.using(self._using)
                    .filter(
                        account_id=intent.account_id,
                        idempotency_key=intent.idempotency_key,
                    )
                    .first()
                )
                if existing is not None:
                    if existing.request_payload_hash != intent.request_payload_hash:
                        raise SimulatedTradeIdempotencyConflict(
                            "idempotency key already belongs to another exact request"
                        )
                    return self._receipt(existing, replayed=True)

                _require_known_simulated_cash(
                    cash_known=account.cash_known,
                    reconciliation_status=account.cash_reconciliation_status,
                )

                active_cash_held, active_shares_held = lock_legacy_execution_order_resources(
                    account_id=intent.account_id,
                    owner_user_id=intent.user_id,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                    idempotency_key=intent.idempotency_key,
                    using=self._using,
                )
                validate_account_v4_fill_history(
                    account=account,
                    intent=intent,
                    using=self._using,
                )
                _validate_plan_bundle_binding(
                    plan=plan,
                    bundle=execution_bundle,
                    as_of=plan.pre_read_at,
                )
                self._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                )
                pending_candidates = self._pending_candidates(
                    intent.account_id,
                    intent.asset_code,
                )
                v4_chains = lock_v4_pending_fill_chains(
                    account=account,
                    asset_code=intent.asset_code,
                    pending_candidates=pending_candidates,
                    using=self._using,
                )
                position = self._locked_position(intent.account_id, intent.asset_code)
                pending_rows = self._locked_pending(intent.account_id, intent.asset_code)
                require_v4_pending_chain_match(pending_rows=pending_rows, entries=v4_chains)
                pending_scope = self._pending_scope_for_rows(pending_rows)
                now = self._now(clock)
                try:
                    _validate_plan_bundle_binding(
                        plan=plan,
                        bundle=execution_bundle,
                        as_of=now,
                    )
                    current_session = plan.calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        if type(plan) is SettlementExecutionPlanV2:
                            plan_exchange = plan.identity_evidence.source_exchange
                        elif type(plan) is SettlementExecutionPlanV3:
                            plan_exchange = plan.identity_evidence.source_exchange
                        else:
                            plan_exchange = plan.intent.market
                        if pending_scope.source_exchange != plan_exchange:
                            raise ValueError(
                                "pending source exchange differs from the execution plan"
                            )
                        plan.calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "settlement evidence expired or changed before row locks were acquired"
                    ) from error
                position, _ = self._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    active_held_shares=active_shares_held,
                    evidence=plan.calendar_evidence,
                    through_session=current_session,
                    released_at=now,
                    v4_release_proofs=encode_due_v4_release_proofs(
                        entries=v4_chains,
                        evidence=plan.calendar_evidence,
                        released_at=now,
                        release_session=current_session,
                    ),
                )
                locked_position: tuple[Decimal, Decimal] | None = None
                if position is not None:
                    self._validate_position(position)
                    locked_position = _position_available_after_holds(
                        total_quantity=position.quantity,
                        available_quantity=position.available_quantity,
                        held_shares=active_shares_held,
                    )
                elif active_shares_held > 0:
                    raise SimulatedTradeExecutionBlocked(
                        "active sell reservation has no locked position",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                if intent.side is SimulatedTradeSide.SELL:
                    _require_unreserved_sell_quantity(
                        quantity=intent.quantity,
                        locked_position=locked_position,
                        held_shares=active_shares_held,
                    )
                self._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                    locked_position=locked_position,
                )
                return self._apply_trade(
                    account=account,
                    position=position,
                    plan=plan,
                    fee_policy=fee_policy,
                    execution_time=now,
                    active_cash_held=active_cash_held,
                )
        except (SimulatedTradeExecutionBlocked, SimulatedTradeIdempotencyConflict):
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "simulated trade ledger calculation failed exact validation"
            ) from error

    def release_due_settlements(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
        calendar_evidence: ExecutionCalendarEvidence,
        clock: SimulatedTradeExecutionClock,
    ) -> int:
        """Release due rows only after re-counting original lags on current calendar facts."""

        if type(calendar_evidence) is not ExecutionCalendarEvidence:
            raise SimulatedTradeExecutionBlocked("release requires exact calendar evidence")
        try:
            with transaction.atomic(using=self._using):
                account = self._locked_account(
                    account_id=account_id,
                    user_id=user_id,
                    require_active=False,
                )
                active_rows = lock_active_order_reservations(
                    account_id=account_id,
                    using=self._using,
                )
                pending_candidates = self._pending_candidates(account_id, asset_code)
                v4_chains = lock_v4_pending_fill_chains(
                    account=account,
                    asset_code=asset_code,
                    pending_candidates=pending_candidates,
                    using=self._using,
                )
                position = self._locked_position(account_id, asset_code)
                pending_rows = self._locked_pending(account_id, asset_code)
                require_v4_pending_chain_match(pending_rows=pending_rows, entries=v4_chains)
                pending_scope = self._pending_scope_for_rows(pending_rows)
                active_shares_held = Decimal("0.000000")
                if pending_rows:
                    if type(account.user_id) is not int:
                        raise SimulatedTradeAccountScopeUnavailable()
                    security_ids: set[str] = set()
                    for row in pending_rows:
                        security_id = row.settlement_security_id
                        if type(security_id) is not str or not security_id:
                            raise SimulatedTradeExecutionBlocked(
                                "pending settlement security identity is unavailable",
                                code="PENDING_SETTLEMENT_INVALID",
                            )
                        security_ids.add(security_id)
                    if len(security_ids) != 1:
                        raise SimulatedTradeExecutionBlocked(
                            "pending settlements contain multiple security identities",
                            code="PENDING_SETTLEMENT_INVALID",
                        )
                    _, active_shares_held = active_order_reservation_holds(
                        active_rows,
                        account_id=account_id,
                        owner_user_id=account.user_id,
                        security_id=next(iter(security_ids)),
                        asset_code=asset_code,
                    )
                now = self._now(clock)
                try:
                    calendar_evidence.validate_for(now)
                    current_session = calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        if pending_scope.source_exchange != calendar_evidence.snapshot.exchange:
                            raise ValueError(
                                "calendar exchange differs from the original pending source"
                            )
                        calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "published calendar does not cover the complete release interval"
                    ) from error
                _, released = self._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    active_held_shares=active_shares_held,
                    evidence=calendar_evidence,
                    through_session=current_session,
                    released_at=now,
                    v4_release_proofs=encode_due_v4_release_proofs(
                        entries=v4_chains,
                        evidence=calendar_evidence,
                        released_at=now,
                        release_session=current_session,
                    ),
                )
                return released
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "settlement release failed exact ledger validation"
            ) from error

    def _locked_account(
        self,
        *,
        account_id: int,
        user_id: int | None,
        require_active: bool = True,
    ) -> SimulatedAccountModel:
        """Acquire the first lock and enforce simulated-account ownership."""

        query = SimulatedAccountModel._default_manager.using(self._using).select_for_update()
        filters: dict[str, object] = {
            "pk": account_id,
            "account_type": "simulated",
        }
        if user_id is not None:
            filters["user_id"] = user_id
        if require_active:
            filters["is_active"] = True
        account = query.filter(**filters).first()
        if account is None:
            raise SimulatedTradeAccountScopeUnavailable()
        return account

    def _locked_position(self, account_id: int, asset_code: str) -> PositionModel | None:
        """Acquire the second lock for the account/security aggregate."""

        row = (
            PositionModel._default_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account_id, asset_code=asset_code)
            .first()
        )
        return row

    def _locked_pending(self, account_id: int, asset_code: str) -> list[SimulatedTradeModel]:
        """Acquire third-order pending-fill locks in deterministic date/PK order."""
        return _locked_pending_rows_from_storage(
            using=self._using, account_id=account_id, asset_code=asset_code
        )

    def _pending_candidates(
        self,
        account_id: int,
        asset_code: str,
    ) -> list[SimulatedTradeModel]:
        """Read account/security pending BUY locators before locking their fill chains."""
        return _pending_candidates_from_storage(
            using=self._using, account_id=account_id, asset_code=asset_code
        )

    def _pending_scope_for_rows(
        self,
        rows: list[SimulatedTradeModel],
    ) -> PendingSettlementScopeV1 | None:
        """Validate every pending receipt and derive one unambiguous source scope."""
        return _pending_scope_for_rows_from_storage(rows)

    def _now(self, clock: SimulatedTradeExecutionClock) -> datetime:
        """Read and validate the fresh clock only after all row locks are held."""

        return _aware_time(clock.now())

    def _release_pending_rows(
        self,
        *,
        position: PositionModel | None,
        pending_rows: list[SimulatedTradeModel],
        active_held_shares: Decimal,
        evidence: ExecutionCalendarEvidence,
        through_session: date,
        released_at: datetime,
        v4_release_proofs: Mapping[int, EncodedOrderFillSettlementReleaseProof],
    ) -> tuple[PositionModel | None, int]:
        """Release eligible rows under the locked account/security aggregate."""
        return _release_pending_rows_from_storage(
            using=self._using,
            position=position,
            pending_rows=pending_rows,
            active_held_shares=active_held_shares,
            evidence=evidence,
            through_session=through_session,
            released_at=released_at,
            v4_release_proofs=v4_release_proofs,
        )

    def _set_release_evidence(
        self,
        row: SimulatedTradeModel,
        evidence: ExecutionCalendarEvidence,
    ) -> None:
        """Save the actual release proof separately from the buy-time forecast."""
        _set_release_evidence_from_storage(row=row, evidence=evidence)

    def _apply_trade(
        self,
        *,
        account: SimulatedAccountModel,
        position: PositionModel | None,
        plan: SettlementPlan,
        fee_policy: SimulatedFeePolicyV2,
        execution_time: datetime,
        active_cash_held: Decimal,
    ) -> SimulatedTradeExecutionReceipt:
        """Apply one buy or sell with the locked ledger values and exact fee snapshot."""

        intent = plan.intent
        try:
            (
                plan_binding,
                binding_version,
                settlement_exchange,
            ) = _build_settlement_plan_binding_for_execution(
                plan,
                executed_at=execution_time,
            )
            plan_binding_payload = plan_binding.to_payload()
            plan_binding_hash = plan_binding.content_hash
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "settlement execution plan could not be sealed for persistence"
            ) from error
        if (
            type(account.current_cash) is not Decimal
            or type(account.current_market_value) is not Decimal
        ):
            raise SimulatedTradeExecutionBlocked("account money fields are not exact Decimals")
        cash = validate_ledger_money(account.current_cash, "account.current_cash")
        active_cash_held = validate_ledger_money(
            active_cash_held,
            "active_order_held_cash",
            allow_zero=True,
        )
        spendable_cash = _spendable_cash_after_holds(cash, active_cash_held)
        market_value = validate_ledger_money(
            account.current_market_value,
            "account.current_market_value",
        )
        amount = plan.amount
        fees = fee_policy.calculate_for(
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            side=intent.side,
            amount=amount,
            as_of=execution_time,
        )
        require_trade_fee_storage_range(fees)
        total_fees = fees.total_fee
        next_position: PositionModel | None = position
        if intent.side is SimulatedTradeSide.BUY:
            total_cost = _money_sum(amount, total_fees)
            if spendable_cash < total_cost:
                raise SimulatedTradeExecutionBlocked(
                    "unreserved account cash is insufficient for this buy"
                )
            next_cash = _money_difference(
                cash,
                total_cost,
                "account.current_cash_after_buy",
            )
            old_position_value = (
                validate_ledger_money(position.market_value, "position.market_value")
                if position is not None
                else Decimal("0.00")
            )
            next_position = self._apply_buy_position(
                position=position,
                intent=plan.intent,
                total_cost=total_cost,
                market_session=plan.market_session,
                released_immediately=plan.settlement_lag_sessions == 0,
            )
            next_market_value = _rebased_account_market_value(
                market_value,
                old_position_value,
                validate_ledger_money(
                    next_position.market_value, "position.market_value_after_buy"
                ),
            )
            realized_pnl = None
            realized_pnl_pct = None
            settlement_status = "released" if plan.settlement_lag_sessions == 0 else "pending"
        else:
            if position is None:
                raise SimulatedTradeExecutionBlocked("sell requires an existing position")
            total_cost = total_fees
            net_proceeds = _net_sell_proceeds(amount, total_fees)
            if net_proceeds < 0 and spendable_cash < net_proceeds.copy_abs():
                raise SimulatedTradeExecutionBlocked(
                    "unreserved account cash cannot cover the net sell fee debit"
                )
            next_cash = _money_sum(cash, net_proceeds)
            if next_cash < active_cash_held:
                raise SimulatedTradeExecutionBlocked(
                    "sell fees would consume cash reserved by another order"
                )
            old_position_value = validate_ledger_money(
                position.market_value,
                "position.market_value_before_sell",
            )
            next_position, realized_pnl, realized_pnl_pct = self._apply_sell_position(
                position=position,
                intent=plan.intent,
                amount=amount,
                total_cost=total_cost,
                market_session=plan.market_session,
            )
            new_position_value = (
                validate_ledger_money(
                    next_position.market_value,
                    "position.market_value_after_sell",
                )
                if next_position is not None
                else Decimal("0.00")
            )
            next_market_value = _rebased_account_market_value(
                market_value,
                old_position_value,
                new_position_value,
            )
            settlement_status = None

        account.current_cash = next_cash
        account.current_market_value = next_market_value
        account.total_value = _money_sum(next_cash, next_market_value)
        account.total_trades += 1
        if realized_pnl is not None and realized_pnl > 0:
            account.winning_trades += 1
        account.last_trade_date = plan.market_session
        account.save(
            using=self._using,
            update_fields=[
                "current_cash",
                "current_market_value",
                "total_value",
                "total_trades",
                "winning_trades",
                "last_trade_date",
                "updated_at",
            ],
        )

        evidence = plan.calendar_evidence
        publication = evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked("trade calendar binding is missing")
        fee_schedule = fee_policy.fee_schedule_v1
        fee_payload = fee_policy.to_payload()
        immediate_release = (
            intent.side is SimulatedTradeSide.BUY and plan.settlement_lag_sessions == 0
        )
        trade = SimulatedTradeModel._default_manager.using(self._using).create(
            account=account,
            asset_code=intent.asset_code,
            asset_name=intent.asset_name,
            asset_type=intent.asset_type,
            action=intent.side.value,
            quantity=intent.quantity,
            price=intent.price,
            amount=amount,
            commission=fees.commission,
            transfer_fee=fees.transfer_fee,
            stamp_duty=fees.stamp_duty,
            slippage=fees.slippage,
            total_cost=total_cost,
            fee_amounts_known=True,
            cost_basis_known=(
                True
                if intent.side is SimulatedTradeSide.BUY
                else position.cost_basis_known if position is not None else None
            ),
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            reason=intent.reason,
            signal_id=intent.signal_id,
            order_date=plan.market_session,
            execution_date=plan.market_session,
            execution_time=execution_time,
            status="executed",
            idempotency_key=intent.idempotency_key,
            request_payload_hash=intent.request_payload_hash,
            settlement_plan_binding_version=binding_version,
            settlement_plan_binding_payload=plan_binding_payload,
            settlement_plan_binding_hash=plan_binding_hash,
            fee_config_id=fee_schedule.config_id,
            fee_schedule_hash=fee_policy.content_hash,
            fee_schedule_snapshot=fee_payload,
            fee_precision_basis=fee_schedule.precision_basis.value,
            fee_calculation_purpose=fee_schedule.calculation_purpose.value,
            fee_rounding_policy=fee_schedule.rounding_policy.value,
            settlement_status=settlement_status,
            settlement_security_id=intent.security_id,
            settlement_market=intent.market,
            settlement_exchange=settlement_exchange,
            settlement_board=intent.board,
            settlement_market_session=plan.market_session,
            settlement_lag_sessions=plan.settlement_lag_sessions,
            settlement_bundle_id=plan.settlement_bundle_id,
            settlement_bundle_version=plan.settlement_bundle_version,
            settlement_bundle_hash=plan.settlement_bundle_hash,
            settlement_policy_id=plan.settlement_policy_id,
            settlement_policy_version=plan.settlement_policy_version,
            settlement_policy_hash=plan.settlement_policy_hash,
            execution_rule_v2_hash=plan.execution_rule_v2_hash,
            settlement_release_date=plan.settlement_release_date,
            settlement_calendar_snapshot_id=evidence.snapshot.snapshot_id,
            settlement_calendar_content_hash=evidence.snapshot.content_hash,
            settlement_calendar_record_digest=evidence.snapshot.record_digest,
            settlement_calendar_publication_id=publication.publication_id,
            settlement_calendar_publication_hash=publication.publication_hash,
            settlement_calendar_policy_hash=publication.policy_hash,
            settlement_calendar_evidence_hash=evidence.evidence_hash,
            settlement_calendar_timezone=publication.timezone_name,
            settlement_released_at=execution_time if immediate_release else None,
            settlement_release_session=plan.market_session if immediate_release else None,
            settlement_release_calendar_snapshot_id=(
                evidence.snapshot.snapshot_id if immediate_release else None
            ),
            settlement_release_calendar_content_hash=(
                evidence.snapshot.content_hash if immediate_release else None
            ),
            settlement_release_calendar_record_digest=(
                evidence.snapshot.record_digest if immediate_release else None
            ),
            settlement_release_calendar_publication_id=(
                publication.publication_id if immediate_release else None
            ),
            settlement_release_calendar_publication_hash=(
                publication.publication_hash if immediate_release else None
            ),
            settlement_release_calendar_policy_hash=(
                publication.policy_hash if immediate_release else None
            ),
            settlement_release_calendar_evidence_hash=(
                evidence.evidence_hash if immediate_release else None
            ),
            settlement_release_calendar_timezone=(
                publication.timezone_name if immediate_release else None
            ),
        )
        SimulatedTradeModel._default_manager.using(self._using).filter(pk=trade.pk).update(
            execution_time=execution_time
        )
        # Keep the explicit settlement-clock write and its in-memory value aligned.
        # The model now also preserves supplied instants via its current-time default.
        trade.execution_time = execution_time
        return self._receipt(trade)

    def _apply_buy_position(
        self,
        *,
        position: PositionModel | None,
        intent: SimulatedTradeIntent,
        total_cost: Decimal,
        market_session: date,
        released_immediately: bool,
    ) -> PositionModel:
        """Add an exact buy while preserving every preexisting sellable share."""

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionBlocked("buy position requires a typed order intent")
        new_quantity = intent.quantity
        market_value = _multiply_money(new_quantity, intent.price, "position.market_value")
        if position is None:
            avg_cost = _average_cost(total_cost, new_quantity)
            return PositionModel._default_manager.using(self._using).create(
                account_id=intent.account_id,
                asset_code=intent.asset_code,
                asset_name=intent.asset_name,
                asset_type=intent.asset_type,
                quantity=new_quantity,
                available_quantity=(new_quantity if released_immediately else Decimal("0")),
                available_quantity_known=True,
                avg_cost=avg_cost,
                total_cost=total_cost,
                cost_basis_known=True,
                current_price=intent.price,
                market_value=market_value,
                unrealized_pnl=market_value - total_cost,
                unrealized_pnl_pct=_percentage(market_value - total_cost, total_cost),
                first_buy_date=market_session,
                signal_id=intent.signal_id,
                entry_reason=intent.reason,
            )
        self._validate_position(position)
        if position.is_invalidated:
            raise SimulatedTradeExecutionBlocked("invalidated position cannot receive a new buy")
        if position.asset_type != intent.asset_type:
            raise SimulatedTradeExecutionBlocked("position asset type differs from buy intent")
        old_quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        old_available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        old_cost = validate_ledger_money(position.total_cost, "position.total_cost")
        next_quantity = validate_ledger_quantity(
            old_quantity + new_quantity,
            "position.quantity_after_buy",
            allow_zero=False,
        )
        next_cost = _money_sum(old_cost, total_cost)
        next_market_value = _multiply_money(next_quantity, intent.price, "position.market_value")
        next_avg_cost = _average_cost(next_cost, next_quantity)
        next_available = validate_ledger_quantity(
            old_available + (new_quantity if released_immediately else Decimal("0")),
            "position.available_quantity_after_buy",
        )
        if next_available > next_quantity:
            raise SimulatedTradeExecutionBlocked("buy would corrupt sellable quantity")
        position.quantity = next_quantity
        position.available_quantity = next_available
        position.avg_cost = next_avg_cost
        position.total_cost = next_cost
        # A complete new lot does not certify any pre-existing unknown basis.
        position.current_price = intent.price
        position.market_value = next_market_value
        position.unrealized_pnl = next_market_value - next_cost
        position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, next_cost)
        position.last_update_date = market_session
        position.signal_id = intent.signal_id
        position.entry_reason = intent.reason or position.entry_reason
        position.save(
            using=self._using,
            update_fields=[
                "quantity",
                "available_quantity",
                "avg_cost",
                "total_cost",
                "current_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "last_update_date",
                "signal_id",
                "entry_reason",
            ],
        )
        return position

    def _apply_sell_position(
        self,
        *,
        position: PositionModel,
        intent: SimulatedTradeIntent,
        amount: Decimal,
        total_cost: Decimal,
        market_session: date,
    ) -> tuple[PositionModel | None, Decimal | None, float | None]:
        """Sell only explicitly available shares and preserve exact remaining cost basis."""

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionBlocked("sell position requires a typed order intent")
        self._validate_position(position)
        if position.asset_type != intent.asset_type:
            raise SimulatedTradeExecutionBlocked("position asset type differs from sell intent")
        quantity = validate_ledger_quantity(position.quantity, "position.quantity")
        available = validate_ledger_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        if intent.quantity > available:
            raise SimulatedTradeExecutionBlocked(
                "sell quantity exceeds explicitly available shares",
                code=ExecutionDenyCode.SELLABLE_BALANCE_INSUFFICIENT.value,
            )
        if intent.quantity > quantity:
            raise SimulatedTradeExecutionBlocked("sell quantity exceeds total shares")
        stored_cost = validate_ledger_money(
            position.total_cost,
            "position.total_cost",
            allow_zero=False,
        )
        cost_basis = _allocate_sale_cost_basis(
            total_cost=stored_cost,
            sold_quantity=intent.quantity,
            total_quantity=quantity,
        )
        if position.cost_basis_known is True:
            realized_pnl = _signed_money(amount - total_cost - cost_basis, "realized_pnl")
            realized_pct = _percentage(realized_pnl, cost_basis)
        else:
            realized_pnl = None
            realized_pct = None
        remaining = validate_ledger_quantity(
            quantity - intent.quantity,
            "position.quantity_after_sell",
        )
        if remaining == 0:
            position.delete(using=self._using)
            return None, realized_pnl, realized_pct
        remaining_cost = validate_ledger_money(
            stored_cost - cost_basis,
            "position.remaining_cost_basis",
            allow_zero=False,
        )
        remaining_market_value = _multiply_money(
            remaining,
            intent.price,
            "position.market_value_after_sell",
        )
        position.quantity = remaining
        position.available_quantity = validate_ledger_quantity(
            _quantity_difference(
                available,
                intent.quantity,
                "position.available_quantity_after_sell",
            ),
            "position.available_quantity_after_sell",
        )
        position.avg_cost = _average_cost(remaining_cost, remaining)
        position.total_cost = remaining_cost
        position.current_price = intent.price
        position.market_value = remaining_market_value
        position.unrealized_pnl = remaining_market_value - remaining_cost
        position.unrealized_pnl_pct = _percentage(position.unrealized_pnl, remaining_cost)
        position.last_update_date = market_session
        position.save(
            using=self._using,
            update_fields=[
                "quantity",
                "available_quantity",
                "avg_cost",
                "total_cost",
                "current_price",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "last_update_date",
            ],
        )
        return position, realized_pnl, realized_pct

    def _validate_position(self, position: PositionModel) -> None:
        """Reject malformed historic aggregates without rebuilding missing lot history."""

        _validate_execution_position(position)

    def _receipt(
        self,
        row: SimulatedTradeModel | None,
        *,
        replayed: bool = False,
    ) -> SimulatedTradeExecutionReceipt:
        """Delegate to the existing strict persisted-binding receipt reader."""

        return _build_simulated_trade_execution_receipt(row, replayed=replayed)
