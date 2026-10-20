"""Atomic local partial-fill persistence for the simulated order ledger.

The repository is deliberately not bound by composition. A caller must inject
the same durable local event reader used to observe a fill; this adapter only
re-reads and compares that event under the simulated-account lock. It does not
qualify an event source, create a quote, or treat a fill price as a current mark.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal, localcontext

from django.core.exceptions import ObjectDoesNotExist
from django.db import DEFAULT_DB_ALIAS, DatabaseError, models, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ExistingOrderFill,
    FillRequestDisposition,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventReader,
    LocalSimulatedFillEventV1,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
    _require_aware,
    _require_hash,
    _require_token,
    validate_ledger_money,
    validate_ledger_price,
    validate_ledger_quantity,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationError,
    OrderReservationStatus,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.execution_settlement_accounting_math import (
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
    _require_unreserved_sell_quantity,
    _signed_money,
    _spendable_cash_after_holds,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_binding_codec import (
    encode_order_reservation_fill_binding,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _blocked,
    _create_receipt,
    _create_trade,
    _existing_result,
    _locked_fill_chain,
    _LockedFillChain,
    _resource_cash_consumed,
    _trade_settlement_bindings,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_ledger_storage import (
    _account_positions_snapshot,
    _active_hold_totals,
    _locked_pending_buys,
    _moneyless_quantity_sum,
    _pending_release_plan,
    _persist_pending_releases,
    _quantity_sum,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_request_reader import (
    DjangoSimulatedOrderFillRequestReader,
    _validate_locator,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_snapshot_codec import (
    encode_order_reservation_fill_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
    lock_order_reservation_key,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_sqlite_precision import (
    PrecisionValue,
    require_sqlite_values,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

_logger = logging.getLogger(__name__)
_ZERO_CASH = Decimal("0.00")
_ZERO_SHARES = Decimal("0.000000")


def _aware_now(clock: SimulatedTradeExecutionClock) -> datetime:
    """Read one fresh aware clock only after all ledger rows are locked."""

    value = clock.now()
    if type(value) is not datetime:
        raise _blocked("SIMULATED_FILL_CLOCK_INVALID", "成交记账时钟必须为明确的 aware datetime")
    try:
        _require_aware(value, "fill_writer_now")
    except (ArithmeticError, TypeError, ValueError) as error:
        raise _blocked(
            "SIMULATED_FILL_CLOCK_INVALID", "成交记账时钟必须为明确的 aware datetime"
        ) from error
    return value


def _validate_locator_event(event: object) -> LocalSimulatedFillEventV1:
    """Check only the stable event locator needed before receipt replay lookup."""

    if type(event) is not LocalSimulatedFillEventV1:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件必须为精确类型")
    try:
        if (
            type(event.account_id) is not int
            or event.account_id <= 0
            or type(event.user_id) is not int
            or event.user_id <= 0
            or type(event.reservation_id) is not int
            or event.reservation_id <= 0
        ):
            raise ValueError("fill event owner scope is invalid")
        _require_token(event.order_idempotency_key, "order_idempotency_key", max_length=128)
        _require_token(event.source_namespace, "source_namespace", max_length=128)
        _require_token(event.source_event_id, "source_event_id", max_length=128)
        _require_hash(event.event_payload_hash, "event_payload_hash")
    except (ArithmeticError, SimulatedSettlementContractError, TypeError, ValueError) as error:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件定位字段不可验证") from error
    return event


def _validate_new_event(
    event: LocalSimulatedFillEventV1,
    *,
    using: str,
    reservation_row: SimulatedOrderReservationModel,
    chain: _LockedFillChain,
    proof: OrderFillSettlementProof,
    now: datetime,
    expected_event_payload_hash: str | None,
) -> None:
    """Bind a fresh event, its proof, and every owner/order identity to locks."""

    if event.event_kind is LocalSimulatedFillEventKind.UNKNOWN:
        _logger.warning(
            "Unknown local simulated fill kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked("SIMULATED_FILL_EVENT_KIND_UNKNOWN", "未知成交事件类型已阻止记账")
    if event.event_kind not in (
        LocalSimulatedFillEventKind.FILL,
        LocalSimulatedFillEventKind.FINAL_FILL,
    ):
        _logger.warning(
            "Unsupported local simulated fill kind blocked",
            extra={"code": "SIMULATED_FILL_EVENT_KIND_UNKNOWN"},
        )
        raise _blocked("SIMULATED_FILL_EVENT_KIND_UNKNOWN", "不支持的成交事件类型已阻止记账")
    if type(proof) is not OrderFillSettlementProof:
        raise _blocked("SIMULATED_FILL_CALENDAR_INVALID", "成交日历证明类型不受支持")
    try:
        proof.validate()
        proof.calendar_evidence.validate_for(now)
        if proof.calendar_read_cutoff > now:
            raise ValueError("calendar cutoff is later than the locked writer clock")
        _require_token(event.source_version, "source_version", max_length=128)
        _require_token(event.source_snapshot_id, "source_snapshot_id")
        _require_token(event.security_id, "security_id")
        _require_token(event.asset_code, "asset_code")
        for field_name, digest in (
            ("source_snapshot_hash", event.source_snapshot_hash),
            ("intent_payload_hash", event.intent_payload_hash),
            ("reservation_request_hash", event.reservation_request_hash),
            ("plan_snapshot_hash", event.plan_snapshot_hash),
        ):
            _require_hash(digest, field_name)
        for field_name, value in (
            ("occurred_at", event.occurred_at),
            ("source_observed_at", event.source_observed_at),
            ("source_available_at", event.source_available_at),
            ("recorded_at", event.recorded_at),
        ):
            _require_aware(value, field_name)
        validate_ledger_quantity(event.quantity, "fill_quantity", allow_zero=False)
        validate_ledger_price(event.price, "fill_price", allow_zero=False)
        require_sqlite_values(
            values=(
                ("fill_quantity", event.quantity, "quantity"),
                ("fill_price", event.price, "price"),
            ),
            using=using,
        )
    except (ArithmeticError, SimulatedSettlementContractError, TypeError, ValueError) as error:
        raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "成交事件或日历证据不可验证") from error

    reservation = chain.reservation
    intent = chain.intent
    if (
        event.reservation_id != reservation_row.pk
        or event.account_id != reservation_row.account_id
        or event.user_id != reservation_row.owner_user_id
        or event.order_idempotency_key != reservation_row.idempotency_key
        or event.intent_payload_hash != reservation_row.intent_payload_hash
        or event.reservation_request_hash != reservation_row.reservation_request_hash
        or event.plan_snapshot_hash != reservation_row.plan_snapshot_hash
        or event.security_id != reservation_row.security_id
        or event.asset_code != reservation_row.asset_code
        or event.side is not reservation.side
        or intent.request_payload_hash != reservation_row.intent_payload_hash
        or intent.user_id != reservation_row.owner_user_id
        or intent.account_id != reservation_row.account_id
        or intent.idempotency_key != reservation_row.idempotency_key
        or intent.security_id != reservation_row.security_id
        or intent.asset_code != reservation_row.asset_code
    ):
        raise _blocked("SIMULATED_FILL_SOURCE_SCOPE_MISMATCH", "成交事件与锁定订单封存身份不符")
    if expected_event_payload_hash is not None:
        try:
            _require_hash(expected_event_payload_hash, "expected_event_payload_hash")
        except (ArithmeticError, SimulatedSettlementContractError, TypeError, ValueError) as error:
            raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "调用方成交摘要格式无效") from error
        if event.event_payload_hash != expected_event_payload_hash:
            raise SimulatedTradeIdempotencyConflict("成交事件摘要与调用方已观察摘要不一致")
    settlement_bindings = _trade_settlement_bindings(
        reservation_row=reservation_row,
        intent=intent,
        as_of=now,
    )
    settlement_exchange = settlement_bindings.exchange
    settlement_lag_sessions = settlement_bindings.lag_sessions
    if (
        proof.fill_occurred_at != event.occurred_at
        or proof.settlement_exchange != settlement_exchange
        or proof.settlement_lag_sessions != settlement_lag_sessions
        or proof.calendar_evidence.snapshot.exchange != settlement_exchange
        or proof.fill_occurred_at < reservation.reserved_at
    ):
        raise _blocked("SIMULATED_FILL_CALENDAR_SCOPE_MISMATCH", "成交日历证明与订单封存范围不符")


class DjangoSimulatedOrderFillRepository:
    """Persist one exact locally sourced fill under the account-wide ledger lock."""

    def __init__(
        self,
        *,
        event_reader: LocalSimulatedFillEventReader | None = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Select the database and optional durable local event rereader.

        No reader is installed by this packet's composition. A missing reader
        blocks every new fill but does not prevent replay of an exact receipt.
        """

        if type(using) is not str or not using:
            raise ValueError("database alias must be non-empty text")
        self._using = using
        self._event_reader = event_reader
        self._request_reader = DjangoSimulatedOrderFillRequestReader(using=using)

    def resolve_fill_request(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
    ) -> FillRequestDisposition:
        """Resolve owner scope and validate a persisted replay under the parent lock."""

        _validate_locator(
            account_id=account_id,
            user_id=user_id,
            order_idempotency_key=order_idempotency_key,
            source_namespace=source_namespace,
            fill_event_id=fill_event_id,
        )
        with transaction.atomic(using=self._using):
            account = (
                SimulatedAccountModel._base_manager.using(self._using)
                .select_for_update()
                .filter(pk=account_id, user_id=user_id, account_type="simulated")
                .first()
            )
            if account is None:
                return None

            disposition = self._request_reader.resolve_fill_request(
                account_id=account_id,
                user_id=user_id,
                order_idempotency_key=order_idempotency_key,
                source_namespace=source_namespace,
                fill_event_id=fill_event_id,
            )
            if type(disposition) is not ExistingOrderFill:
                return disposition

            reservation_row = (
                SimulatedOrderReservationModel._base_manager.using(self._using)
                .select_for_update()
                .filter(
                    pk=disposition.result.reservation_id,
                    account_id=account.pk,
                    owner_user_id=user_id,
                    idempotency_key=order_idempotency_key,
                )
                .first()
            )
            if reservation_row is None:
                raise _blocked(
                    "SIMULATED_FILL_RECEIPT_INVALID",
                    "已定位成交回执的订单所有权在锁内发生变化",
                )
            chain = _locked_fill_chain(
                reservation_row=reservation_row,
                using=self._using,
            )
            matching_events = tuple(
                decoded.event
                for receipt, decoded in chain.rows
                if receipt.source_namespace == source_namespace
                and receipt.source_event_id == fill_event_id
            )
            if not matching_events:
                raise _blocked(
                    "SIMULATED_FILL_RECEIPT_INVALID",
                    "已定位成交回执在完整链中不存在",
                )
            chain_result = _existing_result(
                chain=chain,
                event=matching_events[0],
                expected_event_payload_hash=disposition.result.event_payload_hash,
            )
            if chain_result is None:
                raise _blocked(
                    "SIMULATED_FILL_RECEIPT_INVALID",
                    "已定位成交回执在完整链中不存在",
                )
            return ExistingOrderFill(result=chain_result)

    def apply_fill_event(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        expected_event_payload_hash: str | None,
        settlement_proof: OrderFillSettlementProof,
        clock: SimulatedTradeExecutionClock,
    ) -> SimulatedOrderFillResult:
        """Re-read, validate and atomically persist one partial local fill.

        Exact persisted event replay is resolved after the owner/account and
        receipt-chain locks but before current clock, source, terminal, or
        valuation checks. New writes require a known current Position mark and
        a fully reconciled account aggregate; this method never creates a
        Position or derives its current mark from the execution price.
        """

        checked_event = _validate_locator_event(event)
        if expected_event_payload_hash is not None:
            try:
                _require_hash(expected_event_payload_hash, "expected_event_payload_hash")
            except (
                ArithmeticError,
                SimulatedSettlementContractError,
                TypeError,
                ValueError,
            ) as error:
                raise _blocked("SIMULATED_FILL_SOURCE_INVALID", "调用方成交摘要格式无效") from error
        try:
            with transaction.atomic(using=self._using):
                account = self._lock_account(
                    account_id=checked_event.account_id,
                    user_id=checked_event.user_id,
                )
                active_rows = lock_active_order_reservations(
                    account_id=checked_event.account_id,
                    using=self._using,
                )
                reservation_row = lock_order_reservation_key(
                    account_id=checked_event.account_id,
                    idempotency_key=checked_event.order_idempotency_key,
                    using=self._using,
                )
                if reservation_row is None:
                    raise SimulatedTradeAccountScopeUnavailable()
                self._validate_locked_owner(
                    account=account,
                    reservation_row=reservation_row,
                    event=checked_event,
                )
                chain = _locked_fill_chain(
                    reservation_row=reservation_row,
                    using=self._using,
                )
                existing = _existing_result(
                    chain=chain,
                    event=checked_event,
                    expected_event_payload_hash=expected_event_payload_hash,
                )
                if existing is not None:
                    return existing
                if account.is_active is not True:
                    raise SimulatedTradeAccountScopeUnavailable()
                if chain.reservation.status is not OrderReservationStatus.ACTIVE:
                    raise _blocked(
                        "ORDER_RESERVATION_TERMINAL",
                        "终态订单不接受新的成交事件",
                    )

                position_rows = list(
                    PositionModel._base_manager.using(self._using)
                    .select_for_update()
                    .filter(account_id=account.pk)
                    .order_by("pk")
                )
                position, current_cash, account_market_value = _account_positions_snapshot(
                    account=account,
                    positions=position_rows,
                    asset_code=reservation_row.asset_code,
                    using=self._using,
                )
                if position.asset_type != reservation_row.asset_type:
                    raise _blocked("POSITION_IDENTITY_CONFLICT", "持仓资产类别与订单封存信息不符")
                pending_rows = _locked_pending_buys(
                    account_id=account.pk,
                    asset_code=reservation_row.asset_code,
                    using=self._using,
                )
                now = _aware_now(clock)
                current_session, due_pending_rows, available_after_release = _pending_release_plan(
                    pending_rows=pending_rows,
                    position=position,
                    proof=settlement_proof,
                    now=now,
                    security_id=reservation_row.security_id,
                )
                _validate_new_event(
                    checked_event,
                    using=self._using,
                    reservation_row=reservation_row,
                    chain=chain,
                    proof=settlement_proof,
                    now=now,
                    expected_event_payload_hash=expected_event_payload_hash,
                )
                if self._event_reader is None:
                    raise _blocked(
                        "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                        "没有配置可持久回读的本地成交来源，未记账",
                    )
                self._reread_source_event(event=checked_event, now=now)
                hold_totals = _active_hold_totals(
                    active_rows=active_rows,
                    reservation_row=reservation_row,
                    chain=chain,
                    using=self._using,
                )
                result = self._apply_locked_fill(
                    account=account,
                    reservation_row=reservation_row,
                    chain=chain,
                    position=position,
                    pending_rows=pending_rows,
                    due_pending_rows=due_pending_rows,
                    available_after_release=available_after_release,
                    active_cash_held=hold_totals[0],
                    active_shares_held=hold_totals[1],
                    other_cash_held=hold_totals[2],
                    other_shares_held=hold_totals[3],
                    event=checked_event,
                    proof=settlement_proof,
                    now=now,
                    current_session=current_session,
                )
                return result
        except (SimulatedTradeExecutionBlocked, SimulatedTradeIdempotencyConflict):
            raise
        except OrderReservationError as error:
            raise _blocked(
                error.code,
                "成交数量或费用超出封存订单预留资源，未记账",
            ) from error
        except DatabaseError as error:
            return self._resolve_unknown_commit(
                event=checked_event,
                expected_event_payload_hash=expected_event_payload_hash,
                cause=error,
            )
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            TypeError,
            ValueError,
        ) as error:
            raise _blocked(
                "SIMULATED_FILL_LEDGER_INVALID", "模拟成交账本核验失败，未确认写入"
            ) from error

    def _lock_account(self, *, account_id: int, user_id: int) -> SimulatedAccountModel:
        """Lock the owner-scoped simulated account parent before every child row."""

        account = (
            SimulatedAccountModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=account_id, user_id=user_id, account_type="simulated")
            .first()
        )
        if account is None:
            raise SimulatedTradeAccountScopeUnavailable()
        return account

    @staticmethod
    def _validate_locked_owner(
        *,
        account: SimulatedAccountModel,
        reservation_row: SimulatedOrderReservationModel,
        event: LocalSimulatedFillEventV1,
    ) -> None:
        """Reject any account, owner or order-key mismatch before receipt decoding."""

        if (
            account.pk != event.account_id
            or account.user_id != event.user_id
            or account.account_type != "simulated"
            or reservation_row.account_id != event.account_id
            or reservation_row.owner_user_id != event.user_id
            or reservation_row.idempotency_key != event.order_idempotency_key
            or reservation_row.pk != event.reservation_id
        ):
            raise SimulatedTradeAccountScopeUnavailable()

    def _reread_source_event(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        now: datetime,
    ) -> None:
        """Compare the exact durable source row again while the account is locked."""

        reader = self._event_reader
        if reader is None:
            raise _blocked("SIMULATED_FILL_SOURCE_UNAVAILABLE", "成交来源读取器未配置")
        try:
            reread = reader.read_event(
                account_id=event.account_id,
                user_id=event.user_id,
                order_idempotency_key=event.order_idempotency_key,
                source_namespace=event.source_namespace,
                fill_event_id=event.source_event_id,
                as_of=now,
            )
        except DatabaseError as error:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_UNAVAILABLE",
                "本地成交事件在锁内无法重新读取，未记账",
            ) from error
        if type(reread) is not LocalSimulatedFillEventV1 or reread != event:
            raise _blocked(
                "SIMULATED_FILL_SOURCE_CHANGED",
                "本地成交事件与锁前观察结果不一致，未记账",
            )

    def _resolve_unknown_commit(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        expected_event_payload_hash: str | None,
        cause: DatabaseError,
    ) -> SimulatedOrderFillResult:
        """Read back an exact committed receipt after the outer transaction ends."""

        try:
            disposition = self.resolve_fill_request(
                account_id=event.account_id,
                user_id=event.user_id,
                order_idempotency_key=event.order_idempotency_key,
                source_namespace=event.source_namespace,
                fill_event_id=event.source_event_id,
            )
        except (DatabaseError, SimulatedTradeExecutionBlocked):
            raise SimulatedTradeExecutionResultUnknown("成交写入后无法读取精确回执状态") from cause
        if isinstance(disposition, ExistingOrderFill):
            stored = disposition.result
            if stored.event_payload_hash != event.event_payload_hash or (
                expected_event_payload_hash is not None
                and stored.event_payload_hash != expected_event_payload_hash
            ):
                raise SimulatedTradeIdempotencyConflict("未知提交回读到不同成交摘要") from cause
            return stored
        raise SimulatedTradeExecutionResultUnknown("成交提交结果无法从精确回执确认") from cause

    def _apply_locked_fill(
        self,
        *,
        account: SimulatedAccountModel,
        reservation_row: SimulatedOrderReservationModel,
        chain: _LockedFillChain,
        position: PositionModel,
        pending_rows: Sequence[SimulatedTradeModel],
        due_pending_rows: Sequence[SimulatedTradeModel],
        available_after_release: Decimal,
        active_cash_held: Decimal,
        active_shares_held: Decimal,
        other_cash_held: Decimal,
        other_shares_held: Decimal,
        event: LocalSimulatedFillEventV1,
        proof: OrderFillSettlementProof,
        now: datetime,
        current_session: date,
    ) -> SimulatedOrderFillResult:
        """Prepare the exact ledger transition, then persist it inside the caller transaction."""

        request = OrderReservationFillRequest(
            fill_event_id=event.source_event_id,
            intent=chain.intent,
            stored_intent_payload_hash=reservation_row.intent_payload_hash,
            reservation=chain.reservation,
            fee_policy=chain.fee_policy,
            fill_occurred_at=event.occurred_at,
            quantity=event.quantity,
            price=event.price,
            prior=chain.accrual,
            close_order=event.event_kind is LocalSimulatedFillEventKind.FINAL_FILL,
        )
        economics = prepare_order_reservation_fill(request)
        cash_consumed = _resource_cash_consumed(economics=economics)
        reservation_after = chain.reservation.apply_fill(
            filled_quantity=economics.quantity,
            cash_consumed=cash_consumed,
            close_order=economics.close_order,
        )
        current_cash = validate_ledger_money(account.current_cash, "account.current_cash")
        quantity_before = validate_ledger_quantity(position.quantity, "position.quantity")
        available_before = validate_ledger_quantity(
            available_after_release,
            "position.available_quantity_after_release",
            allow_zero=True,
        )
        old_cost = validate_ledger_money(
            position.total_cost, "position.total_cost", allow_zero=True
        )
        old_market_value = validate_ledger_money(position.market_value, "position.market_value")
        old_mark = validate_ledger_price(position.current_price, "position.current_price")
        if position.cost_basis_known is True and old_cost == _ZERO_CASH:
            raise _blocked("POSITION_COST_BASIS_INVALID", "已知持仓成本必须为正数")

        active_cash = validate_ledger_money(
            active_cash_held, "active_order_held_cash", allow_zero=True
        )
        active_shares = validate_ledger_quantity(
            active_shares_held,
            "active_order_held_shares",
            allow_zero=True,
        )
        other_cash = validate_ledger_money(
            other_cash_held, "other_order_held_cash", allow_zero=True
        )
        other_shares = validate_ledger_quantity(
            other_shares_held,
            "other_order_held_shares",
            allow_zero=True,
        )
        own_remaining_cash_before = chain.reservation.remaining_cash
        own_remaining_shares_before = chain.reservation.remaining_shares
        if own_remaining_cash_before > active_cash or own_remaining_shares_before > active_shares:
            raise _blocked("ORDER_RESERVATION_STATE_INVALID", "当前订单预留资源与锁定总额不一致")

        remaining_pending_quantity = _moneyless_quantity_sum(
            tuple(
                validate_ledger_quantity(row.quantity, "pending_buy.quantity")
                for row in pending_rows
                if row not in due_pending_rows
            )
        )
        realized_pnl: Decimal | None = None
        realized_pnl_pct: float | None = None
        if economics.side is SimulatedTradeSide.BUY:
            fill_total_cost = _money_sum(
                economics.gross_amount, economics.incremental_fees.total_fee
            )
            next_cash = _money_difference(
                current_cash, fill_total_cost, "account.cash_after_buy_fill"
            )
            next_quantity = _quantity_sum(quantity_before, economics.quantity)
            next_cost = _money_sum(old_cost, fill_total_cost)
            immediately_released = proof.expected_release_session == proof.fill_market_session
            if immediately_released:
                next_available = _quantity_sum(available_before, economics.quantity)
            else:
                next_available = available_before
            trade_total_cost = fill_total_cost
            trade_settlement_status = "released" if immediately_released else "pending"
            trade_cost_basis_known = position.cost_basis_known
        else:
            next_quantity = _quantity_difference(
                quantity_before,
                economics.quantity,
                "position.quantity_after_sell_fill",
            )
            locked_position = _position_available_after_holds(
                total_quantity=quantity_before,
                available_quantity=available_before,
                held_shares=other_shares,
            )
            _require_unreserved_sell_quantity(
                quantity=economics.quantity,
                locked_position=locked_position,
                held_shares=other_shares,
            )
            next_available = _quantity_difference(
                available_before,
                economics.quantity,
                "position.available_after_sell_fill",
            )
            cost_reduction = _allocate_sale_cost_basis(
                total_cost=old_cost,
                sold_quantity=economics.quantity,
                total_quantity=quantity_before,
            )
            next_cost = _money_difference(old_cost, cost_reduction, "position.cost_after_sell_fill")
            net_proceeds = _net_sell_proceeds(
                economics.gross_amount,
                economics.incremental_fees.total_fee,
            )
            next_cash = _money_sum(current_cash, net_proceeds)
            if position.cost_basis_known is True:
                with localcontext() as context:
                    context.prec = 80
                    pnl_value = (
                        economics.gross_amount
                        - economics.incremental_fees.total_fee
                        - cost_reduction
                    )
                realized_pnl = _signed_money(pnl_value, "fill.realized_pnl")
                realized_pnl_pct = _percentage(realized_pnl, cost_reduction)
            trade_total_cost = economics.incremental_fees.total_fee
            trade_settlement_status = None
            trade_cost_basis_known = position.cost_basis_known

        if next_quantity == _ZERO_SHARES:
            next_market_value = _ZERO_CASH
        else:
            next_market_value = _multiply_money(
                next_quantity,
                old_mark,
                "position.market_value_at_existing_mark",
            )
        account_market_value_before = validate_ledger_money(
            account.current_market_value, "account.current_market_value"
        )
        next_account_market_value = _rebased_account_market_value(
            account_market_value_before,
            old_market_value,
            next_market_value,
        )
        next_total_value = _money_sum(next_cash, next_account_market_value)
        next_cash_hold = _money_sum(other_cash, reservation_after.remaining_cash)
        _spendable_cash_after_holds(next_cash, next_cash_hold)
        next_share_hold = _quantity_sum(other_shares, reservation_after.remaining_shares)
        if next_quantity > _ZERO_SHARES:
            _quantity_difference(
                next_available, next_share_hold, "sellable_after_fill_reservations"
            )
            if _quantity_sum(next_available, remaining_pending_quantity) > next_quantity:
                raise _blocked("PENDING_SETTLEMENT_INVALID", "成交后可卖与待结算数量超过持仓")

        if position.cost_basis_known is True and next_quantity > _ZERO_SHARES:
            next_avg_cost = _average_cost(next_cost, next_quantity)
            next_unrealized_pnl = _signed_money(
                _signed_difference(next_market_value, next_cost),
                "position.unrealized_pnl_after_fill",
            )
            next_unrealized_pnl_pct = _percentage(next_unrealized_pnl, next_cost)
        else:
            # Numeric legacy basis remains as stored, while the nullable flag
            # keeps every derived cost/PnL consumer from treating it as known.
            next_avg_cost = position.avg_cost
            next_unrealized_pnl = position.unrealized_pnl
            next_unrealized_pnl_pct = position.unrealized_pnl_pct

        precision_values: list[PrecisionValue] = [
            ("account.current_cash", current_cash, "money"),
            ("account.current_market_value", account_market_value_before, "money"),
            ("position.quantity_before_fill", quantity_before, "quantity"),
            ("position.available_before_fill", available_before, "quantity"),
            ("position.total_cost_before_fill", old_cost, "money"),
            ("position.market_value_before_fill", old_market_value, "money"),
            ("position.current_price", old_mark, "price"),
            ("fill.quantity", economics.quantity, "quantity"),
            ("fill.price", economics.price, "price"),
            ("fill.gross_amount", economics.gross_amount, "money"),
            ("fill.commission", economics.incremental_fees.commission, "money"),
            ("fill.transfer_fee", economics.incremental_fees.transfer_fee, "money"),
            ("fill.stamp_duty", economics.incremental_fees.stamp_duty, "money"),
            ("fill.slippage", economics.incremental_fees.slippage, "money"),
            ("fill.total_fee", economics.incremental_fees.total_fee, "money"),
            ("reservation.filled_quantity", reservation_after.filled_quantity, "quantity"),
            ("reservation.cash_consumed", cash_consumed, "money"),
            ("reservation.shares_consumed", reservation_after.shares_consumed, "quantity"),
            ("reservation.cash_released", reservation_after.cash_released, "money"),
            ("reservation.shares_released", reservation_after.shares_released, "quantity"),
            ("reservation.remaining_cash_before_fill", own_remaining_cash_before, "money"),
            ("reservation.remaining_shares_before_fill", own_remaining_shares_before, "quantity"),
            ("reservation.remaining_cash", reservation_after.remaining_cash, "money"),
            ("reservation.remaining_shares", reservation_after.remaining_shares, "quantity"),
            ("holds.active_cash", active_cash, "money"),
            ("holds.active_shares", active_shares, "quantity"),
            ("holds.other_cash", other_cash, "money"),
            ("holds.other_shares", other_shares, "quantity"),
            ("pending.remaining_quantity", remaining_pending_quantity, "quantity"),
            ("position.quantity_after_fill", next_quantity, "quantity"),
            ("position.available_after_fill", next_available, "quantity"),
            ("position.total_cost_after_fill", next_cost, "money"),
            ("position.market_value_after_fill", next_market_value, "money"),
            ("account.market_value_after_fill", next_account_market_value, "money"),
            ("account.total_value_after_fill", next_total_value, "money"),
            ("holds.cash_after_fill", next_cash_hold, "money"),
            ("holds.shares_after_fill", next_share_hold, "quantity"),
            ("trade.total_cost", trade_total_cost, "money"),
            ("position.average_cost_after_fill", next_avg_cost, "price"),
            ("position.unrealized_pnl_magnitude", next_unrealized_pnl.copy_abs(), "money"),
        ]
        if realized_pnl is not None:
            precision_values.append(
                ("trade.realized_pnl_magnitude", realized_pnl.copy_abs(), "money")
            )
        require_sqlite_values(values=tuple(precision_values), using=self._using)

        encoded = encode_order_reservation_fill_snapshot(
            event=event,
            economics=economics,
            reservation_id=reservation_row.pk,
            fill_sequence=economics.cumulative_state.fill_count,
            plan_snapshot_hash=reservation_row.plan_snapshot_hash,
        )
        binding = encode_order_reservation_fill_binding(snapshot=encoded, proof=proof)
        trade = _create_trade(
            using=self._using,
            account=account,
            reservation_row=reservation_row,
            chain=chain,
            economics=economics,
            encoded=encoded,
            binding_payload=binding.to_payload(),
            binding_hash=binding.settlement_plan_binding_hash,
            total_cost=trade_total_cost,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            cost_basis_known=trade_cost_basis_known,
            settlement_status=trade_settlement_status,
            proof=proof,
            now=now,
            event=event,
        )
        _create_receipt(
            using=self._using,
            encoded=encoded,
            event=event,
            trade=trade,
            reservation_row=reservation_row,
        )

        if next_quantity == _ZERO_SHARES:
            position.delete(using=self._using)
        else:
            position.quantity = next_quantity
            position.available_quantity = next_available
            position.total_cost = next_cost
            position.market_value = next_market_value
            position.valuation_known = True
            if position.cost_basis_known is True:
                position.avg_cost = next_avg_cost
                position.unrealized_pnl = next_unrealized_pnl
                position.unrealized_pnl_pct = next_unrealized_pnl_pct
            position.save(
                using=self._using,
                update_fields=[
                    "quantity",
                    "available_quantity",
                    "total_cost",
                    "market_value",
                    "valuation_known",
                    "avg_cost",
                    "unrealized_pnl",
                    "unrealized_pnl_pct",
                    "last_update_date",
                ],
            )
        account.current_cash = next_cash
        account.current_market_value = next_account_market_value
        account.total_value = next_total_value
        account.total_trades += 1
        if realized_pnl is not None and realized_pnl > 0:
            account.winning_trades += 1
        if account.last_trade_date is None or proof.fill_market_session > account.last_trade_date:
            account.last_trade_date = proof.fill_market_session
        account.save(
            using=self._using,
            update_fields=[
                "current_cash",
                "current_market_value",
                "total_value",
                "total_trades",
                "winning_trades",
                "last_trade_date",
                "cash_known",
                "cash_reconciliation_status",
            ],
        )
        _persist_pending_releases(
            rows=due_pending_rows,
            proof=proof,
            now=now,
            current_session=current_session,
            using=self._using,
        )
        reservation_query = SimulatedOrderReservationModel._base_manager.using(self._using).filter(
            pk=reservation_row.pk,
            status=SimulatedOrderReservationModel.STATUS_ACTIVE,
        )
        updated = models.QuerySet.update(
            reservation_query,
            status=reservation_after.status.value,
            filled_quantity=reservation_after.filled_quantity,
            cash_consumed=reservation_after.cash_consumed,
            shares_consumed=reservation_after.shares_consumed,
            cash_released=reservation_after.cash_released,
            shares_released=reservation_after.shares_released,
            cancelled_at=(
                now if reservation_after.status is OrderReservationStatus.CANCELLED else None
            ),
            updated_at=now,
        )
        if updated != 1:
            raise _blocked("ORDER_RESERVATION_STATE_CHANGED", "锁定订单预留状态发生变化")
        trade_id = trade.pk
        reservation_id = reservation_row.pk
        if type(trade_id) is not int or type(reservation_id) is not int:
            raise _blocked("SIMULATED_FILL_WRITE_INVALID", "成交或订单数据库标识不可验证")
        return SimulatedOrderFillResult(
            reservation_id=reservation_id,
            source_namespace=event.source_namespace,
            source_version=event.source_version,
            event_payload_hash=event.event_payload_hash,
            economics=economics,
            reservation=reservation_after,
            trade_id=trade_id,
            replayed=False,
        )


def _signed_difference(left: Decimal, right: Decimal) -> Decimal:
    """Subtract nonnegative ledger values under a wide context for PnL output."""

    with localcontext() as context:
        context.prec = 80
        return left - right
