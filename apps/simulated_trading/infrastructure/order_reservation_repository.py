"""Persist local simulated-order holds under the shared account ledger lock."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TypeAlias, cast

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
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
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    TradeFeeBreakdown,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
    OrderReservationError,
    OrderReservationRequest,
    OrderReservationResult,
    OrderReservationStatus,
    reserve_order,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    require_no_pending_local_daily_match,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    JSONValue,
    current_order_reservation_book,
    decimal_field,
    decode_order_reservation,
    fee_policy_from_snapshot,
    plan_snapshot_payload,
    snapshot_digest,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_release_storage import (
    encode_due_v4_release_proofs,
    lock_v4_pending_fill_chains,
    require_v4_pending_chain_match,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)

from .execution_settlement_accounting_math import _quantity_difference
from .execution_settlement_uow_repository import DjangoSimulatedTradeExecutionRepository
from .order_reservation_sqlite_precision import PrecisionFamily, require_sqlite_values

ReservationPlan: TypeAlias = SettlementExecutionPlanV2 | SettlementExecutionPlanV3


def _request_from_intent(
    intent: SimulatedTradeIntent,
    *,
    fee_budget: Decimal | None,
) -> OrderReservationRequest:
    """Build the exact cash/share request while preserving the separate full-intent hash."""

    if type(intent) is not SimulatedTradeIntent:
        raise SimulatedTradeExecutionBlocked(
            "order reservation requires an exact simulated trade intent",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        )
    try:
        intent.__post_init__()
        return OrderReservationRequest(
            account_id=intent.account_id,
            security_id=intent.security_id,
            idempotency_key=intent.idempotency_key,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.price,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            fee_budget=fee_budget,
        )
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "order reservation request failed exact validation",
            code="ORDER_RESERVATION_REQUEST_INVALID",
        ) from error


class DjangoSimulatedOrderReservationRepository:
    """Create, replay, inspect, and cancel holds without writing trade rows."""

    def __init__(self, *, using: str) -> None:
        """Bind all reservation writes and reads to one explicit database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise ValueError("using must be a nonempty database alias")
        self._using = using
        self._execution = DjangoSimulatedTradeExecutionRepository(using=using)

    def find_idempotent_reservation(
        self,
        *,
        intent: SimulatedTradeIntent,
        fee_budget: Decimal | None,
    ) -> OrderReservationResult | None:
        """Replay the original hold from stored evidence without source reads."""

        request = _request_from_intent(intent, fee_budget=fee_budget)
        with transaction.atomic(using=self._using):
            account = self._execution._locked_account(
                account_id=intent.account_id,
                user_id=intent.user_id,
                require_active=False,
            )
            active_rows = lock_active_order_reservations(
                account_id=intent.account_id,
                using=self._using,
            )
            row = self._locked_reservation_by_key(
                account_id=intent.account_id,
                idempotency_key=intent.idempotency_key,
            )
            if row is None:
                return None
            self._validate_owner_row(row=row, account=account, user_id=intent.user_id)
            reservation = self._decode_model(row)
            self._require_exact_retry(
                row=row,
                intent=intent,
                request=request,
                reservation=reservation,
            )
            position = self._execution._locked_position(intent.account_id, intent.asset_code)
            book = self._current_book(
                account=account,
                position=position,
                active_rows=active_rows,
                target=row,
                security_id=intent.security_id,
                asset_code=intent.asset_code,
            )
            return OrderReservationResult(book=book, reservation=reservation, replayed=True)

    def reserve_order(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        fee_budget: Decimal | None,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderReservationResult:
        """Recheck evidence under ledger locks, then atomically create one hold."""

        if type(plan) not in (SettlementExecutionPlanV2, SettlementExecutionPlanV3):
            raise SimulatedTradeExecutionBlocked(
                "reservation requires a V2 or V3 settlement plan",
                code="ORDER_RESERVATION_PLAN_INVALID",
            )
        if type(execution_bundle) is not ExecutionSettlementBundleV3:
            raise SimulatedTradeExecutionBlocked(
                "reservation requires an exact Risk V3 bundle",
                code="ORDER_RESERVATION_PLAN_INVALID",
            )
        intent = plan.intent
        request = _request_from_intent(intent, fee_budget=fee_budget)
        self._require_sqlite_values(
            (
                ("quantity", request.quantity, "quantity"),
                ("limit_price", request.limit_price, "price"),
                ("notional", request.notional, "money"),
                ("fee_budget", request.fee_budget, "money"),
            )
        )
        fee_policy = plan.fee_policy_v2
        if type(fee_policy) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked(
                "reservation requires an exact FeeV2 policy",
                code="ORDER_RESERVATION_FEE_POLICY_INVALID",
            )
        try:
            _validate_plan_bundle_binding(
                plan=plan,
                bundle=execution_bundle,
                as_of=plan.pre_read_at,
            )
            self._execution._validate_rule_quantity(
                intent=intent,
                bundle=execution_bundle,
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "reservation plan failed pre-lock validation",
                code="ORDER_RESERVATION_PLAN_INVALID",
            ) from error

        try:
            with transaction.atomic(using=self._using):
                account = self._execution._locked_account(
                    account_id=intent.account_id,
                    user_id=intent.user_id,
                    require_active=True,
                )
                if account.user_id != intent.user_id:
                    raise SimulatedTradeAccountScopeUnavailable()
                active_rows = lock_active_order_reservations(
                    account_id=intent.account_id,
                    using=self._using,
                )
                existing_trade = (
                    SimulatedTradeModel._base_manager.using(self._using)
                    .filter(
                        account_id=intent.account_id,
                        idempotency_key=intent.idempotency_key,
                    )
                    .first()
                )
                if existing_trade is not None:
                    raise SimulatedTradeIdempotencyConflict(
                        "a trade already uses this order idempotency key"
                    )
                existing = self._locked_reservation_by_key(
                    account_id=intent.account_id,
                    idempotency_key=intent.idempotency_key,
                )
                if existing is not None:
                    self._validate_owner_row(
                        row=existing,
                        account=account,
                        user_id=intent.user_id,
                    )
                    reservation = self._decode_model(existing)
                    self._require_exact_retry(
                        row=existing,
                        intent=intent,
                        request=request,
                        reservation=reservation,
                    )
                    position = self._execution._locked_position(
                        intent.account_id,
                        intent.asset_code,
                    )
                    book = self._current_book(
                        account=account,
                        position=position,
                        active_rows=active_rows,
                        target=existing,
                        security_id=intent.security_id,
                        asset_code=intent.asset_code,
                    )
                    return OrderReservationResult(
                        book=book,
                        reservation=reservation,
                        replayed=True,
                    )

                pending_candidates = self._execution._pending_candidates(
                    intent.account_id,
                    intent.asset_code,
                )
                v4_chains = lock_v4_pending_fill_chains(
                    account=account,
                    asset_code=intent.asset_code,
                    pending_candidates=pending_candidates,
                    using=self._using,
                )
                position = self._execution._locked_position(
                    intent.account_id,
                    intent.asset_code,
                )
                pending_rows = self._execution._locked_pending(
                    intent.account_id,
                    intent.asset_code,
                )
                require_v4_pending_chain_match(
                    pending_rows=pending_rows,
                    entries=v4_chains,
                )
                self._require_sqlite_locked_sources(
                    account=account,
                    position=position,
                    pending_rows=pending_rows,
                )
                pre_release_book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=active_rows,
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                )
                pending_scope = self._execution._pending_scope_for_rows(pending_rows)
                now = self._execution._now(clock)
                try:
                    _validate_plan_bundle_binding(
                        plan=plan,
                        bundle=execution_bundle,
                        as_of=now,
                    )
                    fee_policy.validate_at(now)
                    current_session = plan.calendar_evidence.current_open_session(now)
                    if pending_scope is not None:
                        if pending_scope.source_exchange != plan.identity_evidence.source_exchange:
                            raise ValueError(
                                "pending source exchange differs from the execution plan"
                            )
                        plan.calendar_evidence.elapsed_open_sessions(
                            pending_scope.earliest_session,
                            current_session,
                        )
                except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation evidence expired or changed before ledger locks completed",
                        code="ORDER_RESERVATION_PLAN_STALE",
                    ) from error
                position, _ = self._execution._release_pending_rows(
                    position=position,
                    pending_rows=pending_rows,
                    active_held_shares=pre_release_book.active_held_shares,
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
                if position is not None:
                    self._require_sqlite_locked_sources(
                        account=account,
                        position=position,
                        pending_rows=[],
                    )
                    self._execution._validate_position(position)
                book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=active_rows,
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                )
                held_shares = book.active_held_shares
                locked_position: tuple[Decimal, Decimal] | None = None
                if position is not None:
                    available = validate_ledger_quantity(
                        position.available_quantity,
                        "position.available_quantity",
                    )
                    if held_shares > available:
                        raise SimulatedTradeExecutionBlocked(
                            "active sell reservations exceed the locked sellable balance",
                            code="ORDER_RESERVATION_STATE_INVALID",
                        )
                    locked_position = (
                        position.quantity,
                        _quantity_difference(
                            available,
                            held_shares,
                            "sellable_quantity_after_reservations",
                        ),
                    )
                self._execution._validate_rule_quantity(
                    intent=intent,
                    bundle=execution_bundle,
                    locked_position=locked_position,
                )
                fees = fee_policy.calculate_for(
                    asset_type=intent.asset_type,
                    market=intent.market,
                    board=intent.board,
                    side=intent.side,
                    amount=request.notional,
                    as_of=now,
                )
                if type(fees) is not TradeFeeBreakdown:
                    raise SimulatedTradeExecutionBlocked(
                        "FeeV2 returned an unverifiable component breakdown",
                        code="ORDER_RESERVATION_FEE_POLICY_INVALID",
                    )
                snapshot = plan_snapshot_payload(
                    plan=plan,
                    bundle=execution_bundle,
                    fee_policy=fee_policy,
                )
                result = reserve_order(
                    book,
                    request,
                    fee_policy,
                    reserved_at=now,
                )
                if result.replayed:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation key appeared without a locked repository row",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                row = self._create_model(
                    account=account,
                    intent=intent,
                    reservation=result.reservation,
                    fee_policy=fee_policy,
                    fee_breakdown=fees,
                    plan_snapshot=snapshot,
                    book_cash=book.book_cash,
                    sellable_shares=book.sellable_shares,
                    source_snapshot_at=now,
                    plan=plan,
                )
                persisted = self._decode_model(row)
                persisted_book = self._current_book(
                    account=account,
                    position=position,
                    active_rows=[*active_rows, row],
                    target=None,
                    security_id=intent.security_id,
                    asset_code=intent.asset_code,
                )
                return OrderReservationResult(
                    book=persisted_book,
                    reservation=persisted,
                    replayed=False,
                )
        except SimulatedTradeExecutionBlocked:
            raise
        except SimulatedTradeIdempotencyConflict:
            raise
        except IntegrityError as error:
            recovered = self.find_idempotent_reservation(
                intent=intent,
                fee_budget=fee_budget,
            )
            if recovered is not None:
                return recovered
            raise SimulatedTradeExecutionBlocked(
                "reservation could not be committed under its unique account key",
                code="ORDER_RESERVATION_STORAGE_CONFLICT",
            ) from error
        except OrderReservationError as error:
            raise SimulatedTradeExecutionBlocked(
                "订单可用资源或费用预算不满足预留要求",
                code=error.code,
            ) from error
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "reservation failed exact ledger validation",
                code="ORDER_RESERVATION_INVALID",
            ) from error

    def find_order(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> OrderReservation | None:
        """Read one reservation only from its current account-owner scope."""

        self._validate_owner_key(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        row = (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_related("account")
            .filter(
                account_id=account_id,
                owner_user_id=user_id,
                account__user_id=user_id,
                idempotency_key=idempotency_key,
            )
            .first()
        )
        if row is None:
            return None
        return self._decode_model(row)

    def cancel_order(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
        clock: SimulatedTradeExecutionClock,
    ) -> OrderReservation:
        """Release a local hold idempotently, including when its account is inactive."""

        self._validate_owner_key(
            account_id=account_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        try:
            with transaction.atomic(using=self._using):
                account = self._execution._locked_account(
                    account_id=account_id,
                    user_id=user_id,
                    require_active=False,
                )
                actor_active: object = (
                    get_user_model()
                    ._base_manager.using(self._using)
                    .select_for_update()
                    .filter(pk=user_id)
                    .values_list("is_active", flat=True)
                    .first()
                )
                if actor_active is not True:
                    raise SimulatedTradeAccountScopeUnavailable()
                lock_active_order_reservations(
                    account_id=account_id,
                    using=self._using,
                )
                row = self._locked_reservation_by_key(
                    account_id=account_id,
                    idempotency_key=idempotency_key,
                )
                if row is None:
                    raise SimulatedTradeExecutionBlocked(
                        "order reservation was not found in this owner scope",
                        code="ORDER_RESERVATION_NOT_FOUND",
                    )
                self._validate_owner_row(row=row, account=account, user_id=user_id)
                reservation = self._decode_model(row)
                chain = _locked_fill_chain(
                    reservation_row=row,
                    using=self._using,
                )
                require_no_pending_local_daily_match(
                    reservation_row=row,
                    chain=chain,
                    using=self._using,
                )
                if reservation.status is not OrderReservationStatus.ACTIVE:
                    return reservation
                now = self._execution._now(clock)
                if now < reservation.reserved_at:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation cancellation clock precedes its acceptance time",
                        code="CLOCK_INVALID",
                    )
                cancelled = reservation.release_remaining()
                if cancelled.status is not OrderReservationStatus.CANCELLED:
                    raise SimulatedTradeExecutionBlocked(
                        "active reservation did not produce a cancelled hold",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                updated = SimulatedOrderReservationModel.objects.using(self._using)._cancel_locked(
                    account_id=account_id,
                    owner_user_id=user_id,
                    reservation_id=row.pk,
                    filled_quantity=cancelled.filled_quantity,
                    cash_consumed=cancelled.cash_consumed,
                    shares_consumed=cancelled.shares_consumed,
                    cash_released=cancelled.cash_released,
                    shares_released=cancelled.shares_released,
                    cancelled_at=now,
                    updated_at=now,
                )
                if updated != 1:
                    raise SimulatedTradeExecutionBlocked(
                        "reservation changed while its account lock was held",
                        code="ORDER_RESERVATION_STATE_CONFLICT",
                    )
                row.refresh_from_db(using=self._using)
                decoded = self._decode_model(row)
                if decoded != cancelled:
                    raise SimulatedTradeExecutionBlocked(
                        "cancelled reservation differs from its stored resource audit",
                        code="ORDER_RESERVATION_STATE_INVALID",
                    )
                return decoded
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "order reservation cancellation failed exact validation",
                code="ORDER_RESERVATION_INVALID",
            ) from error

    def _locked_reservation_by_key(
        self,
        *,
        account_id: int,
        idempotency_key: str,
    ) -> SimulatedOrderReservationModel | None:
        """Lock a terminal key row after active rows have been locked in order."""

        return (
            SimulatedOrderReservationModel._base_manager.using(self._using)
            .select_for_update()
            .filter(account_id=account_id, idempotency_key=idempotency_key)
            .first()
        )

    def _validate_owner_row(
        self,
        *,
        row: SimulatedOrderReservationModel,
        account: SimulatedAccountModel,
        user_id: int,
    ) -> None:
        """Reject stale ownership or cross-account row association."""

        if (
            row.account_id != account.pk
            or row.owner_user_id != user_id
            or account.user_id != user_id
            or account.account_type != "simulated"
        ):
            raise SimulatedTradeAccountScopeUnavailable()

    def _require_exact_retry(
        self,
        *,
        row: SimulatedOrderReservationModel,
        intent: SimulatedTradeIntent,
        request: OrderReservationRequest,
        reservation: OrderReservation,
    ) -> None:
        """Compare both complete caller intent and fee-bound reservation identity."""

        policy = fee_policy_from_snapshot(validated_plan_snapshot(row))
        expected = request.identity(fee_policy_hash=policy.content_hash)
        if (
            row.intent_payload_hash != intent.request_payload_hash
            or row.reservation_request_hash != expected.request_payload_hash
            or reservation.identity != expected
        ):
            raise SimulatedTradeIdempotencyConflict(
                "order key is already bound to a different exact intent or fee budget"
            )

    def _decode_model(self, row: SimulatedOrderReservationModel) -> OrderReservation:
        """Decode one stored row through the shared strict persistence codec."""

        return decode_order_reservation(row)

    def _decimal_field(self, value: object, field_name: str) -> Decimal:
        """Require an exact finite Decimal from one ledger field."""

        return decimal_field(value, field_name)

    def _current_book(
        self,
        *,
        account: SimulatedAccountModel,
        position: PositionModel | None,
        active_rows: list[SimulatedOrderReservationModel],
        target: SimulatedOrderReservationModel | None,
        security_id: str,
        asset_code: str,
    ) -> OrderReservationBook:
        """Build one exact current book without treating unknown balances as zero."""

        if type(account.user_id) is not int:
            raise SimulatedTradeAccountScopeUnavailable()
        return current_order_reservation_book(
            account=account,
            owner_user_id=account.user_id,
            position=position,
            active_rows=active_rows,
            target=target,
            security_id=security_id,
            asset_code=asset_code,
        )

    def _require_sqlite_values(
        self,
        values: tuple[tuple[str, object, PrecisionFamily], ...],
    ) -> None:
        """Reject new SQLite ledger values outside the supported exact envelope."""

        require_sqlite_values(values=values, using=self._using)

    def _require_sqlite_locked_sources(
        self,
        *,
        account: SimulatedAccountModel,
        position: PositionModel | None,
        pending_rows: list[SimulatedTradeModel],
    ) -> None:
        """Validate known locked balances and pending quantities before their use."""

        values: list[tuple[str, object, PrecisionFamily]] = []
        if account.cash_known is True:
            values.append(("account.current_cash", account.current_cash, "money"))
        if position is not None:
            if position.available_quantity_known is True:
                values.append(
                    ("position.available_quantity", position.available_quantity, "quantity")
                )
            if position.valuation_known is True:
                values.extend(
                    (
                        ("position.quantity", position.quantity, "quantity"),
                        ("position.total_cost", position.total_cost, "money"),
                        ("position.market_value", position.market_value, "money"),
                        ("position.current_price", position.current_price, "price"),
                        ("position.avg_cost", position.avg_cost, "price"),
                    )
                )
        values.extend(("pending_trade.quantity", row.quantity, "quantity") for row in pending_rows)
        self._require_sqlite_values(tuple(values))

    def _create_model(
        self,
        *,
        account: SimulatedAccountModel,
        intent: SimulatedTradeIntent,
        reservation: OrderReservation,
        fee_policy: SimulatedFeePolicyV2,
        fee_breakdown: TradeFeeBreakdown,
        plan_snapshot: dict[str, JSONValue],
        book_cash: Decimal | None,
        sellable_shares: Decimal | None,
        source_snapshot_at: datetime,
        plan: ReservationPlan,
    ) -> SimulatedOrderReservationModel:
        """Persist the prepared order and initial hold with one database write."""

        self._validate_storage_text(intent)
        if (
            type(account.pk) is not int
            or type(account.user_id) is not int
            or account.pk != intent.account_id
            or account.user_id != intent.user_id
        ):
            raise SimulatedTradeAccountScopeUnavailable()
        schedule = fee_policy.fee_schedule_v1
        self._require_sqlite_values(
            (
                ("quantity", reservation.quantity, "quantity"),
                ("limit_price", reservation.limit_price, "price"),
                ("notional", reservation.notional, "money"),
                ("fee_estimate", reservation.fee_estimate, "money"),
                ("fee_budget", reservation.fee_budget, "money"),
                ("commission_estimate", fee_breakdown.commission, "money"),
                ("transfer_fee_estimate", fee_breakdown.transfer_fee, "money"),
                ("stamp_duty_estimate", fee_breakdown.stamp_duty, "money"),
                ("slippage_estimate", fee_breakdown.slippage, "money"),
                ("cash_reserved", reservation.cash_reserved, "money"),
                ("shares_reserved", reservation.shares_reserved, "quantity"),
                ("filled_quantity", reservation.filled_quantity, "quantity"),
                ("cash_consumed", reservation.cash_consumed, "money"),
                ("shares_consumed", reservation.shares_consumed, "quantity"),
                ("cash_released", reservation.cash_released, "money"),
                ("shares_released", reservation.shares_released, "quantity"),
                ("source_book_cash", book_cash, "money"),
                ("source_sellable_quantity", sellable_shares, "quantity"),
            )
        )
        row = SimulatedOrderReservationModel(
            account=account,
            owner_user_id=intent.user_id,
            idempotency_key=intent.idempotency_key,
            intent_payload_hash=intent.request_payload_hash,
            reservation_request_hash=reservation.identity.request_payload_hash,
            security_id=intent.security_id,
            asset_code=intent.asset_code,
            asset_name=intent.asset_name,
            side=reservation.side.value,
            asset_type=intent.asset_type,
            market=intent.market,
            board=intent.board,
            quantity=reservation.quantity,
            limit_price=reservation.limit_price,
            notional=reservation.notional,
            fee_estimate=reservation.fee_estimate,
            fee_budget=reservation.fee_budget,
            commission_estimate=fee_breakdown.commission,
            transfer_fee_estimate=fee_breakdown.transfer_fee,
            stamp_duty_estimate=fee_breakdown.stamp_duty,
            slippage_estimate=fee_breakdown.slippage,
            cash_reserved=reservation.cash_reserved,
            shares_reserved=reservation.shares_reserved,
            filled_quantity=reservation.filled_quantity,
            cash_consumed=reservation.cash_consumed,
            shares_consumed=reservation.shares_consumed,
            cash_released=reservation.cash_released,
            shares_released=reservation.shares_released,
            fee_policy_id=fee_policy.policy_id,
            fee_policy_version=fee_policy.policy_version,
            fee_config_id=schedule.config_id,
            fee_policy_hash=fee_policy.content_hash,
            plan_snapshot_version=1,
            plan_snapshot=cast(dict[str, object], plan_snapshot),
            plan_snapshot_hash=snapshot_digest(plan_snapshot),
            source_book_cash=book_cash,
            source_sellable_quantity=sellable_shares,
            source_snapshot_at=source_snapshot_at,
            market_session=plan.market_session,
            settlement_lag_sessions=plan.settlement_lag_sessions,
            settlement_release_date=plan.settlement_release_date,
            reserved_at=reservation.reserved_at,
            status=reservation.status.value,
            cancelled_at=None,
        )
        row.save(using=self._using, force_insert=True)
        if type(row.pk) is not int or row.pk <= 0:
            raise SimulatedTradeExecutionBlocked(
                "database did not return the new reservation identity",
                code="ORDER_RESERVATION_STORAGE_UNKNOWN",
            )
        row.refresh_from_db(using=self._using)
        return row

    def _validate_storage_text(self, intent: SimulatedTradeIntent) -> None:
        """Reject valid domain tokens that exceed the persisted identity columns."""

        if (
            len(intent.security_id) > 64
            or len(intent.asset_code) > 20
            or len(intent.asset_name) > 100
            or len(intent.asset_type) > 20
            or len(intent.market) > 20
            or len(intent.board) > 20
        ):
            raise SimulatedTradeExecutionBlocked(
                "simulated order identity exceeds reservation storage dimensions",
                code="ORDER_RESERVATION_REQUEST_INVALID",
            )

    def _validate_owner_key(
        self,
        *,
        account_id: int,
        user_id: int,
        idempotency_key: str,
    ) -> None:
        """Reject malformed owner scope before a database lookup."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
            or type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key) > 128
            or idempotency_key.strip() != idempotency_key
            or any(character.isspace() for character in idempotency_key)
        ):
            raise SimulatedTradeExecutionBlocked(
                "order reservation owner or key is invalid",
                code="ORDER_RESERVATION_REQUEST_INVALID",
            )


__all__: tuple[str, ...] = ("DjangoSimulatedOrderReservationRepository",)
